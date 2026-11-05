"""Category alignment and retained history through the staged HTTP contract."""

import pytest

from src.services.case_service import get_case_service
from tests.integration.api.test_staged_adjudication import (
    ANALYST_ID,
    BASE,
    JUDGMENTS,
    claim,
    commit,
)
from tests.integration.api.test_staged_adjudication import (
    staged_client as staged_client,
)


@pytest.mark.parametrize(
    "category,judgment",
    [
        *((f"ERR-0{i}", JUDGMENTS[0]) for i in range(1, 6)),
        ("intentional_dic", JUDGMENTS[0]),
        ("no_violation", JUDGMENTS[1]),
        ("exonerated", JUDGMENTS[1]),
        ("force_majeure", JUDGMENTS[1]),
        ("insufficient_evidence", JUDGMENTS[2]),
    ],
)
async def test_category_alignment_matches_independent_judgment_and_history(staged_client, category, judgment):
    client, _ = staged_client
    # Prepare the assessment source; assertions use only HTTP outputs.
    service = client._transport.app.dependency_overrides[get_case_service]()
    service._model_assessments["assessment-236"]["category"] = category
    await claim(client)
    record = await commit(client, judgment)
    detail = (await client.get(BASE)).json()
    result = await client.post(
        f"{BASE}/adjudicate",
        json={
            "analyst_id": ANALYST_ID,
            "outcome": "DISAGREE",
            "rationale": "1234567890",
            "expected_case_version": detail["case"]["version"],
            "preliminary_judgment_id": record["id"],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["delta"] == "match"
    history = (await client.get("/api/v1/cases/history")).json()["items"][0]
    assert history["preliminary_judgment"]["id"] == record["id"]
    assert history["ai_suggestion"]["category"] == category
    assert history["delta"] == "match"


async def test_slash_judgment_normalizes_and_saved_decision_cannot_be_replaced(staged_client):
    client, _ = staged_client
    await claim(client)
    record = await commit(client, "Nghi oan/bất khả kháng")
    assert record["judgment"] == JUDGMENTS[1]
    detail = (await client.get(BASE)).json()
    payload = {
        "analyst_id": ANALYST_ID,
        "outcome": "DISAGREE",
        "rationale": "1234567890",
        "expected_case_version": detail["case"]["version"],
        "preliminary_judgment_id": record["id"],
    }
    first = await client.post(f"{BASE}/adjudicate", json=payload)
    assert first.status_code == 200, first.text
    payload.update(outcome="AGREE", expected_case_version=first.json()["new_version"])
    retry = await client.post(f"{BASE}/adjudicate", json=payload)
    assert retry.status_code == 409
    saved = (await client.get(BASE)).json()["adjudication"]
    assert saved["outcome"] == "DISAGREE"
