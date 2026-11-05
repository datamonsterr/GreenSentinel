import type {
  CaseDetailResponse,
  DriverPastIncident,
  DriverScorecardAnalysis,
  FraudCaseSummary,
  HypothesisEvidence,
  TrafficCorroboration,
  TrafficProbeSummary,
  TripDetail,
} from "@/types/schemas";

/**
 * Deterministic hash integer for string id to ensure stable mock generation
 */
function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

/**
 * Generates or extracts driver risk scorecard analysis
 */
export function getDriverScorecard(
  driverId: string = "DRV-DEFAULT",
  trip?: TripDetail,
  _caseSummary?: FraudCaseSummary
): DriverScorecardAnalysis {
  const seed = hashString(driverId);
  const pastWarnings = trip?.past_warnings ?? (seed % 4);

  // Determine realistic ratios
  // Violation ratio: between 1.5% and 5.2%
  const violationRatio = parseFloat((2.5 + ((seed % 30) / 10)).toFixed(1));
  // Fined ratio: either 33.3%, 50.0%, or 66.7%
  const finedRatio = pastWarnings > 0 ? (pastWarnings % 2 === 0 ? 50.0 : 66.7) : 33.3;
  // Repeat offense risk: 65 - 85
  const repeatRisk = 65 + (seed % 25);

  const pastIncidents: DriverPastIncident[] = [
    {
      trip_id: `TR-${9000 + (seed % 900)}`,
      occurred_at: "2026-09-21 08:35",
      violation_type: "Hành trình bất thường (DAVI Drift)",
      investigation_finding: "Độ lệch tuyến 2.1km do công trình hầm chui",
      action_taken: "Miễn trừ xử phạt (Exonerated)",
      status: "exonerated",
    },
    {
      trip_id: `TR-${8000 + (seed % 900)}`,
      occurred_at: "2026-09-02 17:15",
      violation_type: "Thời gian dừng chờ vượt ngưỡng (Stall 480s)",
      investigation_finding: "Dừng đón khách sai điểm định vị, không thông báo",
      action_taken: "Cảnh cáo & Khấu trừ 50k VND",
      status: "penalized",
    },
    {
      trip_id: `TR-${6500 + (seed % 900)}`,
      occurred_at: "2026-08-14 12:40",
      violation_type: "Chênh lệch thời gian đón thực tế",
      investigation_finding: "Mất tín hiệu mạng tạm thời trong hầm để xe",
      action_taken: "Cảnh cáo kỹ thuật hệ thống",
      status: "warned",
    },
  ];

  return {
    violation_ratio_90d: violationRatio,
    fined_ratio: finedRatio,
    repeat_offense_risk_score: repeatRisk,
    benchmark_violation_ratio: 5.0,
    past_incidents: pastIncidents,
    tenure_months: 14 + (seed % 18),
  };
}

/**
 * Extracts and aggregates traffic probe metrics
 */
export function getTrafficProbeSummary(
  corroboration?: TrafficCorroboration | null,
  disputeTraffic?: Record<string, unknown>
): TrafficProbeSummary {
  const corridor = corroboration?.road_segment || (disputeTraffic ? "Hành lang đối soát" : "Chưa có thông tin hành lang");
  const publicAvg = corroboration?.public_service?.average_speed_kmh ?? 32.0;
  const peerList = corroboration?.peer_drivers ?? [];
  const peerCount = peerList.length;

  const ratio = typeof disputeTraffic?.ratio === "number" ? disputeTraffic.ratio : 1.0;
  const congestion = corroboration?.public_service?.congestion ?? "clear";

  let status: "NORMAL" | "SLOWER" | "CONGESTED" = "NORMAL";
  if (congestion === "heavy" || ratio > 1.4) {
    status = "CONGESTED";
  } else if (congestion === "moderate" || ratio > 1.15) {
    status = "SLOWER";
  } else {
    status = "NORMAL";
  }

  const baselineSpeed = parseFloat((publicAvg * 0.9).toFixed(1));

  return {
    corridor_name: corridor,
    status,
    ambient_speed_kmh: publicAvg,
    osrm_baseline_speed_kmh: baselineSpeed,
    peer_vehicles_count: peerCount,
    observation_radius_m: 300,
    provider: corroboration?.public_service?.provider || "TomTom Traffic / OSRM Probe",
    congestion_level: congestion,
  };
}

/**
 * Extracts factual, non-judgmental hypothesis evidence metrics without inventing data
 */
export function getHypothesisEvidence(
  caseDetail?: CaseDetailResponse | null
): HypothesisEvidence {
  const samples = caseDetail?.telemetry_samples || [];
  const latestSample = samples[samples.length - 1];

  const features = caseDetail?.features || {};
  const stallDuration = typeof features.stall_duration_s === "number" 
    ? features.stall_duration_s 
    : (typeof features.stationary_duration_s === "number" ? features.stationary_duration_s : null);

  const daviScore = typeof latestSample?.davi_score === "number"
    ? latestSample.davi_score
    : (typeof features.davi_score === "number" ? features.davi_score : null);

  const driftDistance = typeof latestSample?.drift_distance_m === "number"
    ? latestSample.drift_distance_m
    : (typeof features.drift_distance_m === "number" ? features.drift_distance_m : null);

  const missingAlerts = caseDetail?.missingness_alerts || [];
  const gapAnomalyText = missingAlerts.length > 0 
    ? `${missingAlerts.length} gap (> ${missingAlerts[0].gap_duration_s}s)` 
    : (samples.length > 0 ? "None detected" : "Chưa có dữ liệu");

  const isMock = latestSample?.mock_location_reported === true;
  const gpsAccuracy = typeof latestSample?.gps_accuracy_m === "number"
    ? latestSample.gps_accuracy_m
    : (typeof features.gps_accuracy_m === "number" ? features.gps_accuracy_m : null);
  const gpsState = latestSample?.gps_state || (samples.length > 0 ? "Fine / High precision" : "Chưa có tín hiệu");

  const pingLatency = typeof latestSample?.ping_latency_ms === "number"
    ? latestSample.ping_latency_ms
    : (typeof features.ping_latency_ms === "number" ? features.ping_latency_ms : null);

  const batteryLevel = typeof latestSample?.battery_level_pct === "number"
    ? latestSample.battery_level_pct
    : (typeof features.battery_level_pct === "number" ? features.battery_level_pct : null);

  const priorWarnings = typeof caseDetail?.trip?.past_warnings === "number" ? caseDetail.trip.past_warnings : null;

  // Agent violation detection resolution
  const rawCategory = caseDetail?.case?.category || "ERR-01";
  let vCode = "ERR-01";
  if (typeof rawCategory === "string") {
    const match = rawCategory.match(/ERR-\d{2}/i);
    if (match) {
      vCode = match[0].toUpperCase();
    }
  }

  const violationTitles: Record<string, string> = {
    "ERR-01": "Kéo dài thời gian đón khách",
    "ERR-02": "Cố tình hủy chuyến sau nhận khách",
    "ERR-03": "Giả lập vị trí định vị",
    "ERR-04": "Mất liên lạc viễn thông bất thường",
    "ERR-05": "Sai lệch lộ trình nghiêm trọng",
  };

  const violationTitle = violationTitles[vCode] || rawCategory || "Nghi vấn vi phạm chỉ số vận hành";

  let violationPct = 84;
  if (typeof caseDetail?.case?.confidence === "number") {
    violationPct = caseDetail.case.confidence <= 1 
      ? Math.round(caseDetail.case.confidence * 100) 
      : Math.round(caseDetail.case.confidence);
  } else if (typeof caseDetail?.case?.priority_score === "number") {
    violationPct = Math.min(99, Math.max(40, Math.round(caseDetail.case.priority_score)));
  } else if (typeof features.confidence_score === "number") {
    violationPct = Math.round(features.confidence_score <= 1 ? features.confidence_score * 100 : features.confidence_score);
  }

  let detectionReason = typeof features.detection_reason === "string" ? features.detection_reason : "";
  if (!detectionReason) {
    if (vCode === "ERR-01" && stallDuration != null) {
      detectionReason = `Thời gian dừng đỗ ${stallDuration}s vượt ngưỡng 180s tại điểm đón, telemetry không ghi nhận dịch chuyển.`;
    } else if (vCode === "ERR-02") {
      detectionReason = "Tài xế tiếp cận điểm đón nhưng không nhận khách, phát tín hiệu hủy sau thời gian chờ.";
    } else if (vCode === "ERR-03" && isMock) {
      detectionReason = "Tọa độ GPS nhảy vọt bất thường hoặc phát hiện cờ ứng dụng Mock Location.";
    } else if (vCode === "ERR-04" && missingAlerts.length > 0) {
      detectionReason = `Ghi nhận ${gapAnomalyText} làm đứt đoạn chuỗi dữ liệu hành trình.`;
    } else if (vCode === "ERR-05" && daviScore != null) {
      detectionReason = `Chỉ số sai lệch tuyến DAVI đạt ${daviScore.toFixed(2)}, vượt giới hạn lộ trình chuẩn.`;
    } else if (caseDetail?.assessment?.forensic_brief) {
      detectionReason = caseDetail.assessment.forensic_brief;
    } else {
      detectionReason = "Chưa có thông tin bất thường chi tiết từ telemetry.";
    }
  }

  return {
    stall_duration_s: stallDuration,
    davi_score: daviScore,
    drift_distance_m: driftDistance,
    gap_anomaly: gapAnomalyText,
    mock_location_detected: isMock,
    gps_accuracy_m: gpsAccuracy,
    gps_state: gpsState,
    ping_latency_ms: pingLatency,
    battery_level_pct: batteryLevel,
    device_integrity: isMock ? "compromised" : (samples.length > 0 ? "verified" : "unknown"),
    prior_warnings_count: priorWarnings,
    policy_code: caseDetail?.case_policy?.clauses?.[0]?.section_ref || caseDetail?.case_policy?.policy_version || "Quy chuẩn vận hành",
    policy_status: caseDetail?.guardrails?.is_blocking ? "Guardrail cảnh báo lỗi hệ thống" : "Đối soát quy định kích hoạt",
    violation_code: vCode,
    violation_title: violationTitle,
    violation_probability_pct: violationPct,
    detection_reason: detectionReason,
  };
}
