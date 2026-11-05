"""Jev Advisory Anomaly Scoring and Multi-Layer Jev Assessment Service (Issue #71).

Provides:
- TypeSafe Jev Decision Model integration via OpenRouter `/api/alpha/decisions` (`~typesafe/jev-latest`).
- Multi-input assessment: driver profile, driver analytics, trip conversation, driver's reason/agent chat,
  customer reports, telemetry kinematic maneuvers, and trip data (supporting sparse/optional inputs).
- Multi-layer Jev decisions:
  * Layer 1: Error / Fraud Type classification (ERR-01 to ERR-05, no_violation) + calibrated confidence.
  * Layer 2: Automatic Priority Tier assessment (P0, P1, P2) + priority score (1-100).
- High-precision calibrated fallback heuristic for offline/degraded test operation.
- Single-trip fraud scope: ERR-01 (unjustified cancel), ERR-02 (stall), ERR-03 (detour/wrong direction),
  ERR-04 (ghost trip), ERR-05 (Fake GPS). Network graph fraud is excluded from Phase 1 single-trip real-time scope.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.config import Settings, get_settings
from src.models.schemas import DriverMotivationAssessment
from src.services.guardrails import extract_position, is_valid_coordinate
from src.services.motivation_assessment_service import generate_motivation_assessment
from src.services.route_analytics import haversine_distance_m, parse_timestamp

logger = logging.getLogger(__name__)

OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_JEV_MODEL = "inception/mercury-decide:free"
DEFAULT_FALLBACK_MODELS: list[str] = ["perplexity/pplx-decider-flash-v1.2"]

DEFAULT_SYSTEM_PROMPT = """Bạn là Chuyên gia AI Phân tích Gian lận Giao vận Cao cấp (Jev Decision Engine) của hệ thống GreenSM 2026.
Nhiệm vụ của bạn là phân tích tổng hợp các dữ liệu hành trình cuốc xe đơn (single-trip) bao gồm:
1. Thông tin hồ sơ tài xế (driver profile)
2. Thống kê hành vi tài xế (driver analytics)
3. Hội thoại chuyến đi giữa khách và tài xế (trip conversation)
4. Lý do hủy/giải trình của tài xế và trao đổi với hỗ trợ (driver reason & agent conversation)
5. Báo cáo phản ánh của khách hàng (customer reports)
6. Dữ liệu viễn thông telemetry (GPS, tốc độ, thời gian dừng đỗ, mock location)
7. Dữ liệu chuyến đi (trip data)

Quy chế Hợp tác Kinh doanh GreenSM 2026 quy định các nhóm vi phạm đơn cuốc:
- ERR-01: Hủy chuyến không có lý do chính đáng (Điều 14.1) - Tài xế đơn phương hủy chuyến hoặc cố tình tìm cách né tránh đón khách.
- ERR-02: Cố tình dừng đỗ kéo dài / câu giờ (Điều 14.2) - Đứng yên không tiếp cận điểm đón nhằm ép khách phải hủy chuyến.
- ERR-03: Lệch tuyến / đi lòng vòng cố ý (Điều 16.1) - Di chuyển ngược hướng điểm đón hoặc kéo dài lộ trình di chuyển so với lộ trình dự kiến.
- ERR-04: Cuốc xe ảo / gian lận hoàn thành (Điều 15.1) - Hoàn thành chuyến đi nhưng thực tế không đón chở khách.
- ERR-05: Giả mạo định vị GPS / can thiệp phần mềm (Điều 15.3) - Sử dụng mock location provider, bước nhảy tọa độ hoặc vận tốc tức thời phi thực tế.
- no_violation: Chuyến xe hợp lệ, di chuyển bình thường theo lộ trình, hoặc sự cố khách quan (kẹt xe, thời tiết, hạ tầng mạng) đã được ghi nhận.

LƯU Ý PHẠM VI: Chỉ xử lý gian lận hành vi đơn cuốc (single-trip fraud). Các hình thức gian lận mạng lưới phức tạp (vòng lặp thông đồng tài xế - khách hàng đa tài khoản, bào voucher chuỗi) được chuyển sang pipeline đồ thị ngoại tuyến.
"""


# Passenger completion-denial patterns for the ghost-trip lifecycle fallback
# (issue #264). Anchored to never-boarded / self-completed / charged-without-service
# semantics; generic waiting texts ("đậu đâu", "không thấy xe") are excluded.
_GHOST_DENIAL_PATTERNS: tuple[str, ...] = (
    "cuốc ảo",
    "chuyến ảo",
    "ghost trip",
    "ghost ride",
    "ran a ghost ride",
    "chưa hề lên xe",
    "chưa lên xe",
    "chưa hề bước lên xe",
    "không cần lên xe",
    "chưa đi mét nào",
    "chưa gặp mặt tài xế",
    "chưa ra khỏi nhà",
    "chạy không",
    "về đi",
    "bấm hoàn thành",
    "bấm xong",
    "tự kết thúc",
    "tự bấm",
    "chuyến đã xong",
    "chuyến kết thúc",
    "đã trả khách",
    "cước đã trừ",
    "never got in",
    "never took",
    "never met the driver",
    "no need to get in",
    "close the trip",
    "closed the trip",
    "finished the ride",
    "completed in the app",
    "shows completed",
    "finished by itself",
)


def _collect_denial_texts(value: Any) -> list[str]:
    """Flatten str / {"text": ...} / list thereof into raw text fragments."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        text = value.get("text")
        return [text] if isinstance(text, str) else []
    if isinstance(value, (list, tuple)):
        texts: list[str] = []
        for item in value:
            texts.extend(_collect_denial_texts(item))
        return texts
    return []


def _has_passenger_denial(*values: Any) -> bool:
    for value in values:
        for text in _collect_denial_texts(value):
            lowered = text.lower()
            if any(pattern in lowered for pattern in _GHOST_DENIAL_PATTERNS):
                return True
    return False


class JevAssessmentInput(BaseModel):
    """Structured input container for Jev Anomaly Assessment."""

    model_config = ConfigDict(extra="ignore")

    driver: dict[str, Any] = Field(default_factory=dict)
    driver_analytics: dict[str, Any] = Field(default_factory=dict)
    trip_conversation: list[dict[str, Any]] | str | None = None
    driver_reason_and_agent_conversation: dict[str, Any] | list[dict[str, Any]] | str | None = None
    customer_reports: dict[str, Any] | list[dict[str, Any]] | str | None = None
    telemetry: dict[str, Any] = Field(default_factory=dict)
    trip_data: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str | None = None
    state_variant: str = "evidence_classref"
    criteria_variant: str = "baseline"


class JevApiError(Exception):
    """Exception raised when Jev Decision API fails."""

    def __init__(self, message: str, status_code: int | None = None, fallback_reason: str = "other") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.fallback_reason = fallback_reason


class JevUnavailableError(Exception):
    """Exception raised when all Jev decision models fail or Jev is unavailable without heuristic fallback."""

    def __init__(
        self,
        message: str,
        attempts: list[dict[str, Any]] | None = None,
        last_status: int | None = None,
        last_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts or []
        self.last_status = last_status
        self.last_reason = last_reason


class JevAssessmentResult(BaseModel):
    """Calibrated result from Jev Two-Layer Decision Assessment."""

    model_config = ConfigDict(extra="ignore")

    category: str  # ERR-01, ERR-02, ERR-03, ERR-04, ERR-05, no_violation
    confidence: float  # 0.0 - 1.0
    priority: str  # P0, P1, P2
    priority_tier: int  # 0, 1, 2
    priority_score: int  # 1 - 100
    reason_codes: list[str] = Field(default_factory=list)
    forensic_brief: str = ""
    motivation_assessment: DriverMotivationAssessment = Field(default_factory=DriverMotivationAssessment)
    model_requested: str = DEFAULT_JEV_MODEL
    model_used: str = DEFAULT_JEV_MODEL
    provider: str = ""
    fallback_model_used: bool = False
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    cost: float = 0.0
    assessment_source: str = "model"
    fallback_reason: str | None = None
    http_status: int | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    priority_probabilities: dict[str, float] = Field(default_factory=dict)
    evaluated_features: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_assessment_source(self) -> JevAssessmentResult:
        if self.model_used == "jev_calibrated_heuristic" and self.assessment_source == "model":
            self.assessment_source = "heuristic_fallback"
        return self


_DERIVED_JUMP_THRESHOLD_KMH = 120.0
# A coordinate jump smaller than this multiple of the worst endpoint accuracy is
# GPS jitter, not teleportation (Issue #260: honest trips carry ~700-900 m
# accuracy fixes whose noise exceeds 120 km/h when differenced).
_JITTER_MARGIN = 2.0
# Pairs separated by more than this are stale fixes, not teleportation (mirrors
# feature_engineering FEATURE_PARAMS["max_sample_gap_s"]).
_MAX_JUMP_GAP_S = 30.0


def _derived_jump_speed_kmh(points: list[dict]) -> float:
    """Max corroborated teleportation speed (km/h) from coordinates/timestamps.

    Never trusts caller ``max_speed_kmh`` or per-point ``speed_mps``: producer-reported
    speed is untrusted (Issue #260). A pair counts only when both endpoints are valid
    non-mock coordinates and the displacement exceeds ``_JITTER_MARGIN`` times the
    larger endpoint accuracy (unknown accuracy passes: absence of evidence is not
    evidence of jitter). Returns 0.0 when no corroborated jump exists.
    """
    dicts = [p for p in points if isinstance(p, dict)]
    if len(dicts) < 2:
        return 0.0

    def _ts(p: dict) -> datetime | None:
        try:
            return parse_timestamp(p.get("occurred_at"))
        except Exception:
            return None

    def _acc(v: object) -> float | None:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None

    stamps = [_ts(p) for p in dicts]
    timed: list[tuple[datetime, dict[Any, Any]]] = [(s, p) for s, p in zip(stamps, dicts) if s is not None]
    if len(timed) == len(dicts):
        ordered = [p for _, p in sorted(timed, key=lambda pair: pair[0])]
    elif all(isinstance(p.get("sequence"), (int, float)) and not isinstance(p.get("sequence"), bool) for p in dicts):
        ordered = sorted(dicts, key=lambda p: cast("int | float", p.get("sequence")))
    else:
        ordered = list(dicts)

    best = 0.0
    for prev, curr in zip(ordered, ordered[1:]):
        try:
            if bool(prev.get("mock_location_reported")) or bool(curr.get("mock_location_reported")):
                continue
            if str(prev.get("gps_state") or "").lower() == "mock_reported":
                continue
            if str(curr.get("gps_state") or "").lower() == "mock_reported":
                continue
            pos_a, pos_c = extract_position(prev), extract_position(curr)
            if pos_a is None or pos_c is None:
                continue
            if not is_valid_coordinate(*pos_a) or not is_valid_coordinate(*pos_c):
                continue
            ts_a, ts_c = _ts(prev), _ts(curr)
            if ts_a is None or ts_c is None:
                continue
            elapsed = (ts_c - ts_a).total_seconds()
            if elapsed <= 0 or elapsed > _MAX_JUMP_GAP_S:
                continue
            # extract_position returns (lat, lon); haversine takes (lon, lat).
            displacement = haversine_distance_m((pos_a[1], pos_a[0]), (pos_c[1], pos_c[0]))
            acc_a_v = _acc(prev.get("accuracy_m"))
            acc_c_v = _acc(curr.get("accuracy_m"))
            if acc_a_v is None or acc_c_v is None:
                corroborated = True  # unknown accuracy: do not suppress
            else:
                corroborated = displacement > _JITTER_MARGIN * max(acc_a_v, acc_c_v)
            if corroborated:
                best = max(best, displacement / elapsed * 3.6)
        except Exception:
            continue
    return best


def _err05_result(is_mock: bool, derived_max_kmh: float, features_present: list[str]) -> JevAssessmentResult:
    return JevAssessmentResult(
        category="ERR-05",
        confidence=0.98,
        priority="P0",
        priority_tier=0,
        priority_score=98,
        reason_codes=["mock_location_api_detected", "speed_jump_anomaly", "tampered_provider"],
        forensic_brief=(
            "Forensic Brief — Phát hiện can thiệp định vị giả mạo GPS (mock_location_reported="
            f"{is_mock}, max_speed={round(derived_max_kmh, 1)} km/h derived; "
            "tham chiếu Điều 15.3 Quy chế GreenSM 2026)."
        ),
        model_used="jev_calibrated_heuristic",
        probabilities={"ERR-05": 0.98, "no_violation": 0.02},
        priority_probabilities={"P0": 0.95, "P1": 0.05},
        evaluated_features=features_present,
    )


class JevAssessmentService:
    """Service orchestrating TypeSafe Jev Decision API calls and calibrated fallbacks."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.system_prompt = DEFAULT_SYSTEM_PROMPT

    async def assess(self, inp: JevAssessmentInput) -> JevAssessmentResult:
        """Execute multi-layer Jev assessment across all available operational evidence."""
        # Check available features for audit
        features_present = []
        if inp.driver:
            features_present.append("driver_profile")
        if inp.driver_analytics:
            features_present.append("driver_analytics")
        if inp.trip_conversation:
            features_present.append("trip_conversation")
        if inp.driver_reason_and_agent_conversation:
            features_present.append("driver_agent_conversation")
        if inp.customer_reports:
            features_present.append("customer_reports")
        if inp.telemetry:
            features_present.append("telemetry_kinematics")
        if inp.trip_data:
            features_present.append("trip_metadata")

        api_key = getattr(self.settings, "project_jev_api_key", None) or getattr(
            self.settings, "openrouter_api_key", None
        )
        model_name = (
            getattr(self.settings, "project_jev_model", None)
            or getattr(self.settings, "jev_model", None)
            or DEFAULT_JEV_MODEL
        )
        allow_heuristic = bool(getattr(self.settings, "jev_allow_heuristic_fallback", False))

        if not api_key or api_key in ("mock", "test-key"):
            if not allow_heuristic:
                raise JevUnavailableError(
                    "Jev Decision API key not configured and heuristic fallback is disabled",
                    attempts=[],
                )
            logger.warning("Jev Decision API key not configured, falling back to calibrated heuristic")
            result = self._calibrated_heuristic(inp, features_present)
            result.model_requested = model_name
            result.assessment_source = "heuristic_fallback"
            result.fallback_reason = "missing_api_key"
            return await self._assess_motivation(inp, result)

        try:
            res = await self._call_jev_api(inp, api_key, model_name, features_present)
            if res is not None:
                return await self._assess_motivation(inp, res)
        except JevUnavailableError as exc:
            if not allow_heuristic:
                raise
            logger.warning(
                "All Jev models failed in chain (%s), falling back to calibrated heuristic: %s",
                model_name,
                exc,
            )
            result = self._calibrated_heuristic(inp, features_present)
            result.model_requested = model_name
            result.assessment_source = "heuristic_fallback"
            result.fallback_reason = exc.last_reason or "models_failed"
            result.attempts = exc.attempts
            result.http_status = exc.last_status
            return await self._assess_motivation(inp, result)
        except Exception as exc:
            if not allow_heuristic:
                raise JevUnavailableError(f"Unexpected Jev error: {exc}", attempts=[]) from exc
            logger.warning("Jev Decision API failed (%s), falling back to calibrated heuristic", exc)
            result = self._calibrated_heuristic(inp, features_present)
            result.model_requested = model_name
            result.assessment_source = "heuristic_fallback"
            result.fallback_reason = "unexpected_error"
            return await self._assess_motivation(inp, result)

        if not allow_heuristic:
            raise JevUnavailableError("Jev Decision API returned no result and heuristic fallback is disabled")
        logger.warning("Jev Decision API returned no result, falling back to calibrated heuristic")
        result = self._calibrated_heuristic(inp, features_present)
        result.model_requested = model_name
        result.assessment_source = "heuristic_fallback"
        result.fallback_reason = "no_result"
        return await self._assess_motivation(inp, result)

    async def _assess_motivation(self, inp: JevAssessmentInput, result: JevAssessmentResult) -> JevAssessmentResult:
        """Third assessment stage: evidence-bounded motivation after classification."""
        # Preserve references supplied by the classifier without retaining its
        # verdict-like prose or introducing a new policy source.
        policy_references = list(dict.fromkeys(re.findall(r"Điều \d+(?:\.\d+)*", result.forensic_brief)))
        points = inp.telemetry.get("points") or inp.telemetry.get("telemetry_points") or inp.telemetry.get("samples")
        if not isinstance(points, list):
            points = [inp.telemetry] if inp.telemetry else []
        result.motivation_assessment = await generate_motivation_assessment(
            trip=inp.trip_data,
            features=inp.telemetry,
            telemetry=points,
            evidence_scope=str(inp.trip_data.get("trip_id") or inp.trip_data.get("id") or ""),
        )
        result.forensic_brief = result.motivation_assessment.natural_vietnamese_narrative
        if result.motivation_assessment.economic_incentive_reward == 0:
            # Keep the classification visible in the factual fallback, without
            # reusing the old verdict-like templates. Typed evidence stays in
            # category/reason_codes/evaluated_features.
            result.forensic_brief += f" Nhóm dấu hiệu cần xem xét: {result.category}."
        if policy_references:
            result.forensic_brief = f"Tham chiếu phân loại: {', '.join(policy_references)}. {result.forensic_brief}"
        return result

    async def _call_jev_api(
        self,
        inp: JevAssessmentInput,
        api_key: str,
        primary_model: str,
        features_present: list[str],
    ) -> JevAssessmentResult:
        """Call OpenRouter Jev /api/alpha/decisions endpoint across model chain with retries."""
        from src.services.jev_criteria import get_jev_criteria
        from src.services.jev_state_builder import build_jev_state

        state_payload = build_jev_state(inp, variant=getattr(inp, "state_variant", "evidence_classref"))
        error_type_criteria = get_jev_criteria(variant=getattr(inp, "criteria_variant", "baseline"))

        fallback_models = getattr(self.settings, "jev_fallback_models", None)
        if fallback_models is None:
            fallback_models = DEFAULT_FALLBACK_MODELS

        chain: list[str] = [primary_model]
        for m in fallback_models:
            if m and m not in chain:
                chain.append(m)

        questions = {
            "error_type": {
                "type": "choice",
                "instructions": (
                    f"{inp.system_prompt or self.system_prompt}\n"
                    "Classify the trip into the exact violation code (or 'no_violation') "
                    "based on observable evidence."
                ),
                "criteria": error_type_criteria,
            },
            "priority_tier": {
                "type": "choice",
                "instructions": (
                    "Assess the urgency priority tier of this case based on violation severity, "
                    "passenger impact, and forensic confidence."
                ),
                "criteria": {
                    "P0": "Critical urgency: Fake GPS, high financial/safety exposure, immediate freeze/intervention required",
                    "P1": "High urgency: Prolonged stall, route divergence, passenger dispute requiring prioritized analyst review",
                    "P2": "Medium/Low urgency: Driver cancellation, minor irregularity, nominal low-risk monitoring",
                },
            },
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel",
            "X-Title": "GreenSentinel Jev Anomaly Scoring Engine",
        }

        attempts: list[dict[str, Any]] = []
        last_status: int | None = None
        last_reason: str | None = None
        max_retries = 2

        async with httpx.AsyncClient(timeout=30.0) as client:
            for current_model in chain:
                is_fallback = current_model != primary_model
                request_body = {
                    "model": current_model,
                    "state": state_payload,
                    "questions": questions,
                }

                for attempt_idx in range(1 + max_retries):
                    resp: httpx.Response | None = None
                    err_msg: str | None = None
                    status_code: int | None = None

                    try:
                        resp = await client.post(OPENROUTER_DECISIONS_URL, headers=headers, json=request_body)
                        status_code = resp.status_code
                    except (httpx.TimeoutException, TimeoutError):
                        err_msg = "timeout"
                        status_code = None
                    except Exception as exc:
                        err_msg = str(exc)
                        status_code = None

                    last_status = status_code
                    if status_code == 400:
                        last_reason = "max_tokens_exceeded"
                    elif status_code == 402:
                        last_reason = "insufficient_credits"
                    elif status_code == 429:
                        last_reason = "rate_limit"
                    elif err_msg and "timeout" in err_msg.lower():
                        last_reason = "timeout"
                    elif status_code is not None and status_code != 200:
                        last_reason = "other"
                    elif err_msg:
                        last_reason = "other"

                    if resp is not None and status_code == 200:
                        attempts.append({"model": current_model, "status": 200, "error": None})
                        data = resp.json()
                        answers = data.get("answers", {})
                        error_ans = answers.get("error_type", {})
                        priority_ans = answers.get("priority_tier", {})

                        choice_cat = str(error_ans.get("choice") or "no_violation")
                        conf_val = float(error_ans.get("confidence", 0.90))
                        probs = error_ans.get("probabilities", {})

                        choice_prio = str(priority_ans.get("choice") or "P2")
                        prio_probs = priority_ans.get("probabilities", {})
                        tier_int = 0 if choice_prio == "P0" else (1 if choice_prio == "P1" else 2)

                        if prio_probs and choice_prio in prio_probs:
                            try:
                                p_conf = float(prio_probs[choice_prio])
                            except (ValueError, TypeError):
                                p_conf = 0.95
                            if tier_int == 0:
                                score = min(100, max(90, int(90 + 10 * p_conf)))
                            elif tier_int == 1:
                                score = min(89, max(70, int(70 + 20 * p_conf)))
                            else:
                                score = (
                                    min(69, max(30, int(30 + 35 * p_conf)))
                                    if choice_cat != "no_violation"
                                    else min(29, max(1, int(10 + 15 * p_conf)))
                                )
                        else:
                            score = (
                                98
                                if tier_int == 0
                                else (92 if tier_int == 1 else 70 if choice_cat != "no_violation" else 15)
                            )

                        brief = self._build_forensic_brief(choice_cat, conf_val, tier_int, inp, current_model)
                        reason_codes = self._derive_reason_codes(choice_cat, inp)

                        resolved_model = str(data.get("model") or current_model)
                        provider_name = str(data.get("provider") or "")
                        usage = data.get("usage") or {}
                        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
                        cost = float(usage.get("cost") or 0.0)

                        return JevAssessmentResult(
                            category=choice_cat,
                            confidence=round(conf_val, 2),
                            priority=choice_prio,
                            priority_tier=tier_int,
                            priority_score=score,
                            reason_codes=reason_codes,
                            forensic_brief=brief,
                            model_requested=primary_model,
                            model_used=resolved_model,
                            provider=provider_name,
                            fallback_model_used=is_fallback,
                            attempts=attempts,
                            input_tokens=input_tokens,
                            cost=cost,
                            assessment_source="model",
                            fallback_reason=None,
                            http_status=200,
                            probabilities=probs,
                            priority_probabilities=prio_probs,
                            evaluated_features=features_present,
                        )

                    # Handle failure
                    if resp is not None:
                        err_text = resp.text
                        attempts.append({"model": current_model, "status": status_code, "error": err_text})
                        logger.warning(
                            "OpenRouter Jev model %s attempt %d returned HTTP %d: %s",
                            current_model,
                            attempt_idx + 1,
                            status_code,
                            err_text,
                        )
                        is_retryable = (status_code == 429) or (status_code >= 500)
                    else:
                        attempts.append({"model": current_model, "status": None, "error": err_msg})
                        logger.warning(
                            "OpenRouter Jev model %s attempt %d failed: %s",
                            current_model,
                            attempt_idx + 1,
                            err_msg,
                        )
                        is_retryable = True

                    if is_retryable:
                        if attempt_idx < max_retries:
                            backoff_s = 0.25 * (2**attempt_idx)
                            await asyncio.sleep(backoff_s)
                            continue
                        else:
                            break
                    else:
                        # 4xx other than 429: move to next model immediately, no retry!
                        break

        raise JevUnavailableError(
            f"All Jev models failed in chain: {chain}",
            attempts=attempts,
            last_status=last_status,
            last_reason=last_reason,
        )

    def _calibrated_heuristic(self, inp: JevAssessmentInput, features_present: list[str]) -> JevAssessmentResult:
        """Deterministic calibrated heuristic matching Jev decision boundaries."""
        telem = inp.telemetry or {}
        trip = inp.trip_data or {}

        # 1. Platform outage / Technical dropout / missing telemetry points
        points = telem.get("points") or []
        has_explicit_point_count = "telemetry_points" in telem or "points_count" in telem
        points_count = int(telem.get("points_count", telem.get("telemetry_points", len(points))))
        if (
            telem.get("platform_outage")
            or telem.get("gps_degraded")
            or (has_explicit_point_count and points_count == 0)
        ):
            return JevAssessmentResult(
                category="insufficient_evidence",
                confidence=0.50,
                priority="P2",
                priority_tier=2,
                priority_score=15,
                reason_codes=["insufficient_telemetry_evidence", "technical_dropout_short_circuit"],
                forensic_brief="Forensic Brief — Dữ liệu viễn thông không đủ hoặc có sự cố hạ tầng kỹ thuật; chuyển chuyên viên phân tích xem xét.",
                model_used="jev_calibrated_heuristic",
                evaluated_features=features_present,
            )

        # 2. Fake GPS via mock provider flag. Evaluated before stall: confirmed
        #    provider tampering wins over stall. Reported speed alone never
        #    triggers ERR-05 (Issue #260: producer speed is untrusted).
        points = telem.get("points") or []
        is_mock = bool(telem.get("mock_location_reported")) or any(
            bool(p.get("mock_location_reported")) or p.get("gps_state") == "mock_reported"
            for p in points
            if isinstance(p, dict)
        )
        if is_mock:
            return _err05_result(is_mock, _derived_jump_speed_kmh(points), features_present)

        # 3. Deliberate Prolonged Stall / Refusing to move (ERR-02)
        stationary_s = int(telem.get("stationary_duration_s") or 0)
        maneuvers = telem.get("maneuvers") or []
        has_stop_maneuver = any(m.get("action") == "stop" and m.get("duration_s", 0) >= 180 for m in maneuvers)
        cancellation_reason = str(trip.get("cancellation_reason") or "")
        actor = str(trip.get("cancellation_actor") or "").lower()
        lifecycle = str(trip.get("lifecycle_state") or trip.get("status") or "").lower()

        is_prolonged_stall = stationary_s >= 180 or has_stop_maneuver
        if is_prolonged_stall and lifecycle != "completed" and actor != "driver":
            return JevAssessmentResult(
                category="ERR-02",
                confidence=0.92,
                priority="P1",
                priority_tier=1,
                priority_score=92,
                reason_codes=["stationary_duration_over_180s", "passenger_forced_cancellation", "traffic_nominal"],
                forensic_brief=(
                    f"Forensic Brief — [ERR-02] Ghi nhận thời gian dừng đỗ câu giờ (stationary_duration_s: {stationary_s}s >= 180s; "
                    f"lý do: '{cancellation_reason}'; tham chiếu Điều 14.2 Quy chế GreenSM 2026)."
                ),
                model_used="jev_calibrated_heuristic",
                probabilities={"ERR-02": 0.92, "ERR-01": 0.05, "no_violation": 0.03},
                priority_probabilities={"P1": 0.90, "P0": 0.06, "P2": 0.04},
                evaluated_features=features_present,
            )

        # 4. Derived-speed teleportation jump (ERR-05). Evaluated AFTER stall
        #    (Issue #260 DoD-3): a confirmed stall is not stolen by a speed-only
        #    signal. Uses derived FeatureWindow kinematics only — never caller
        #    max_speed_kmh or reported speed_mps.
        derived_max_kmh = _derived_jump_speed_kmh(points)
        if derived_max_kmh > _DERIVED_JUMP_THRESHOLD_KMH:
            return _err05_result(is_mock, derived_max_kmh, features_present)

        # 5. Route Divergence / Wrong Direction (ERR-03)
        has_wrong_dir = any(m.get("action") == "wrong_direction" for m in maneuvers) or bool(
            telem.get("wrong_direction")
        )
        if has_wrong_dir or "lệch tuyến" in cancellation_reason.lower():
            return JevAssessmentResult(
                category="ERR-03",
                confidence=0.88,
                priority="P1",
                priority_tier=1,
                priority_score=88,
                reason_codes=["wrong_direction_divergence_from_pickup", "excessive_detour"],
                forensic_brief=(
                    "Forensic Brief — Lộ trình xe di chuyển lệch hướng điểm đón hoặc kéo dài lộ trình > 35% "
                    "(tham chiếu Điều 16.1 Quy chế GreenSM 2026)."
                ),
                model_used="jev_calibrated_heuristic",
                probabilities={"ERR-03": 0.88, "no_violation": 0.12},
                priority_probabilities={"P1": 0.88, "P2": 0.12},
                evaluated_features=features_present,
            )

        # 6. Cancellation with sub-threshold stall or ambiguous reason
        if lifecycle == "cancelled":
            if actor == "driver" and (
                "vô cớ" in cancellation_reason.lower()
                or "từ chối" in cancellation_reason.lower()
                or "unjustified" in cancellation_reason.lower()
            ):
                return JevAssessmentResult(
                    category="ERR-01",
                    confidence=0.85,
                    priority="P2",
                    priority_tier=2,
                    priority_score=70,
                    reason_codes=["unjustified_driver_cancellation"],
                    forensic_brief=(
                        f"Forensic Brief — [ERR-01] Chuyến xe bị hủy đơn phương bởi tài xế "
                        f"(lý do: '{cancellation_reason}'; tham chiếu Điều 14.1 Quy chế GreenSM 2026)."
                    ),
                    model_used="jev_calibrated_heuristic",
                    probabilities={"ERR-01": 0.85, "no_violation": 0.15},
                    priority_probabilities={"P2": 0.85, "P1": 0.15},
                    evaluated_features=features_present,
                )
            return JevAssessmentResult(
                category="insufficient_evidence",
                confidence=0.0,
                priority="P2",
                priority_tier=2,
                priority_score=30,
                reason_codes=["cancellation_below_threshold_or_ambiguous"],
                forensic_brief="Forensic Brief — Dữ liệu hủy chuyến chưa đủ bằng chứng kết luận vi phạm; cần chuyên viên thẩm định.",
                model_used="jev_calibrated_heuristic",
                evaluated_features=features_present,
            )

        # 7. Ghost Ride (ERR-04)
        if "ảo" in cancellation_reason.lower() or "ghost" in cancellation_reason.lower():
            return JevAssessmentResult(
                category="ERR-04",
                confidence=0.91,
                priority="P1",
                priority_tier=1,
                priority_score=90,
                reason_codes=["unfulfilled_passenger_ghost_trip"],
                forensic_brief="Forensic Brief — [ERR-04] Phát hiện hoàn thành chuyến ảo không có hành khách (tham chiếu Điều 15.1).",
                model_used="jev_calibrated_heuristic",
                probabilities={"ERR-04": 0.91, "no_violation": 0.09},
                priority_probabilities={"P1": 0.90, "P0": 0.10},
                evaluated_features=features_present,
            )

        # 7b. Ghost-trip lifecycle fallback (issue #264): completed lifecycle with
        # known never-arrived pickup (arrived_at/started_at keys present-None) plus
        # passenger completion-denial text. Missing arrival keys = unknown, so the
        # rule fails closed. Advisory only: P1 analyst review, never auto-action.
        never_arrived = (
            "arrived_at" in trip
            and "started_at" in trip
            and trip.get("arrived_at") is None
            and trip.get("started_at") is None
        )
        if (
            lifecycle == "completed"
            and never_arrived
            and _has_passenger_denial(
                inp.customer_reports,
                inp.trip_conversation,
                inp.driver_reason_and_agent_conversation,
            )
        ):
            return JevAssessmentResult(
                category="ERR-04",
                confidence=0.91,
                priority="P1",
                priority_tier=1,
                priority_score=90,
                reason_codes=[
                    "ghost_trip_unfulfilled",
                    "completed_without_pickup",
                    "passenger_denial_present",
                ],
                forensic_brief=(
                    "Forensic Brief — [ERR-04] Chuyến xe ở trạng thái hoàn thành nhưng không ghi nhận "
                    "thời điểm đón khách (arrived_at/started_at đều vắng) kèm phản ánh phủ nhận sử dụng "
                    "dịch vụ từ hành khách (tham chiếu Điều 15.1 Quy chế GreenSM 2026). "
                    "Khuyến nghị chuyển chuyên viên phân tích xem xét; đây là tín hiệu tư vấn, "
                    "không tự động xử lý."
                ),
                model_used="jev_calibrated_heuristic",
                probabilities={"ERR-04": 0.91, "no_violation": 0.09},
                priority_probabilities={"P1": 0.90, "P0": 0.10},
                evaluated_features=features_present,
            )

        # 8. Completed Nominal Trip
        return JevAssessmentResult(
            category="no_violation",
            confidence=0.95,
            priority="P2",
            priority_tier=2,
            priority_score=15,
            reason_codes=["telemetry_nominal", "trip_completed_normally"],
            forensic_brief="Forensic Brief — Không ghi nhận chỉ số bất thường. Lộ trình và động học danh định.",
            model_used="jev_calibrated_heuristic",
            probabilities={"no_violation": 0.95, "ERR-01": 0.05},
            priority_probabilities={"P2": 0.95, "P1": 0.05},
            evaluated_features=features_present,
        )

    def _build_forensic_brief(
        self,
        category: str,
        confidence: float,
        tier: int,
        inp: JevAssessmentInput,
        model_name: str,
    ) -> str:
        telem = inp.telemetry or {}
        stall = telem.get("stationary_duration_s", 0)
        cancellation = inp.trip_data.get("cancellation_reason", "")
        conf_pct = int(confidence * 100)

        mapping = {
            "ERR-01": f"Forensic Brief — Jev AI ({model_name}, {conf_pct}%) [ERR-01] nhận định tài xế đơn phương hủy cuốc vô cớ (Điều 14.1).",
            "ERR-02": f"Forensic Brief — Jev AI ({model_name}, {conf_pct}%) [ERR-02] xác nhận cố tình dừng đỗ câu giờ ({stall}s >= 180s; '{cancellation}'; Điều 14.2).",
            "ERR-03": f"Forensic Brief — Jev AI ({model_name}, {conf_pct}%) [ERR-03] phát hiện lộ trình di chuyển lệch tuyến / ngược hướng (Điều 16.1).",
            "ERR-04": f"Forensic Brief — Jev AI ({model_name}, {conf_pct}%) [ERR-04] phát hiện dấu hiệu chuyến đi ảo (Điều 15.1).",
            "ERR-05": f"Forensic Brief — Jev AI ({model_name}, {conf_pct}%) [ERR-05] phát hiện can thiệp định vị giả mạo GPS (Điều 15.3).",
            "no_violation": f"Forensic Brief — Jev AI ({model_name}, {conf_pct}%) xác nhận chuyến xe không có hành vi vi phạm.",
        }
        return mapping.get(category, f"Forensic Brief — Jev AI phân loại {category} ({conf_pct}%).")

    def _derive_reason_codes(self, category: str, inp: JevAssessmentInput) -> list[str]:
        codes = []
        if category == "ERR-05":
            codes.extend(["mock_location_detected", "speed_jump_anomaly"])
        elif category == "ERR-02":
            codes.extend(["stationary_duration_over_180s", "stall_anomaly"])
        elif category == "ERR-03":
            codes.extend(["route_divergence", "wrong_direction"])
        elif category == "ERR-01":
            codes.extend(["driver_cancellation"])
        elif category == "ERR-04":
            codes.extend(["ghost_trip_unfulfilled"])
        else:
            codes.append("telemetry_nominal")

        if inp.customer_reports:
            codes.append("customer_complaint_present")
        if inp.driver_analytics and inp.driver_analytics.get("prior_sanctions_count", 0) > 0:
            codes.append("prior_driver_sanctions")
        return codes


_jev_assessment_service_instance: JevAssessmentService | None = None


def get_jev_assessment_service() -> JevAssessmentService:
    global _jev_assessment_service_instance
    if _jev_assessment_service_instance is None:
        _jev_assessment_service_instance = JevAssessmentService()
    return _jev_assessment_service_instance
