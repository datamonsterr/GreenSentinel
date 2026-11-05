"""Contract-level checks for the external traffic review guidance."""

from pathlib import Path

from src.agents.driver_agent import GSUPPORT_SYSTEM_PROMPT
from src.rag.cockpit_agent import _cockpit_declarations
from src.services.tool_catalog import CATALOG_ENTRIES, COCKPIT_SURFACE_NAMES, DRIVER_SURFACE_NAMES


def test_force_majeure_guidance_requires_grounded_dual_traffic_evidence() -> None:
    prompt = Path("src/agents/prompts/fraud_analyst_system_prompt.md").read_text(encoding="utf-8")
    combined = f"{prompt}\n{GSUPPORT_SYSTEM_PROMPT}"

    assert "fetch_corridor_historical_traffic" in combined
    assert "query_traffic_incident_feed" in combined
    assert "never invent" in combined.lower()
    assert "human analyst" in combined.lower()
    assert "empty incident list" in combined.lower()
    assert "cannot verify incidents" in combined.lower()


def test_canonical_traffic_tools_are_exposed_to_cockpit_and_driver_surfaces() -> None:
    names = {entry.canonical_id for entry in CATALOG_ENTRIES}
    for name in ("fetch_corridor_historical_traffic", "query_traffic_incident_feed"):
        assert name in names
        assert name in COCKPIT_SURFACE_NAMES
        assert name in DRIVER_SURFACE_NAMES

    declarations = {declaration.name: declaration for declaration in _cockpit_declarations()}
    for name in ("fetch_corridor_historical_traffic", "query_traffic_incident_feed"):
        schema = declarations[name].parameters
        assert schema.required == ["bbox", "start_time", "end_time"]
        assert schema.properties["bbox"].items.type.name == "NUMBER"
        assert "free_flow_speed_kmh" not in schema.properties

    catalog = {entry.canonical_id: entry for entry in CATALOG_ENTRIES}
    history = catalog["fetch_corridor_historical_traffic"].output_schema["oneOf"][0]
    incidents = catalog["query_traffic_incident_feed"].output_schema["oneOf"][0]
    assert history["additionalProperties"] is False
    assert history["properties"]["source_type"]["const"] == "first_party_peer_telemetry"
    assert history["properties"]["peer_count"]["minimum"] == 3
    assert incidents["additionalProperties"] is False
    assert incidents["properties"]["retention"]["const"] == "memory_only"
    assert incidents["properties"]["historical_absence_proven"]["const"] is False
