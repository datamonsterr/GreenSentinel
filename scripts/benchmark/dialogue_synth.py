"""Deterministic dialogue synthesis for the Jev benchmark dataset (Issue #252)."""

from __future__ import annotations

import random
from functools import cache
from pathlib import Path
from typing import Any

import yaml

BANK_DIR = Path(__file__).resolve().parents[2] / "data" / "conversation_bank"

# Held-out template partition (Issue #281): index-band 70/15/15 partition of a
# bank's entries so train/validation/test share no dialogue template. Bands are
# non-empty only when a bank holds >= 7 entries per role (all current banks: 20).
SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST = "train", "validation", "test"
SPLITS = (SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST)

# Surface paraphrase layer (Issue #281). Affixes never touch the trigger words a
# bank entry carries, so `trap` = keyword|paraphrase semantics are preserved.
_PREFIX = {
    "vi": ("", "Ơ", "Này", "Ừ", "À", "Anh ơi", "Em ơi", "Vâng", "Ok", "Thì", "Mà", "Chứ"),
    "en": ("", "Hey", "Look", "Well", "Uh", "So", "Ok", "Right"),
}
_SUFFIX = {
    "vi": ("", " nhé", " nha", " ạ", " đấy", " luôn", " mà", " nhá", " nè", " chứ", " ấy", " cơ"),
    "en": ("", " ok", " man", " please", " though", " alright", " yeah", " hey"),
}
_PUNCT = (".", "!", "...", "")


@cache
def pool_for_split(context: str, role: str, split: str) -> tuple[dict[str, Any], ...]:
    """Template pool restricted to one split; index partition guarantees every split non-empty."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {list(SPLITS)}")
    pool = load_pool(context, role)
    n = len(pool)
    a, b = int(n * 0.70), int(n * 0.70) + int(n * 0.15)
    bands = {
        SPLIT_TRAIN: slice(0, a),
        SPLIT_VALIDATION: slice(a, b),
        SPLIT_TEST: slice(b, n),
    }
    subset = pool[bands[split]]
    if not subset:
        raise ValueError(f"split band empty: context={context!r} role={role!r} split={split!r} pool_n={n}")
    return subset


def _vary(rng: random.Random, text: str, lang: str) -> str:
    """Deterministic surface paraphrase: prefix + text + suffix + punctuation."""
    prefixes = _PREFIX.get(lang, _PREFIX["vi"])
    suffixes = _SUFFIX.get(lang, _SUFFIX["vi"])
    prefix = rng.choice(prefixes)
    suffix = rng.choice(suffixes)
    punct = rng.choice(_PUNCT)
    core = f"{prefix} {text}" if prefix else text
    return f"{core}{suffix}{punct}"


CONTEXTS = (
    "normal_trip",
    "err01_unjustified_cancel",
    "err02_stall",
    "err02_slowcrawl",
    "err03_deviation",
    "err03_loop",
    "err04_phantom",
    "err05_fake_gps",
    "traffic_gridlock",
    "technical_dropout",
)

FRAUD_CONTEXTS = frozenset(
    {
        "err01_unjustified_cancel",
        "err02_stall",
        "err02_slowcrawl",
        "err03_deviation",
        "err03_loop",
        "err04_phantom",
        "err05_fake_gps",
    }
)

MIN_TURNS = 4
MAX_TURNS = 12
CUSTOMER_ONLY_MIN_TURNS = 2
CUSTOMER_ONLY_MAX_TURNS = 6
NO_REPORT_PROB_FRAUD = 0.30
NONE_REPORT_PROB = 0.40

DIALOGUE_MODES = ("full", "empty", "customer_only")


@cache
def load_pool(context: str, role: str) -> tuple[dict[str, Any], ...]:
    if context not in CONTEXTS:
        raise ValueError(f"unknown context {context!r}; expected one of {list(CONTEXTS)}")
    if role not in ("driver", "customer"):
        raise ValueError(f"unknown role {role!r}")
    with open(BANK_DIR / f"{context}.yaml", encoding="utf-8") as fh:
        bank = yaml.safe_load(fh)
    return tuple(bank[role])


def _render(text: str, trip_facts: dict[str, Any]) -> str:
    facts = dict(trip_facts or {})
    mapping = {
        "wait_min": int(facts.get("wait_s", 300) // 60),
        "dist_km": round(float(facts.get("distance_m", 2000)) / 1000, 1),
        "pickup": facts.get("pickup_name", "điểm đón"),
        "dest": facts.get("dest_name", "điểm đến"),
    }
    try:
        return text.format(**mapping)
    except (KeyError, IndexError, ValueError):
        return text


def synthesize_dialogue(
    rng: random.Random,
    context: str,
    trip_facts: dict[str, Any] | None,
    mode: str = "full",
    *,
    turn_count: int | None = None,
    split: str | None = None,
    paraphrase: bool = False,
) -> list[dict[str, Any]]:
    if mode not in DIALOGUE_MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {list(DIALOGUE_MODES)}")
    if mode == "empty":
        if context not in CONTEXTS:
            raise ValueError(f"unknown context {context!r}; expected one of {list(CONTEXTS)}")
        return []
    facts = trip_facts or {}
    if mode == "customer_only":
        pool = pool_for_split(context, "customer", split) if split else load_pool(context, "customer")
        n_turns = rng.randint(CUSTOMER_ONLY_MIN_TURNS, CUSTOMER_ONLY_MAX_TURNS)
        entries = rng.sample(pool, n_turns) if n_turns <= len(pool) else [rng.choice(pool) for _ in range(n_turns)]
        turns: list[dict[str, Any]] = []
        offset_s = 0
        for entry in entries:
            offset_s += rng.randint(5, 120)
            text = _render(str(entry["text"]), facts)
            if paraphrase:
                text = _vary(rng, text, entry.get("lang", "vi"))
            turns.append(
                {
                    "role": "customer",
                    "text": text,
                    "sent_at_offset_s": offset_s,
                    "lang": entry.get("lang", "vi"),
                }
            )
        return turns
    n_turns = rng.randint(MIN_TURNS, MAX_TURNS)
    role = rng.choice(["driver", "customer"])
    turns = []
    offset_s = 0
    for _ in range(n_turns):
        pool = pool_for_split(context, role, split) if split else load_pool(context, role)
        entry = rng.choice(pool)
        offset_s += rng.randint(5, 120)
        text = _render(str(entry["text"]), facts)
        if paraphrase:
            text = _vary(rng, text, entry.get("lang", "vi"))
        turns.append(
            {
                "role": role,
                "text": text,
                "sent_at_offset_s": offset_s,
                "lang": entry.get("lang", "vi"),
            }
        )
        role = "customer" if role == "driver" else "driver"
    return turns


def synthesize_objection_reason(
    rng: random.Random,
    context: str,
    trip_facts: dict[str, Any] | None,
) -> dict[str, str]:
    facts = trip_facts or {}
    if context in FRAUD_CONTEXTS and rng.random() < NO_REPORT_PROB_FRAUD:
        return {"status": "no_report", "text": ""}
    entry = rng.choice(load_pool(context, "driver"))
    status = "late" if context == "technical_dropout" and rng.random() < 0.25 else "present"
    return {"status": status, "text": _render(str(entry["text"]), facts)}


def synthesize_customer_report(
    rng: random.Random,
    context: str,
    trip_facts: dict[str, Any] | None,
) -> str | None:
    if rng.random() < NONE_REPORT_PROB:
        return None
    entry = rng.choice(load_pool(context, "customer"))
    return _render(str(entry["text"]), trip_facts or {})
