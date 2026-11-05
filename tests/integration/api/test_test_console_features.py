"""Console feature contract: cancellation evidence, history, title, overview, presets.

These tests exercise the isolated in-memory simulation backend through the public
``/test/api/v1`` routes. They assert trusted-caller tenancy, canonical
cancellation evidence, and that recorded pipeline evidence is never fabricated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.driver_directory import DriverRecord, get_driver_directory

ORG_A = "018f2f4e-0000-7000-8000-000000000001"
ORG_B = "018f2f4e-0000-7000-8000-00000000000b"
DRIVER_A_ID = "018f2f4e-3000-7000-8000-000000000011"
DRIVER_B_ID = "018f2f4e-3000-7000-8000-0000000000b1"


@pytest.fixture(autouse=True)
def setup_drivers():
    driver_dir = get_driver_directory()
    driver_dir.register_driver(
        DriverRecord(
            driver_id=UUID(DRIVER_A_ID),
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-2000-7000-8000-000000000011"),
            external_subject="user_real_org_a",
            display_name="Nguyen Viet",
            email="driver.a@example.com",
            account_status="active",
        )
    )
    driver_dir.register_driver(
        DriverRecord(
            driver_id=UUID(DRIVER_B_ID),
            organization_id=ORG_B,
            principal_id=UUID("018f2f4e-2000-7000-8000-0000000000b1"),
            external_subject="user_real_org_b",
            display_name="Tran Van B",
            email="driver.b@example.com",
            account_status="active",
        )
    )


def _client(org: str = ORG_A, principal: str = "tester-1") -> TestClient:
    return TestClient(
        app,
        headers={
            "X-Test-Context": "true",
            "X-Role": "demo_operator",
            "X-Principal-Id": principal,
            "X-Organization-Id": org,
        },
    )


def _make_run(client: TestClient, *, name: str = "Console Run", title: str | None = None) -> str:
    org_id = client.headers.get("X-Organization-Id")
    driver_id = DRIVER_B_ID if org_id == ORG_B else DRIVER_A_ID
    plan = client.post("/test/api/v1/plans", json={"name": name}).json()
    definition = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan["id"],
            "route_geometry": {
                "type": "LineString",
                "coordinates": [[105.8524, 21.0285], [105.8342, 21.0450]],
            },
            "initial_snapshot": {"location": {"latitude": 21.0200, "longitude": 105.8600}, "address": "Origin"},
            "pickup_snapshot": {"location": {"latitude": 21.0285, "longitude": 105.8524}, "address": "Pickup"},
            "destination_snapshot": {
                "location": {"latitude": 21.0450, "longitude": 105.8342},
                "address": "Destination",
            },
            "driver_config": {"speed_mps": 12.0, "update_cadence_s": 1.0, "driver_id": driver_id},
            "fault_configs": [],
            "messages": [],
        },
    ).json()
    body: dict[str, object] = {"definition_revision_id": definition["id"], "speed_factor": 1.0}
    if title is not None:
        body["title"] = title
    run = client.post("/test/api/v1/runs", json=body).json()
    return run["id"]


def test_run_gets_default_title_and_is_listed_in_history():
    client = _client()
    run_id = _make_run(client, name="History Plan")

    listed = client.get("/test/api/v1/runs")
    assert listed.status_code == 200
    rows = listed.json()
    match = [r for r in rows if r["id"] == run_id]
    assert len(match) == 1
    assert match[0]["title"]  # default generated name is present
    assert match[0]["status"] in {"QUEUED", "RUNNING", "PAUSED", "COMPLETED", "CANCELLED", "FAILED"}


def test_history_is_scoped_to_the_owning_organization():
    owner = _client(ORG_A, "owner-a")
    run_id = _make_run(owner, name="Tenant A plan")

    foreign = _client(ORG_B, "owner-b")
    rows = foreign.get("/test/api/v1/runs").json()
    assert all(r["id"] != run_id for r in rows)


def test_run_title_is_editable_and_persisted():
    client = _client()
    run_id = _make_run(client)
    from src.services.test_simulation_runner import get_simulation_runner

    get_simulation_runner().repository.update_run_status(UUID(run_id), "RUNNING")

    updated = client.patch(f"/test/api/v1/runs/{run_id}", json={"title": "Wrong-way Hanoi night shift"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Wrong-way Hanoi night shift"

    relisted = [r for r in client.get("/test/api/v1/runs").json() if r["id"] == run_id]
    assert relisted[0]["title"] == "Wrong-way Hanoi night shift"


def test_title_update_rejects_blank_and_foreign_runs():
    client = _client()
    run_id = _make_run(client)
    from src.services.test_simulation_runner import get_simulation_runner

    get_simulation_runner().repository.update_run_status(UUID(run_id), "RUNNING")
    blank = client.patch(f"/test/api/v1/runs/{run_id}", json={"title": "   "})
    assert blank.status_code == 422

    foreign = _client(ORG_B, "owner-b")
    assert foreign.patch(f"/test/api/v1/runs/{run_id}", json={"title": "hijack"}).status_code == 404


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"actor": "passenger", "reason": "Customer changed plan"}, 200),
        ({"actor": "driver", "reason": "Driver could not reach pickup"}, 200),
    ],
)
def test_participant_cancellation_records_canonical_evidence(payload, expected):
    client = _client()
    run_id = _make_run(client)
    from src.services.test_simulation_runner import get_simulation_runner

    get_simulation_runner().repository.update_run_status(UUID(run_id), "RUNNING")

    response = client.post(f"/test/api/v1/runs/{run_id}/controls", json={"command": "CANCEL", "payload": payload})
    assert response.status_code == expected

    run = client.get(f"/test/api/v1/runs/{run_id}").json()
    assert run["status"] == "CANCELLED"
    assert run["cancellation_actor"] == payload["actor"]
    assert run["cancellation_reason"] == payload["reason"]
    assert run["cancelled_at"]


def test_cancellation_requires_actor_and_non_blank_reason():
    client = _client()
    run_id = _make_run(client)
    from src.services.test_simulation_runner import get_simulation_runner

    get_simulation_runner().repository.update_run_status(UUID(run_id), "RUNNING")

    blank_reason = client.post(
        f"/test/api/v1/runs/{run_id}/controls",
        json={"command": "CANCEL", "payload": {"actor": "passenger", "reason": "   "}},
    )
    assert blank_reason.status_code == 422

    bad_actor = client.post(
        f"/test/api/v1/runs/{run_id}/controls",
        json={"command": "CANCEL", "payload": {"actor": "robot", "reason": "because"}},
    )
    assert bad_actor.status_code == 422

    # The rejected requests must not have recorded participant cancellation evidence.
    run = client.get(f"/test/api/v1/runs/{run_id}").json()
    assert run["cancellation_actor"] is None
    assert run["cancellation_reason"] is None


def test_platform_cancel_without_payload_remains_supported():
    client = _client()
    run_id = _make_run(client)
    from src.services.test_simulation_runner import get_simulation_runner

    get_simulation_runner().repository.update_run_status(UUID(run_id), "RUNNING")
    response = client.post(f"/test/api/v1/runs/{run_id}/controls", json={"command": "CANCEL"})
    assert response.status_code == 200
    assert client.get(f"/test/api/v1/runs/{run_id}").json()["status"] == "CANCELLED"


def test_overview_reports_recorded_pipeline_evidence_only(monkeypatch):
    from unittest.mock import AsyncMock

    from src.services.test_simulation_runner import get_simulation_runner

    # Keep the run queued so the empty-input assertion cannot race a real tick.
    monkeypatch.setattr(get_simulation_runner(), "start_run", AsyncMock())
    client = _client()
    run_id = _make_run(client, name="Overview Plan")

    empty = client.get(f"/test/api/v1/runs/{run_id}/overview").json()
    assert empty["trips_input"] == 0
    assert empty["trips_classified"] == 0
    assert empty["classification_counts"] == {}
    assert [s["key"] for s in empty["stages"]] == ["input", "models", "classified"]

    from src.models.test_simulation import TestTelemetrySample
    from src.services.test_simulation_runner import get_simulation_runner

    repository = get_simulation_runner().repository
    repository.save_sample(
        TestTelemetrySample(
            run_id=run_id,
            step_index=0,
            latitude=21.0285,
            longitude=105.8524,
            speed_mps=12.0,
            heading_deg=90.0,
            emitted_at=datetime.now(UTC),
            is_fault_injected=True,
            fault_type="JUMP",
        )
    )
    repository.update_run_status(UUID(run_id), "COMPLETED")

    saved = client.post(f"/test/api/v1/runs/{run_id}/save-case")
    assert saved.status_code == 201, saved.text
    overview = client.get(f"/test/api/v1/runs/{run_id}/overview").json()
    assert overview["trips_processed"] >= 1
    assert overview["trips_classified"] == 1
    assert overview["classification_counts"].get("ERR-05") == 1


def test_presets_expose_published_library_with_truthful_availability():
    client = _client()
    response = client.get("/test/api/v1/presets")
    assert response.status_code == 200
    body = response.json()

    presets = {p["id"]: p for p in body["presets"]}
    assert set(presets) == {"default", "all-normal", "wrong-direction", "synthesized-vietnam"}
    assert presets["default"]["title"] == "Default"
    assert presets["all-normal"]["title"] == "All normal trips"
    assert presets["wrong-direction"]["title"] == "Driver going wrong direction"
    assert presets["synthesized-vietnam"]["title"] == "Vietnam trips (synthesized)"
    assert presets["synthesized-vietnam"]["available"] is True
    assert presets["synthesized-vietnam"]["kind"] == "vietnam"

    assert presets["all-normal"]["available"] is True
    assert presets["all-normal"]["source_label"] == "no_violation"
    assert all(t["label"] == "no_violation" for t in presets["all-normal"]["sample_trips"])

    # Wrong-direction detection is not verified yet; it must not look selectable.
    assert presets["wrong-direction"]["available"] is False
    assert presets["wrong-direction"]["unavailable_reason"]

    assert body["source"]["revision"] == "914a36560727f5892a24fba3a4173cb245c963da"


def test_presets_require_an_organization():
    anonymous = TestClient(app, headers={"X-Test-Context": "true"})
    assert anonymous.get("/test/api/v1/presets").status_code == 401
