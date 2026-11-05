"""Tool catalog mapping canonical operations, surface aliases, permissions, and schemas.

Refs #60, #85.
"""

from __future__ import annotations

from typing import Any, Literal

from src.models.tool_contracts import ToolCatalogEntry, ToolExecutionContext, ToolResult

ANALYST_SURFACE_NAMES = frozenset(
    {
        "get_case_detail",
        "list_cases",
        "claim_case",
        "record_case_action",
        "adjudicate_case",
        "query_policy",
        "trigger_simulation",
        "get_driver_history",
        "query_cases_db",
        "check_driver_suspension",
        "check_weather_condition",
        "check_traffic_situation",
        "fetch_corridor_historical_traffic",
        "query_traffic_incident_feed",
        "write_ticket_for_driver",
        "check_related_cases_to_vehicle",
        "get_driver_card",
        "search_policy_documents",
        "geocode_address",
        "reverse_geocode_coordinates",
        "match_trip_telemetry",
    }
)

COCKPIT_SURFACE_NAMES = frozenset(
    {
        "search_policy",
        "search_policy_documents",
        "get_driver_card",
        "get_driver_trip_history",
        "check_driver_suspension",
        "list_cases",
        "get_case_information",
        "get_driver_profile",
        "get_telemetry",
        "get_case_list_priority",
        "get_audit_log",
        "check_weather_condition",
        "check_traffic_situation",
        "fetch_corridor_historical_traffic",
        "query_traffic_incident_feed",
        "write_ticket_for_driver",
        "check_related_cases_to_vehicle",
        "geocode_address",
        "reverse_geocode_coordinates",
        "match_trip_telemetry",
    }
)

DRIVER_SURFACE_NAMES = frozenset(
    {
        "get_driver_dispute_context",
        "corroborate_traffic_conditions",
        "fetch_corridor_historical_traffic",
        "query_traffic_incident_feed",
        "inspect_trip_telemetry",
        "verify_exoneration_rules",
        "submit_driver_statement",
        "query_driver_policy",
        "geocode_address",
        "reverse_geocode_coordinates",
        "match_trip_telemetry",
        "list_my_cases",
        "get_case_timeline",
        "explain_case_status",
        "get_my_scorecard",
        "list_my_trips",
        "get_trip_summary",
        "check_weather_condition",
        "check_traffic_situation",
        "get_forensic_brief",
        "suggest_dispute_path",
        "assess_statement_completeness",
        "get_appeal_options",
    }
)

FORBIDDEN_MODEL_COMMANDS = frozenset(
    {
        "claim_case",
        "record_case_action",
        "adjudicate_case",
        "trigger_simulation",
        "write_ticket_for_driver",
        "submit_driver_statement",
    }
)

# Canonical entries
CATALOG_ENTRIES: list[ToolCatalogEntry] = [
    ToolCatalogEntry(
        canonical_id="get_case_context",
        surface_names=["get_case_detail", "get_case_information", "get_driver_dispute_context"],
        actor="both",
        purpose="Retrieve case identifiers, factual brief, timeline, and evidence availability.",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string", "description": "Case identifier"}},
            "required": ["case_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "status": {"type": "string"},
                "dispute": {"type": "object"},
            },
            "required": ["case_id"],
        },
        error_codes=["NOT_FOUND", "FORBIDDEN", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="list_cases",
        surface_names=["list_cases", "get_case_list_priority"],
        actor="analyst",
        purpose="List and filter fraud cases by status, priority, or assignment.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by case status"},
                "priority": {"type": "string", "description": "Filter by priority"},
                "limit": {"type": "integer", "description": "Maximum cases to return"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {"cases": {"type": "array"}, "count": {"type": "integer"}},
            "required": ["cases", "count"],
        },
        error_codes=["FORBIDDEN", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="inspect_trip_telemetry",
        surface_names=["inspect_trip_telemetry", "get_telemetry"],
        actor="both",
        purpose="Retrieve GPS breadcrumbs, speed, jitter, and mock-location signals for a trip.",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string", "description": "Case identifier"}},
            "required": ["case_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "points": {"type": "array"},
                "summary": {"type": "object"},
            },
            "required": ["case_id"],
        },
        error_codes=["NOT_FOUND", "SOURCE_UNAVAILABLE", "FORBIDDEN"],
        provenance_kind="dataset",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="check_traffic_situation",
        surface_names=["check_traffic_situation", "corroborate_traffic_conditions"],
        actor="both",
        purpose="Retrieve verified road traffic congestion, speed, and delays along the trip route.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
                "trip_id": {"type": "string", "description": "Trip identifier"},
                "latitude": {"type": "number", "description": "Optional latitude point"},
                "longitude": {"type": "number", "description": "Optional longitude point"},
                "start_lat": {"type": "number", "description": "Route start latitude"},
                "start_lon": {"type": "number", "description": "Route start longitude"},
                "end_lat": {"type": "number", "description": "Route end latitude"},
                "end_lon": {"type": "number", "description": "Route end longitude"},
            },
        },
        output_schema={"type": "object"},
        error_codes=["SOURCE_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"],
        provenance_kind="provider",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="fetch_corridor_historical_traffic",
        surface_names=["fetch_corridor_historical_traffic"],
        actor="both",
        purpose="Assess historical corridor congestion from same-organization first-party peer GPS telemetry.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["VALIDATION_ERROR", "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
        timeout_seconds=10,
    ),
    ToolCatalogEntry(
        canonical_id="query_traffic_incident_feed",
        surface_names=["query_traffic_incident_feed"],
        actor="both",
        purpose="Find external traffic incidents relevant to a case corridor and time window.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["VALIDATION_ERROR", "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT"],
        provenance_kind="provider",
        side_effects=False,
        model_selectable=True,
        timeout_seconds=10,
    ),
    ToolCatalogEntry(
        canonical_id="check_weather_condition",
        surface_names=["check_weather_condition"],
        actor="both",
        purpose="Retrieve weather conditions, rain, wind, and visibility at trip time and location.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
                "trip_id": {"type": "string", "description": "Trip identifier"},
                "latitude": {"type": "number", "description": "Location latitude"},
                "longitude": {"type": "number", "description": "Location longitude"},
                "lat": {"type": "number", "description": "Location latitude"},
                "lon": {"type": "number", "description": "Location longitude"},
                "time_iso": {"type": "string", "description": "Timestamp in ISO 8601"},
            },
        },
        output_schema={"type": "object"},
        error_codes=["SOURCE_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"],
        provenance_kind="provider",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="get_driver_history",
        surface_names=[
            "get_driver_history",
            "get_driver_trip_history",
            "get_driver_card",
            "get_driver_profile",
            "check_driver_suspension",
        ],
        actor="both",
        purpose="Retrieve driver operating standing, rating, trip stats, and suspension history.",
        input_schema={
            "type": "object",
            "properties": {
                "driver_identifier": {
                    "type": "string",
                    "description": "Driver ID, plate number, or name",
                }
            },
            "required": ["driver_identifier"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "driver_id": {"type": "string"},
                "standing": {"type": "string"},
                "rating": {"type": "number"},
            },
            "required": ["driver_id"],
        },
        error_codes=["NOT_FOUND", "FORBIDDEN"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="check_related_cases_to_vehicle",
        surface_names=["check_related_cases_to_vehicle"],
        actor="analyst",
        purpose="Find past or concurrent dispute/fraud cases associated with the same vehicle.",
        input_schema={
            "type": "object",
            "properties": {
                "vehicle_identifier": {
                    "type": "string",
                    "description": "Plate number or vehicle ID",
                }
            },
            "required": ["vehicle_identifier"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "vehicle_id": {"type": "string"},
                "related_cases": {"type": "array"},
            },
            "required": ["vehicle_id", "related_cases"],
        },
        error_codes=["FORBIDDEN", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="search_policy_documents",
        surface_names=["search_policy_documents", "search_policy", "query_policy", "query_driver_policy"],
        actor="both",
        purpose="Search GreenSM regulations, terms, dispute rules, and force majeure articles.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or keywords"},
                "category": {"type": "string", "description": "Optional category filter"},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "results": {"type": "array"},
                "citations": {"type": "array"},
            },
            "required": ["query", "results"],
        },
        error_codes=["SOURCE_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"],
        provenance_kind="provider",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="verify_exoneration_rules",
        surface_names=["verify_exoneration_rules"],
        actor="driver",
        purpose="Advisory evaluation of dispute corroboration against policy rules (no auto-action).",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
                "claim_type": {"type": "string", "description": "Claim category"},
            },
            "required": ["case_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "claim_type": {"type": "string"},
                "qualifies_for_exoneration": {"type": "boolean"},
                "metrics": {"type": "object"},
            },
            "required": ["case_id", "qualifies_for_exoneration"],
        },
        error_codes=["NOT_FOUND", "FORBIDDEN"],
        provenance_kind="composite",
        side_effects=False,
        model_selectable=True,
    ),
    # Human-only commands (Disabled from model selection)
    ToolCatalogEntry(
        canonical_id="claim_case",
        surface_names=["claim_case"],
        actor="analyst",
        purpose="HUMAN ONLY: Claim review lease on a case.",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string"}, "analyst_id": {"type": "string"}},
            "required": ["case_id", "analyst_id"],
        },
        output_schema={"type": "object", "properties": {"success": {"type": "boolean"}}},
        error_codes=["FORBIDDEN", "CONFLICT"],
        provenance_kind="database",
        side_effects=True,
        model_selectable=False,
    ),
    ToolCatalogEntry(
        canonical_id="record_case_action",
        surface_names=["record_case_action"],
        actor="analyst",
        purpose="HUMAN ONLY: Record an audit action or note on a case.",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string"}, "action": {"type": "string"}},
            "required": ["case_id", "action"],
        },
        output_schema={"type": "object", "properties": {"recorded": {"type": "boolean"}}},
        error_codes=["FORBIDDEN"],
        provenance_kind="database",
        side_effects=True,
        model_selectable=False,
    ),
    ToolCatalogEntry(
        canonical_id="adjudicate_case",
        surface_names=["adjudicate_case"],
        actor="analyst",
        purpose="HUMAN ONLY: Submit official adjudication decision for a case.",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string"}, "decision": {"type": "string"}},
            "required": ["case_id", "decision"],
        },
        output_schema={"type": "object", "properties": {"adjudicated": {"type": "boolean"}}},
        error_codes=["FORBIDDEN", "CONFLICT"],
        provenance_kind="database",
        side_effects=True,
        model_selectable=False,
    ),
    ToolCatalogEntry(
        canonical_id="trigger_simulation",
        surface_names=["trigger_simulation"],
        actor="analyst",
        purpose="HUMAN ONLY: Trigger synthetic simulation run.",
        input_schema={
            "type": "object",
            "properties": {"simulation_type": {"type": "string"}},
            "required": ["simulation_type"],
        },
        output_schema={"type": "object", "properties": {"simulation_id": {"type": "string"}}},
        error_codes=["FORBIDDEN"],
        provenance_kind="database",
        side_effects=True,
        model_selectable=False,
    ),
    ToolCatalogEntry(
        canonical_id="write_ticket_for_driver",
        surface_names=["write_ticket_for_driver"],
        actor="analyst",
        purpose="HUMAN ONLY: Issue formal penalty ticket to driver.",
        input_schema={
            "type": "object",
            "properties": {"driver_id": {"type": "string"}, "violation": {"type": "string"}},
            "required": ["driver_id", "violation"],
        },
        output_schema={"type": "object", "properties": {"ticket_id": {"type": "string"}}},
        error_codes=["FORBIDDEN"],
        provenance_kind="database",
        side_effects=True,
        model_selectable=False,
    ),
    ToolCatalogEntry(
        canonical_id="submit_driver_statement",
        surface_names=["submit_driver_statement"],
        actor="driver",
        purpose="HUMAN ONLY: Driver command to submit formal dispute statement.",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string"}, "statement": {"type": "string"}},
            "required": ["case_id", "statement"],
        },
        output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        error_codes=["FORBIDDEN", "CONFLICT"],
        provenance_kind="database",
        side_effects=True,
        model_selectable=False,
    ),
    ToolCatalogEntry(
        canonical_id="query_cases_db",
        surface_names=["query_cases_db"],
        actor="analyst",
        purpose="HUMAN ONLY: Unrestricted database queries.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        output_schema={"type": "object", "properties": {"rows": {"type": "array"}}},
        error_codes=["FORBIDDEN"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=False,
    ),
    ToolCatalogEntry(
        canonical_id="get_audit_log",
        surface_names=["get_audit_log"],
        actor="analyst",
        purpose="HUMAN ONLY: Retrieve full internal audit trail.",
        input_schema={"type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]},
        output_schema={"type": "object", "properties": {"audit_trail": {"type": "array"}}},
        error_codes=["FORBIDDEN"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=False,
    ),
]

# Geoapify case-scoped read-only tools (ref #230). Lookup and match results are
# advisory evidence; they never assert intent and never overwrite stored GPS.
CATALOG_ENTRIES.extend(
    [
        ToolCatalogEntry(
            canonical_id="geocode_address",
            surface_names=["geocode_address"],
            actor="both",
            purpose="Forward geocode an address; candidates carry confidence and distance. Lookup is not location proof.",
            input_schema={
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "Free-text address to geocode"},
                    "limit": {"type": "integer", "description": "Maximum candidates (1-10)"},
                },
                "required": ["address"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "query": {"type": "string"},
                    "results": {"type": "array"},
                    "count": {"type": "integer"},
                    "lookup_is_not_location_proof": {"const": True},
                },
                "required": ["case_id", "query", "results", "count", "lookup_is_not_location_proof"],
            },
            error_codes=["SOURCE_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE", "VALIDATION_ERROR"],
            provenance_kind="provider",
            side_effects=False,
            model_selectable=True,
            timeout_seconds=10,
        ),
        ToolCatalogEntry(
            canonical_id="reverse_geocode_coordinates",
            surface_names=["reverse_geocode_coordinates"],
            actor="both",
            purpose="Reverse geocode WGS84 coordinates; candidates carry confidence and distance. Lookup is not location proof.",
            input_schema={
                "type": "object",
                "properties": {
                    "longitude": {"type": "number", "description": "WGS84 longitude"},
                    "latitude": {"type": "number", "description": "WGS84 latitude"},
                    "limit": {"type": "integer", "description": "Maximum candidates (1-10)"},
                },
                "required": ["longitude", "latitude"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "query": {"type": "string"},
                    "results": {"type": "array"},
                    "count": {"type": "integer"},
                    "lookup_is_not_location_proof": {"const": True},
                },
                "required": ["case_id", "query", "results", "count", "lookup_is_not_location_proof"],
            },
            error_codes=["SOURCE_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE", "VALIDATION_ERROR"],
            provenance_kind="provider",
            side_effects=False,
            model_selectable=True,
            timeout_seconds=10,
        ),
        ToolCatalogEntry(
            canonical_id="match_trip_telemetry",
            surface_names=["match_trip_telemetry"],
            actor="both",
            purpose="Snap stored GPS to the road network; return counts and match distance per point. Originals are never overwritten.",
            input_schema={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "limit": {"type": "integer", "description": "Maximum points to match (2-100)"},
                },
                "required": [],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "point_count": {"type": "integer"},
                    "matched_count": {"type": "integer"},
                    "unmatched_count": {"type": "integer"},
                    "interpolated_count": {"type": "integer"},
                    "match_distance_m_by_index": {"type": "object"},
                    "originals_never_overwritten": {"const": True},
                },
                "required": [
                    "case_id",
                    "point_count",
                    "matched_count",
                    "unmatched_count",
                    "interpolated_count",
                    "match_distance_m_by_index",
                    "originals_never_overwritten",
                ],
            },
            error_codes=["SOURCE_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE", "VALIDATION_ERROR"],
            provenance_kind="provider",
            side_effects=False,
            model_selectable=True,
            timeout_seconds=10,
        ),
    ]
)

# Runtime-native read/draft seams from the approved catalog.  They remain
# model-selectable only after the same trusted context and case authorization
# checks in tool_execution.py.
for _canonical_id, _purpose in (
    ("get_trip_lifecycle_evidence", "Retrieve recorded assignment lifecycle events."),
    ("compare_trip_routes", "Compare recorded route evidence with the planned route."),
    ("check_system_error_guardrail", "Retrieve recorded platform and telemetry guardrail evidence."),
    ("get_dispute_dossier", "Retrieve the authorized dispute dossier and statements."),
    ("search_case_precedents", "Search authorized, previously decided case precedents."),
    ("get_case_map_snapshot", "Retrieve a versioned source-backed case map artifact."),
    ("draft_evidence_request", "Draft a source-linked evidence request for human review."),
    ("draft_case_minutes", "Draft minutes from an already recorded decision."),
    ("preview_case_minutes", "Preview exact minutes content and provenance before approval."),
    ("request_action_approval", "Prepare a human approval request without executing it."),
    ("ask_interactive_question", "Create a typed durable clarification question."),
    ("get_action_status", "Retrieve authorized action and delivery state."),
):
    CATALOG_ENTRIES.append(
        ToolCatalogEntry(
            canonical_id=_canonical_id,
            surface_names=[_canonical_id],
            actor="analyst"
            if _canonical_id
            in {
                "search_case_precedents",
                "preview_case_minutes",
                "draft_case_minutes",
                "draft_evidence_request",
                "request_action_approval",
            }
            else "both",
            purpose=_purpose,
            input_schema={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "question_id_stable": {"type": "string"},
                    "question_text": {"type": "string"},
                    "evidence_gap_description": {"type": "string"},
                    "allowed_submission_options": {"type": "array"},
                    "options": {"type": "array"},
                    "content": {"type": "object"},
                    "action": {"type": "string"},
                    "minutes_id": {"type": "string"},
                    "action_id": {"type": "string"},
                    "claim_type": {"type": "string"},
                    "violation_code": {"type": "string"},
                    "actor_target": {"type": "string"},
                    "question_kind": {"type": "string"},
                    "purpose": {"type": "string"},
                    "hint": {"type": "string"},
                    "max_selections": {"type": ["integer", "null"]},
                    "allows_explanation": {"type": "boolean"},
                    "recipient": {"type": "string"},
                    "rationale": {"type": "string"},
                    "decision_id": {"type": "string"},
                    "evidence_snapshot_id": {"type": "string"},
                    "match_limit": {"type": "integer", "description": "Max GPS points to map-match (2-100)"},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
            provenance_kind="composite",
            side_effects=False,
            model_selectable=True,
        )
    )


_DRIVER_CATALOG_DEFS: list[ToolCatalogEntry] = [
    ToolCatalogEntry(
        canonical_id="list_my_cases",
        surface_names=["list_my_cases"],
        actor="driver",
        purpose="List dispute cases for authenticated driver.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by case status"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="get_case_timeline",
        surface_names=["get_case_timeline"],
        actor="driver",
        purpose="Retrieve dispute status history and response deadline.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="explain_case_status",
        surface_names=["explain_case_status"],
        actor="driver",
        purpose="Provide plain-language explanation of case status.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
                "locale": {"type": "string", "description": "Locale code, e.g. vi or en", "default": "vi"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="get_my_scorecard",
        surface_names=["get_my_scorecard"],
        actor="driver",
        purpose="Retrieve 90-day driver scorecard and metrics.",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="list_my_trips",
        surface_names=["list_my_trips"],
        actor="driver",
        purpose="Retrieve trip history and ratings for authenticated driver.",
        input_schema={
            "type": "object",
            "properties": {
                "cursor": {"type": "string", "description": "Opaque pagination cursor"},
                "limit": {"type": "integer", "description": "Number of trips (1..50)", "default": 20},
                "status": {"type": "string", "description": "Filter by trip status"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="get_trip_summary",
        surface_names=["get_trip_summary"],
        actor="driver",
        purpose="Retrieve details and ratings of a specific trip.",
        input_schema={
            "type": "object",
            "properties": {
                "trip_id": {"type": "string", "description": "Trip identifier"},
            },
            "required": ["trip_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="get_forensic_brief",
        surface_names=["get_forensic_brief"],
        actor="both",
        purpose="Retrieve observed abnormalities without judgment or verdict.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="suggest_dispute_path",
        surface_names=["suggest_dispute_path"],
        actor="driver",
        purpose="Provide advisory dispute guidance from evidence.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="assess_statement_completeness",
        surface_names=["assess_statement_completeness"],
        actor="driver",
        purpose="Assess completeness of driver dispute statement via checklist.",
        input_schema={
            "type": "object",
            "properties": {
                "incident_type": {
                    "type": "string",
                    "description": "Incident type: traffic, gps, weather, passenger, other",
                },
                "description": {"type": "string", "description": "Concrete dispute description"},
                "corroborations": {"type": "array", "description": "List of corroborating evidence strings or objects"},
                "no_evidence_declared": {
                    "type": "boolean",
                    "description": "Whether driver explicitly declares no evidence available",
                },
            },
            "required": ["incident_type", "description"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="composite",
        side_effects=False,
        model_selectable=True,
    ),
    ToolCatalogEntry(
        canonical_id="get_appeal_options",
        surface_names=["get_appeal_options"],
        actor="driver",
        purpose="Retrieve available appeal options and next steps.",
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case identifier"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        error_codes=["FORBIDDEN", "NOT_FOUND", "SOURCE_UNAVAILABLE", "VALIDATION_ERROR"],
        provenance_kind="database",
        side_effects=False,
        model_selectable=True,
    ),
]
CATALOG_ENTRIES.extend(_DRIVER_CATALOG_DEFS)


def get_tool_catalog() -> list[ToolCatalogEntry]:
    """Return all catalog entries."""
    return CATALOG_ENTRIES


def model_tool_names(actor: str) -> set[str]:
    """Return model-selectable surface names for a given actor."""
    selectable: set[str] = set()
    for entry in CATALOG_ENTRIES:
        if not entry.model_selectable:
            continue
        if entry.actor in (actor, "both"):
            selectable.update(entry.surface_names)
    return selectable


def model_input_schemas(actor: str | None = None) -> list[dict[str, Any]]:
    """Return input schemas for model-selectable tools."""
    schemas = []
    for entry in CATALOG_ENTRIES:
        if not entry.model_selectable:
            continue
        if actor is None or entry.actor in (actor, "both"):
            schema_copy = dict(entry.input_schema)
            schema_copy["properties"] = {
                key: value
                for key, value in schema_copy.get("properties", {}).items()
                if key
                not in {
                    "actor_id",
                    "organization_id",
                    "roles",
                    "permissions",
                    "runtime_context",
                    "case_id",
                    "driver_id",
                }
            }
            schema_copy["required"] = [
                key for key in schema_copy.get("required", []) if key not in {"case_id", "driver_id"}
            ]
            schema_copy["additionalProperties"] = False
            schema_copy["title"] = entry.canonical_id
            schemas.append(schema_copy)
    return schemas


async def lookup_case_detail_typed(
    case_id: str,
    context: ToolExecutionContext | None = None,
) -> ToolResult:
    """Typed canonical case lookup returning validated ToolResult with real database provenance.

    Refs #60, #85 (T1).
    """
    import datetime

    from fastapi import HTTPException

    from src.models.tool_contracts import EvidenceProvenance, ToolError, ToolResult
    from src.services.case_service import get_case_service

    service = get_case_service()
    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    tool_call_id = context.tool_call_id if context else f"call_{case_id}"

    try:
        org_id = context.organization_id if context else None
        res = await service.get_case_detail(case_id=case_id, organization_id=org_id)
        data = res.model_dump(mode="json")
        rec_id = getattr(res, "id", None) or getattr(getattr(res, "case", None), "id", case_id)
        provenance = [
            EvidenceProvenance(
                kind="database",
                source="app.fraud_cases",
                record_ids=[str(rec_id or case_id)],
                retrieved_at=now_iso,
            )
        ]
        return ToolResult(
            status="succeeded",
            tool_id="get_case_context",
            tool_call_id=tool_call_id,
            data=data,
            provenance=provenance,
        )
    except HTTPException as e:
        error_code: Literal["NOT_FOUND", "FORBIDDEN", "INTERNAL_ERROR"] = (
            "NOT_FOUND" if e.status_code == 404 else ("FORBIDDEN" if e.status_code == 403 else "INTERNAL_ERROR")
        )
        return ToolResult(
            status="failed",
            tool_id="get_case_context",
            tool_call_id=tool_call_id,
            error=ToolError(
                code=error_code,
                message=str(e.detail),
                retryable=False,
            ),
            provenance=[
                EvidenceProvenance(
                    kind="unavailable",
                    source="app.fraud_cases",
                    retrieved_at=now_iso,
                )
            ],
        )
    except Exception as e:
        return ToolResult(
            status="failed",
            tool_id="get_case_context",
            tool_call_id=tool_call_id,
            error=ToolError(
                code="PERSISTENCE_UNAVAILABLE",
                message=str(e),
                retryable=True,
            ),
            provenance=[
                EvidenceProvenance(
                    kind="unavailable",
                    source="app.fraud_cases",
                    retrieved_at=now_iso,
                )
            ],
        )


# Schemas for actual canonical domain results and safe proposal arguments.
# Legacy aliases remain documented above; authority is injected by the server.
def _traffic_history_output_schema() -> dict[str, Any]:
    available = {
        "type": "object",
        "properties": {
            "status": {"const": "available"},
            "source_type": {"const": "first_party_peer_telemetry"},
            "peer_count": {"type": "integer", "minimum": 3},
            "observed_speed_kmh": {"type": "number", "minimum": 0},
            "free_flow_speed_kmh": {"type": "number", "exclusiveMinimum": 0},
            "congestion_ratio": {"type": "number", "minimum": 0, "maximum": 1},
            "congested": {"type": "boolean"},
            "window_start": {"type": "string"},
            "window_end": {"type": "string"},
            "method": {"const": "median_peer_trip_speed_vs_p85_peer_baseline"},
        },
        "required": [
            "status",
            "source_type",
            "peer_count",
            "observed_speed_kmh",
            "free_flow_speed_kmh",
            "congestion_ratio",
            "congested",
            "window_start",
            "window_end",
            "method",
        ],
        "additionalProperties": False,
    }
    unavailable = {
        "type": "object",
        "properties": {"status": {"enum": ["unavailable", "validation_error"]}, "reason": {"type": "string"}},
        "required": ["status", "reason"],
        "additionalProperties": False,
    }
    return {"oneOf": [available, unavailable]}


def _traffic_incidents_output_schema() -> dict[str, Any]:
    incident = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string"},
            "severity": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
            "start_time": {"type": "string"},
            "end_time": {"type": "string"},
            "updated_at": {"type": "string"},
        },
        "additionalProperties": False,
    }
    available = {
        "type": "object",
        "properties": {
            "status": {"const": "available"},
            "incidents": {"type": "array", "items": incident},
            "congested": {"type": "boolean"},
            "observed_at": {"type": "string"},
            "historical_absence_proven": {"const": False},
            "retention": {"const": "memory_only"},
        },
        "required": [
            "status",
            "incidents",
            "congested",
            "observed_at",
            "historical_absence_proven",
            "retention",
        ],
        "additionalProperties": False,
    }
    unavailable = {
        "type": "object",
        "properties": {
            "status": {"const": "unavailable"},
            "reason": {"type": "string"},
            "historical_absence_proven": {"const": False},
            "retention": {"const": "memory_only"},
        },
        "required": ["status", "reason", "historical_absence_proven", "retention"],
        "additionalProperties": False,
    }
    validation_error = {
        "type": "object",
        "properties": {"status": {"const": "validation_error"}, "reason": {"type": "string"}},
        "required": ["status", "reason"],
        "additionalProperties": False,
    }
    return {"oneOf": [available, unavailable, validation_error]}


def _synchronize_canonical_contracts():
    from src.models import workflow_models as wm

    pairs = {
        "ask_interactive_question": (wm.AskInteractiveQuestionArguments, wm.AskInteractiveQuestionResult),
        "draft_evidence_request": (wm.DraftEvidenceRequestArguments, wm.DraftEvidenceRequestResult),
        "draft_case_minutes": (wm.DraftCaseMinutesArguments, wm.DraftCaseMinutesResult),
        "preview_case_minutes": (wm.PreviewCaseMinutesArguments, wm.PreviewCaseMinutesResult),
        "request_action_approval": (wm.RequestActionApprovalArguments, wm.RequestActionApprovalResult),
        "get_action_status": (wm.GetActionStatusArguments, wm.GetActionStatusResult),
    }
    objects = {"type": "object"}
    arrays = {"type": "array", "items": objects}
    string = {"type": "string"}
    nullable_object = {"anyOf": [objects, {"type": "null"}]}
    fields = {
        "get_case_context": {
            "schema_version": string,
            "case_id": string,
            "evidence": objects,
            "evidence_status": string,
            "evidence_snapshot": objects,
            "prepared_at": string,
            "frozen": {"type": "boolean"},
            "source": string,
        },
        "list_cases": {"cases": arrays, "count": {"type": "integer", "minimum": 0}},
        "inspect_trip_telemetry": {"case_id": string, "points": arrays, "summary": objects},
        "get_trip_lifecycle_evidence": {"case_id": string, "events": arrays, "summary": objects},
        "get_driver_history": {"case_id": string, "driver": objects},
        "check_related_cases_to_vehicle": {"case_id": string, "cases": arrays},
        "check_traffic_situation": {"case_id": string, "observations": arrays},
        "check_weather_condition": {
            "case_id": string,
            "observation_date": string,
            "hourly": objects,
            "units": objects,
            "source_type": {"const": "historical_reanalysis"},
        },
        "search_policy_documents": {
            "case_id": string,
            "query": string,
            "results": arrays,
            "citations": arrays,
            "status": {"enum": ["succeeded", "uncertain"]},
            "abstention": string,
        },
        "compare_trip_routes": {
            "case_id": string,
            "route_geometry": nullable_object,
            "planned_segments": arrays,
            "observed": arrays,
            "progress_metrics": nullable_object,
            "missingness": arrays,
            "match_summary": nullable_object,
        },
        "check_system_error_guardrail": {"case_id": string, "guardrails": nullable_object, "missingness": arrays},
        "verify_exoneration_rules": {
            "case_id": string,
            "advisory_only": {"const": True},
            "action": {"const": "REQUIRES_ANALYST_REVIEW"},
            "guardrails": nullable_object,
        },
        "get_case_map_snapshot": {
            "case_id": string,
            "evidence_snapshot_id": string,
            "snapshot_version": {"type": "integer"},
            "snapshot_hash": string,
            "route_refs": arrays,
            "checkpoint_times": arrays,
            "gap_windows": arrays,
            "traveled_path": arrays,
            "planned_routes": arrays,
            "provider": string,
            "style": string,
            "rendered_at": string,
            "image_ref": {"anyOf": [string, {"type": "null"}]},
            "attribution": string,
            "cost_credits": {"type": "integer"},
            "unavailable": nullable_object,
            "deterministic_key": string,
        },
        "geocode_address": {
            "case_id": string,
            "query": string,
            "results": arrays,
            "count": {"type": "integer"},
            "lookup_is_not_location_proof": {"const": True},
        },
        "reverse_geocode_coordinates": {
            "case_id": string,
            "query": string,
            "results": arrays,
            "count": {"type": "integer"},
            "lookup_is_not_location_proof": {"const": True},
        },
        "match_trip_telemetry": {
            "case_id": string,
            "point_count": {"type": "integer"},
            "matched_count": {"type": "integer"},
            "unmatched_count": {"type": "integer"},
            "interpolated_count": {"type": "integer"},
            "match_distance_m_by_index": objects,
            "originals_never_overwritten": {"const": True},
        },
        "get_dispute_dossier": {"case_id": string, "statements": arrays},
        "search_case_precedents": {
            "case_id": string,
            "precedents": arrays,
            "role": {"const": "historical_decisions_only"},
        },
    }
    for tool_id in ("inspect_trip_telemetry", "get_trip_lifecycle_evidence"):
        fields[tool_id].update(
            {
                "total_samples": {"type": "integer", "minimum": 0},
                "sampled_from_samples": {"type": "integer", "minimum": 0},
                "returned_samples": {"type": "integer", "minimum": 0},
                "truncated": {"type": "boolean"},
                "sampling": string,
            }
        )
    for entry in CATALOG_ENTRIES:
        if entry.canonical_id in pairs:
            input_model, output_model = pairs[entry.canonical_id]
            entry.input_schema = input_model.model_json_schema()
            entry.output_schema = output_model.model_json_schema()
        elif entry.canonical_id == "fetch_corridor_historical_traffic":
            entry.output_schema = _traffic_history_output_schema()
        elif entry.canonical_id == "query_traffic_incident_feed":
            entry.output_schema = _traffic_incidents_output_schema()
        elif entry.canonical_id in fields:
            if entry.canonical_id in {
                "check_weather_condition",
                "check_traffic_situation",
                "search_policy_documents",
            }:
                # Dual-shape dispatch (driver general-FAQ lookup vs analyst
                # case-scoped evidence-bound lookup in tool_execution.py) —
                # same precedent as check_weather_condition/check_traffic_situation.
                entry.output_schema = {"type": "object"}
            else:
                entry.output_schema = {
                    "type": "object",
                    "properties": fields[entry.canonical_id],
                    "required": list(fields[entry.canonical_id]),
                    "additionalProperties": False,
                }
        entry.input_schema["additionalProperties"] = False
        if entry.canonical_id == "list_cases":
            entry.input_schema["properties"]["limit"].update(minimum=1, maximum=100)
        if entry.canonical_id in {"check_related_cases_to_vehicle", "get_driver_history"}:
            entry.input_schema = {
                "type": "object",
                "properties": {"driver_id": {"type": "string"}} if entry.canonical_id == "get_driver_history" else {},
                "additionalProperties": False,
            }
        if entry.canonical_id == "check_weather_condition":
            entry.input_schema = {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "trip_id": {"type": "string"},
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "time_iso": {"type": "string"},
                },
                "additionalProperties": False,
            }
        if entry.canonical_id == "check_traffic_situation":
            entry.input_schema = {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "trip_id": {"type": "string"},
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                    "start_lat": {"type": "number"},
                    "start_lon": {"type": "number"},
                    "end_lat": {"type": "number"},
                    "end_lon": {"type": "number"},
                },
                "additionalProperties": False,
            }
        if entry.canonical_id == "draft_case_minutes":
            # Decision and map authority come from the recorded decision source.
            entry.input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
        entry.timeout_seconds = 10
        entry.max_retries = 1 if entry.canonical_id not in pairs else 0


_synchronize_canonical_contracts()
