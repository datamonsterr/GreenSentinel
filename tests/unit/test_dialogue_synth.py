from __future__ import annotations

import random

import pytest
import yaml

from scripts.benchmark.dialogue_synth import (
    CONTEXTS,
    FRAUD_CONTEXTS,
    MAX_TURNS,
    MIN_TURNS,
    synthesize_customer_report,
    synthesize_dialogue,
    synthesize_objection_reason,
)
from tests.support.repo import REPO_ROOT

BANK_DIR = REPO_ROOT / "data" / "conversation_bank"
FACTS = {"wait_s": 420, "distance_m": 3500, "pickup_name": "Sảnh A", "dest_name": "Sân bay"}

ERR01_TRIGGERS = ("vô cớ", "từ chối", "unjustified")
ERR04_TRIGGERS = ("ảo", "ghost")


def _bank(context: str) -> dict:
    with open(BANK_DIR / f"{context}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _paraphrases(context: str) -> list[str]:
    bank = _bank(context)
    return [e["text"] for role in ("driver", "customer") for e in bank[role] if e.get("trap") == "paraphrase"]


def _keywords(context: str) -> list[str]:
    bank = _bank(context)
    return [e["text"] for role in ("driver", "customer") for e in bank[role] if e.get("trap") == "keyword"]


@pytest.mark.parametrize("context", CONTEXTS)
def test_bank_coverage_per_role(context: str) -> None:
    bank = _bank(context)
    for role in ("driver", "customer"):
        texts = [e["text"] for e in bank[role]]
        assert len(texts) >= 20, f"{context}/{role}: {len(texts)} variants"
        assert len(set(texts)) >= 20, f"{context}/{role}: variants not distinct"


def test_determinism_same_seed() -> None:
    first = (synthesize_dialogue(random.Random(7), "err02_stall", FACTS),)
    second = (synthesize_dialogue(random.Random(7), "err02_stall", FACTS),)
    assert first == second
    assert synthesize_objection_reason(
        random.Random(7), "err01_unjustified_cancel", FACTS
    ) == synthesize_objection_reason(random.Random(7), "err01_unjustified_cancel", FACTS)
    assert synthesize_customer_report(random.Random(7), "err04_phantom", FACTS) == synthesize_customer_report(
        random.Random(7), "err04_phantom", FACTS
    )


@pytest.mark.parametrize("context", CONTEXTS)
def test_dialogue_shape(context: str) -> None:
    turns = synthesize_dialogue(random.Random(42), context, FACTS)
    assert MIN_TURNS <= len(turns) <= MAX_TURNS
    offsets = [t["sent_at_offset_s"] for t in turns]
    assert offsets == sorted(offsets) and len(set(offsets)) == len(offsets)
    for turn in turns:
        assert set(turn) == {"role", "text", "sent_at_offset_s", "lang"}
        assert turn["role"] in ("driver", "customer")
        assert turn["lang"] in ("vi", "en")
        assert turn["text"] and "{" not in turn["text"] and "}" not in turn["text"]
    roles = [t["role"] for t in turns]
    assert all(a != b for a, b in zip(roles, roles[1:]))
    assert set(roles) == {"driver", "customer"}


def test_brittleness_err01_paraphrases_avoid_triggers() -> None:
    par = _paraphrases("err01_unjustified_cancel")
    assert len(par) >= 5
    for text in par:
        assert all(k not in text.lower() for k in ERR01_TRIGGERS), text
    kw = _keywords("err01_unjustified_cancel")
    assert len(kw) >= 5
    assert all(any(k in t.lower() for k in ERR01_TRIGGERS) for t in kw)


def test_brittleness_err04_paraphrases_avoid_triggers() -> None:
    par = _paraphrases("err04_phantom")
    assert len(par) >= 5
    for text in par:
        assert all(k not in text.lower() for k in ERR04_TRIGGERS), text
    kw = _keywords("err04_phantom")
    assert len(kw) >= 5
    assert all(any(k in t.lower() for k in ERR04_TRIGGERS) for t in kw)


def test_objection_no_report_rate_on_fraud() -> None:
    n = 600
    hits = sum(
        1
        for i in range(n)
        if synthesize_objection_reason(random.Random(i), "err02_stall", FACTS)["status"] == "no_report"
    )
    assert 0.15 <= hits / n <= 0.45, hits / n


def test_objection_honest_never_no_report() -> None:
    for context in set(CONTEXTS) - FRAUD_CONTEXTS:
        for i in range(50):
            res = synthesize_objection_reason(random.Random(i), context, FACTS)
            assert res["status"] in ("present", "late")
            assert res["text"]


def test_customer_report_none_rate() -> None:
    n = 600
    nones = sum(1 for i in range(n) if synthesize_customer_report(random.Random(i), "err03_deviation", FACTS) is None)
    assert 0.25 <= nones / n <= 0.55, nones / n


def test_unknown_context_raises() -> None:
    with pytest.raises(ValueError):
        synthesize_dialogue(random.Random(0), "nope", FACTS)
    with pytest.raises(ValueError):
        synthesize_objection_reason(random.Random(0), "nope", FACTS)
    with pytest.raises(ValueError):
        synthesize_customer_report(random.Random(0), "nope", FACTS)


def test_empty_trip_facts_ok() -> None:
    turns = synthesize_dialogue(random.Random(1), "normal_trip", {})
    assert MIN_TURNS <= len(turns) <= MAX_TURNS
    assert synthesize_dialogue(random.Random(1), "normal_trip", None) == turns


def test_dialogue_mode_empty() -> None:
    for context in CONTEXTS:
        assert synthesize_dialogue(random.Random(3), context, FACTS, mode="empty") == []


def test_dialogue_mode_customer_only_no_driver_turns() -> None:
    for context in CONTEXTS:
        turns = synthesize_dialogue(random.Random(11), context, FACTS, mode="customer_only")
        assert 2 <= len(turns) <= 6
        assert all(t["role"] == "customer" for t in turns)
        offsets = [t["sent_at_offset_s"] for t in turns]
        assert offsets == sorted(offsets) and len(set(offsets)) == len(offsets)
        for turn in turns:
            assert set(turn) == {"role", "text", "sent_at_offset_s", "lang"}
            assert turn["text"] and "{" not in turn["text"] and "}" not in turn["text"]


def test_dialogue_mode_determinism() -> None:
    for mode in ("full", "empty", "customer_only"):
        first = synthesize_dialogue(random.Random(9), "err02_stall", FACTS, mode=mode)
        second = synthesize_dialogue(random.Random(9), "err02_stall", FACTS, mode=mode)
        assert first == second


def test_dialogue_mode_unknown_raises() -> None:
    with pytest.raises(ValueError):
        synthesize_dialogue(random.Random(0), "normal_trip", FACTS, mode="nope")
    with pytest.raises(ValueError):
        synthesize_dialogue(random.Random(0), "nope", FACTS, mode="customer_only")
