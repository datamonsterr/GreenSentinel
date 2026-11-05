"""EDA: MultiWOZ 2.2 taxi dialogues + SGD structural reference.

Reads extracted repo tarballs under data/raw (git-ignored). Writes only
aggregate stats + short anonymized snippets to notebooks/dialogues/profile.json.
No raw redistribution. SGD is CC BY-SA (EDA-ONLY): stats only, no utterance quotes.
MultiWOZ is MIT: small snippets allowed.
"""

from __future__ import annotations

import collections
import glob
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MW = ROOT / "data/raw/multiwoz/multiwoz-master/data/MultiWOZ_2.2"
SGD = ROOT / "data/raw/sgd_dialogue/dstc8-schema-guided-dialogue-master"
OUT = ROOT / "notebooks/dialogues"

CANCEL_RE = re.compile(
    r"\bcancel|change my mind|modify|wrong (information|car|taxi|booking)|"
    r"never (got|given|came|arrived|received)|still waiting|not happy|complain|"
    r"back up|wrong car\b",
    re.I,
)


def q(a: np.ndarray) -> dict:
    a = np.asarray(a, dtype=float)
    out = {"count": int(len(a))}
    if len(a):
        keys = ["min", "p05", "p25", "p50", "p75", "p95", "max"]
        for k, v in zip(keys, np.quantile(a, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1])):
            out[k] = round(float(v), 3)
        out["mean"] = round(float(a.mean()), 3)
        out["std"] = round(float(a.std()), 3)
    return out


def load_mw() -> tuple[list, list]:
    all_d, taxi_d = [], []
    for split in ("train", "dev", "test"):
        for f in sorted(glob.glob(str(MW / split / "dialogues_*.json"))):
            for d in json.load(open(f)):
                all_d.append(d)
                if "taxi" in [s.lower() for s in d.get("services", [])]:
                    taxi_d.append(d)
    return all_d, taxi_d


def mw_stats(taxi_d: list) -> dict:
    turns, uturns, ulen_c, ulen_w, slen_c, slen_w = [], [], [], [], [], []
    slot_c = collections.Counter()
    taxi_only = 0
    for d in taxi_d:
        t = d.get("turns", [])
        turns.append(len(t))
        if set(s.lower() for s in d.get("services", [])) == {"taxi"}:
            taxi_only += 1
        for turn in t:
            u = turn.get("utterance", "") or ""
            if turn.get("speaker") == "USER":
                uturns.append(1)
                ulen_c.append(len(u))
                ulen_w.append(len(u.split()))
            else:
                slen_c.append(len(u))
                slen_w.append(len(u.split()))
            for fr in turn.get("frames", []) or []:
                st = (fr.get("state") or {}).get("slot_values", {}) or {}
                for k, v in st.items():
                    if k.startswith("taxi-") and v:
                        slot_c[k] += 1
    user_per = []
    for d in taxi_d:
        user_per.append(sum(1 for t in d.get("turns", []) if t.get("speaker") == "USER"))
    return {
        "n_dialogues": len(taxi_d),
        "taxi_only_dialogues": taxi_only,
        "turns_total": q(np.array(turns)),
        "user_turns_per_dialogue": q(np.array(user_per)),
        "user_utt_chars": q(np.array(ulen_c)),
        "user_utt_words": q(np.array(ulen_w)),
        "system_utt_chars": q(np.array(slen_c)),
        "system_utt_words": q(np.array(slen_w)),
        "taxi_slot_mentions": dict(slot_c.most_common(20)),
    }


def complaint_quotes(taxi_d: list, k: int = 8) -> list[dict]:
    out = []
    for d in taxi_d:
        for t in d.get("turns", []):
            if t.get("speaker") != "USER":
                continue
            u = (t.get("utterance") or "").strip()
            if CANCEL_RE.search(u) and 20 <= len(u) <= 220 and len(out) < 40:
                out.append({"dialogue_id": d.get("dialogue_id"), "utterance": u})
    # diverse pick: spread across dialogues
    seen, picks = set(), []
    for r in out:
        if r["dialogue_id"] not in seen:
            seen.add(r["dialogue_id"])
            picks.append(r)
        if len(picks) == k:
            break
    return picks


def sgd_stats() -> dict:
    n, turns, ulen_w, svc_c = 0, [], [], collections.Counter()
    ride_turns, ride_ulen = [], []
    ride_services = {"RideSharing_1", "RideSharing_2", "Buses_1", "Buses_2", "Buses_3", "Flights_1"}
    ride_n = 0
    slot_c = collections.Counter()
    for split in ("train", "dev", "test"):
        for f in sorted(glob.glob(str(SGD / split / "dialogues_*.json"))):
            for d in json.load(open(f)):
                n += 1
                svcs = d.get("services", [])
                for s in svcs:
                    svc_c[s] += 1
                t = d.get("turns", [])
                turns.append(len(t))
                is_ride = bool(set(svcs) & ride_services)
                if is_ride:
                    ride_n += 1
                    ride_turns.append(len(t))
                for turn in t:
                    u = turn.get("utterance", "") or ""
                    if turn.get("speaker") == "USER":
                        ulen_w.append(len(u.split()))
                        if is_ride:
                            ride_ulen.append(len(u.split()))
                    for fr in turn.get("frames", []) or []:
                        for a in fr.get("actions", []) or []:
                            if a.get("slot") and a.get("slot") != "intent":
                                slot_c[f"{fr.get('service')}:{a.get('slot')}"] += 1
    return {
        "n_dialogues": n,
        "turns_total": q(np.array(turns)),
        "user_utt_words": q(np.array(ulen_w)),
        "ride_subset_dialogues": ride_n,
        "ride_turns_total": q(np.array(ride_turns)),
        "ride_user_utt_words": q(np.array(ride_ulen)),
        "top_services": dict(svc_c.most_common(15)),
        "top_slots": dict(slot_c.most_common(25)),
    }


def run() -> dict:
    all_d, taxi_d = load_mw()
    report = {
        "provenance": {
            "multiwoz": "data/raw/multiwoz (MIT), MultiWOZ 2.2 JSON, services incl taxi",
            "sgd": "data/raw/sgd_dialogue (CC BY-SA 4.0, EDA-ONLY: stats only, no quotes)",
            "multiwoz_dialogues_total": len(all_d),
        },
        "multiwoz_taxi": mw_stats(taxi_d),
        "complaint_cancellation_snippets_mw_taxi_mit_only": complaint_quotes(taxi_d),
        "sgd": sgd_stats(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "profile.json").write_text(json.dumps(report, indent=2) + "\n")
    m = report["multiwoz_taxi"]
    print(f"mw_taxi={m['n_dialogues']} taxi_only={m['taxi_only_dialogues']}")
    print(f"turns p50={m['turns_total']['p50']} user_words p50={m['user_utt_words']['p50']}")
    print(f"slots={m['taxi_slot_mentions']}")
    print(f"sgd_n={report['sgd']['n_dialogues']} ride={report['sgd']['ride_subset_dialogues']}")
    print(f"snippets={len(report['complaint_cancellation_snippets_mw_taxi_mit_only'])}")
    return report


if __name__ == "__main__":
    run()
