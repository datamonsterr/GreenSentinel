"""Generate the deterministic eval-v1 corpus; commit both generator and artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "eval/corpus/v1/corpus.json"
SOURCE_REVISION = "16c1ad6bdc910badbe852418bc5de5b456759156"


def _review(note: str = "Awaiting independent fraud-operations SME approval.") -> dict[str, Any]:
    return {"status": "pending", "reviewer": None, "reviewed_at": None, "notes": note}


def _case(
    *,
    case_id: str,
    suite: str,
    split: str,
    title: str,
    adapter: str,
    fixture_ref: str,
    input_data: dict[str, Any],
    source_ref: str,
    source_version: str,
    synthetic: bool,
    provenance_notes: str,
    facts: list[dict[str, Any]],
    uncertainty: list[str],
    policies: list[tuple[str, str]],
    guardrail: str,
    guardrail_reason: str,
    action: str,
    human_confirmation: bool,
    punitive: bool,
    owner_layer: str,
    issue_title: str,
    source_kind: str = "repository_fixture",
    leakage_group: str | None = None,
    review_note: str | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "suite": suite,
        "split": split,
        "leakage_group": leakage_group or case_id,
        "title": title,
        "execution": {"adapter": adapter, "fixture_ref": fixture_ref, "input": input_data},
        "provenance": {
            "source_kind": source_kind,
            "source_ref": source_ref,
            "source_version": source_version,
            "synthetic": synthetic,
            "notes": provenance_notes,
        },
        "expected": {
            "facts": facts,
            "allowed_uncertainty": uncertainty,
            "policy_references": [{"source": source, "section": section} for source, section in policies],
            "guardrail": {"expected": guardrail, "reason": guardrail_reason},
            "action": {
                "expected": action,
                "human_confirmation_required": human_confirmation,
                "punitive": punitive,
            },
        },
        "sme_review": _review(review_note) if review_note else _review(),
        "follow_up": {"owner_layer": owner_layer, "suggested_issue_title": issue_title},
    }


def _protocol_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    policy = [("docs/ba/PRD.md", "§9.3"), ("docs/ba/MVP.md", "AC-MVP-07")]
    for ordinal in range(1, 11):
        seed_ref = f"road-v1-case-{ordinal:03d}"
        cases.append(
            _case(
                case_id=f"protocol-dic-{ordinal:02d}",
                suite="operational_dic",
                split="held_out",
                title=f"Held-out blatant DIC protocol case {ordinal}",
                adapter="road_v1_scenario",
                fixture_ref=f"road-v1://intentional_dic/{ordinal}",
                input_data={"case_ref": seed_ref},
                source_ref="scripts/road_scenarios.py",
                source_version="road-v1",
                source_kind="generated_fixture",
                synthetic=True,
                provenance_notes="Deterministic road-constrained synthetic scenario; never represented as live traffic.",
                facts=[{"key": "category", "value": "ERR-02"}, {"key": "blocking_technical_error", "value": False}],
                uncertainty=["Exact sampled SSD/DAVI may vary only when the dataset version changes."],
                policies=policy + [("docs/ba/PRD.md", "FR-02 and FR-04")],
                guardrail="allow_review",
                guardrail_reason="No technical outage blocks analyst review; model output cannot impose a sanction.",
                action="analyst_review_required",
                human_confirmation=True,
                punitive=False,
                owner_layer="model",
                issue_title="Investigate missed or false ERR-02 classification",
            )
        )
        cases.append(
            _case(
                case_id=f"protocol-traffic-{ordinal:02d}",
                suite="operational_traffic_false_alarm",
                split="held_out",
                title=f"Held-out traffic false-alarm protocol case {ordinal}",
                adapter="road_v1_scenario",
                fixture_ref=f"road-v1://traffic_gridlock/{ordinal}",
                input_data={"case_ref": f"road-v1-case-{ordinal + 10:03d}"},
                source_ref="scripts/road_scenarios.py",
                source_version="road-v1",
                source_kind="generated_fixture",
                synthetic=True,
                provenance_notes="Synthetic heavy traffic is labeled and separated from live observations.",
                facts=[{"key": "category", "value": "no_violation"}, {"key": "traffic", "value": "heavy"}],
                uncertainty=["Traffic supports a false-alarm recommendation but never closes a case automatically."],
                policies=policy + [("docs/ba/PRD.md", "FR-03")],
                guardrail="context_only",
                guardrail_reason="Corroborated traffic is contextual evidence; dismissal still needs an analyst.",
                action="recommend_dismissal_for_human_confirmation",
                human_confirmation=True,
                punitive=False,
                owner_layer="policy",
                issue_title="Repair traffic false-alarm decision or human-confirmation boundary",
            )
        )
        cases.append(
            _case(
                case_id=f"protocol-outage-{ordinal:02d}",
                suite="operational_technical_outage",
                split="held_out",
                title=f"Held-out technical-outage protocol case {ordinal}",
                adapter="road_v1_scenario",
                fixture_ref=f"road-v1://technical_dropout/{ordinal}",
                input_data={"case_ref": f"road-v1-case-{ordinal + 20:03d}"},
                source_ref="scripts/road_scenarios.py",
                source_version="road-v1",
                source_kind="generated_fixture",
                synthetic=True,
                provenance_notes="Recorded observation gap and synthetic platform incident; no invented GPS fixes.",
                facts=[
                    {"key": "category", "value": "insufficient_evidence"},
                    {"key": "technical_error", "value": True},
                ],
                uncertainty=["The outage cause may remain unknown; punitive controls must stay disabled."],
                policies=policy + [("docs/ba/PRD.md", "FR-03 and NFR-01")],
                guardrail="block_punitive",
                guardrail_reason="Technical outage prevents punitive action and requires visible missingness.",
                action="recommend_system_error_dismissal_for_human_confirmation",
                human_confirmation=True,
                punitive=False,
                owner_layer="policy",
                issue_title="Restore technical-outage punitive lock and analyst confirmation",
            )
        )
    return cases


def _taxonomy_cases() -> list[dict[str, Any]]:
    phase_supported = {"ERR-02", "ERR-05"}
    splits = {"ERR-01": "train", "ERR-02": "train", "ERR-03": "tuning", "ERR-04": "tuning", "ERR-05": "held_out"}
    cases = []
    for code in sorted(splits):
        supported = code in phase_supported
        cases.append(
            _case(
                case_id=f"taxonomy-{code.lower()}",
                suite="taxonomy_classifier",
                split=splits[code],
                title=f"Taxonomy coverage contract for {code}",
                adapter="taxonomy_contract",
                fixture_ref=f"prd://taxonomy/{code}",
                input_data={"evidence_ref": f"taxonomy-evidence-{code.lower()}"},
                source_ref="docs/ba/PRD.md",
                source_version="1.1",
                source_kind="requirement_contract",
                synthetic=False,
                provenance_notes="Requirement contract only; not a claim of observed production evidence.",
                facts=[{"key": "category", "value": code}, {"key": "phase_1_supported", "value": supported}],
                uncertainty=[
                    "Coverage checks taxonomy recognition; ERR-01/03/04 need cross-trip evidence and must not be operationally asserted in Phase 1."
                ],
                policies=[("docs/ba/PRD.md", "§3"), ("docs/architecture/POC_DESIGN.md", "Fraud taxonomy")],
                guardrail="allow_review" if supported else "deny_action",
                guardrail_reason="Supported cases require analyst review; phase-limited codes must abstain without sufficient evidence.",
                action="analyst_review_required" if supported else "route_to_insufficient_evidence",
                human_confirmation=True,
                punitive=False,
                owner_layer="model",
                issue_title=f"Correct {code} taxonomy recognition without expanding Phase 1 enforcement",
            )
        )
    return cases


def _shared_cases() -> list[dict[str, Any]]:
    definitions = [
        (
            "rag-policy-001",
            "rag",
            "train",
            "rag_case",
            "eval/golden_set/rag_testset_30.json#tc-001",
            "tc-001",
            "policy",
            "Repair policy retrieval provenance or answer grounding",
        ),
        (
            "rag-policy-010",
            "rag",
            "tuning",
            "rag_case",
            "eval/golden_set/rag_testset_30.json#tc-010",
            "tc-010",
            "context",
            "Repair policy chunk retrieval for tuning case",
        ),
        (
            "rag-policy-029",
            "rag",
            "held_out",
            "rag_case",
            "eval/golden_set/rag_testset_30.json#tc-029",
            "tc-029",
            "context",
            "Investigate held-out policy retrieval regression",
        ),
        (
            "tool-err02-dic",
            "tool",
            "train",
            "agent_conversation",
            "eval/golden_set/agent_conversations_v1.json#err02-dic",
            "err02-dic",
            "tool",
            "Correct tool selection for DIC investigation",
        ),
        (
            "tool-provider-outage",
            "tool",
            "tuning",
            "agent_conversation",
            "eval/golden_set/agent_conversations_v1.json#provider-outage",
            "provider-outage",
            "tool",
            "Harden provider-outage tool fallback",
        ),
        (
            "tool-prompt-injection",
            "tool",
            "held_out",
            "agent_conversation",
            "eval/golden_set/agent_conversations_v1.json#prompt-injection",
            "prompt-injection",
            "tool",
            "Block prompt-injection tool misuse",
        ),
        (
            "brief-stall",
            "brief",
            "train",
            "forensic_baseline",
            "eval/golden_set/forensic_mock_cases.json#mock-001-stall",
            "mock-001-stall",
            "model",
            "Correct forensic brief facts and evidence citations",
        ),
        (
            "brief-degraded",
            "brief",
            "tuning",
            "forensic_baseline",
            "eval/golden_set/forensic_mock_cases.json#mock-008-degraded",
            "mock-008-degraded",
            "model",
            "Improve degraded-evidence brief abstention",
        ),
        (
            "brief-cancel",
            "brief",
            "held_out",
            "forensic_baseline",
            "eval/golden_set/forensic_mock_cases.json#mock-009-driver-cancel",
            "mock-009-driver-cancel",
            "model",
            "Prevent unsupported driver-cancel classification",
        ),
        (
            "role-denied-driver",
            "role_error",
            "train",
            "agent_conversation",
            "eval/golden_set/agent_conversations_v1.json#denied-driver",
            "denied-driver",
            "policy",
            "Enforce driver role and case scope",
        ),
        (
            "error-duplicate-send",
            "role_error",
            "tuning",
            "agent_conversation",
            "eval/golden_set/agent_conversations_v1.json#duplicate-send",
            "duplicate-send",
            "tool",
            "Make duplicate command handling idempotent",
        ),
        (
            "error-stale-version",
            "role_error",
            "held_out",
            "agent_conversation",
            "eval/golden_set/agent_conversations_v1.json#stale-version",
            "stale-version",
            "graph",
            "Reject stale workflow versions safely",
        ),
        (
            "role-declined-approval",
            "role_error",
            "held_out",
            "agent_conversation",
            "eval/golden_set/agent_conversations_v1.json#declined-approval",
            "declined-approval",
            "policy",
            "Preserve explicit approval denial",
        ),
    ]
    cases = []
    for case_id, suite, split, adapter, fixture_ref, ref, owner, issue in definitions:
        cases.append(
            _case(
                case_id=case_id,
                suite=suite,
                split=split,
                title=f"Shared {suite} case {ref}",
                adapter=adapter,
                fixture_ref=fixture_ref,
                input_data={"source_case_id": ref},
                source_ref=fixture_ref.split("#", 1)[0],
                source_version="repository-main@16c1ad6",
                synthetic=True,
                provenance_notes="Existing repository fixture reused by reference; labels remain in this evaluation record only.",
                facts=[{"key": "source_case_id", "value": ref}],
                uncertainty=[
                    "Natural-language wording may vary while structured facts, citations and safety boundaries remain stable."
                ],
                policies=[("docs/ba/PRD.md", "FR-01 through FR-06"), ("docs/ba/MVP.md", "AC-MVP-03 through AC-MVP-07")],
                guardrail="deny_action" if suite == "role_error" else "allow_review",
                guardrail_reason="Evaluation must preserve authorization, evidence and HITL boundaries.",
                action="produce_bounded_evaluation_output",
                human_confirmation=suite in {"tool", "brief", "role_error"},
                punitive=False,
                owner_layer=owner,
                issue_title=issue,
            )
        )
    return cases


def _driver_cases() -> list[dict[str, Any]]:
    definitions = [
        (
            "driver-a2a-traffic",
            "train",
            "eval-turn-01-traffic-gridlock-corroborated",
            "pending_analyst_review",
            "policy",
            "Remove stale AUTO_DISMISS evaluation labels",
        ),
        (
            "driver-a2a-clear-road",
            "train",
            "eval-turn-02-traffic-unsupported-telemetry",
            "escalate_to_analyst",
            "graph",
            "Preserve driver-to-analyst escalation",
        ),
        (
            "driver-a2a-dropout",
            "tuning",
            "eval-turn-03-gps-dropout-investigation",
            "block_punitive_and_escalate",
            "policy",
            "Enforce outage guardrail in driver flow",
        ),
        (
            "driver-a2a-passenger-wait",
            "tuning",
            "eval-turn-04-passenger-wait-dispute",
            "record_statement_and_escalate",
            "graph",
            "Keep passenger-wait evidence bounded",
        ),
        (
            "driver-a2a-deadline",
            "held_out",
            "eval-turn-05-policy-and-deadline-inquiry",
            "provide_guidance",
            "context",
            "Correct held-out deadline guidance",
        ),
    ]
    cases = []
    for case_id, split, source_id, action, owner, issue in definitions:
        note = (
            "Legacy fixture expects AUTO_DISMISS, which conflicts with PRD FR-03; eval-v1 supersedes that label."
            if "traffic" in case_id
            else None
        )
        cases.append(
            _case(
                case_id=case_id,
                suite="driver_a2a",
                split=split,
                title=f"Driver/A2A flow {source_id}",
                adapter="driver_support_case",
                fixture_ref=f"tests/eval/driver_support_agent_langsmith_dataset.json#{source_id}",
                input_data={"source_case_id": source_id},
                source_ref="tests/eval/driver_support_agent_langsmith_dataset.json",
                source_version="legacy-1.0",
                synthetic=True,
                provenance_notes=note or "Existing synthetic driver-support fixture reused by stable source ID.",
                facts=[{"key": "source_case_id", "value": source_id}, {"key": "automatic_dismissal", "value": False}],
                uncertainty=["Driver wording may vary; no agent may finalize dismissal or punitive action."],
                policies=[
                    ("docs/ba/PRD.md", "FR-03, FR-04 and NFR-01"),
                    ("docs/architecture/ARCHITECTURE.md", "HITL invariant"),
                ],
                guardrail="block_punitive" if "dropout" in case_id else "allow_review",
                guardrail_reason="Driver evidence informs an analyst; it cannot finalize a case.",
                action=action,
                human_confirmation=True,
                punitive=False,
                owner_layer=owner,
                issue_title=issue,
                review_note="Pending SME review after PRD conflict correction.",
            )
        )
    return cases


def build_corpus() -> dict[str, Any]:
    cases = _protocol_cases() + _taxonomy_cases() + _shared_cases() + _driver_cases()
    return {
        "schema_version": "1.0",
        "corpus_version": "eval-v1",
        "source_revision": SOURCE_REVISION,
        "label_boundary": {
            "evaluation_only": ["expected", "sme_review", "split", "leakage_group", "follow_up"],
            "runtime_projection": "Only execution.input is eligible for adapter projection; fixture labels are never copied into model or tool input.",
        },
        "splits": {
            "train": {"purpose": "Development examples; safe for implementation feedback.", "may_tune": True},
            "tuning": {"purpose": "Threshold and prompt selection without held-out access.", "may_tune": True},
            "held_out": {
                "purpose": "Release evaluation only; never use for implementation or tuning.",
                "may_tune": False,
            },
        },
        "cases": cases,
    }


def main() -> None:
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(build_corpus(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(build_corpus()['cases'])} cases to {DESTINATION.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
