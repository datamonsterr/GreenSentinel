"""Chronological operational history, independent from benchmark truth and priors."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta


def driver_split(driver_id: str) -> str:
    """Fixed 70/15/15 hash partition; never split an individual driver's trips."""
    bucket = int(hashlib.sha256(driver_id.encode()).hexdigest()[:16], 16) / 2**64
    return "train" if bucket < 0.70 else "validation" if bucket < 0.85 else "test"


def operational_events(bundles: list[dict]) -> list[dict]:
    return sorted(
        [
            {
                "trip_ref": bundle["trip_ref"],
                "driver_id": bundle["driver_id"],
                "occurred_at": bundle["assignment"]["ended_at"],
                "cancelled": bundle["trip"]["status"] == "cancelled",
                "passenger_report": bool(bundle["customer_report"]),
                "provenance": "synthetic operational terminal event",
            }
            for bundle in bundles
        ],
        key=lambda e: (e["occurred_at"], e["trip_ref"]),
    )


def attach_history(bundles: list[dict]) -> list[dict]:
    """Use only terminal events strictly before request time, with [as_of-d, as_of) windows.

    Overlapping trips do not see one another's eventual outcomes. The persistent
    ledger contains operational outcomes/report presence, never labels or priors.
    """
    histories: dict[str, list[dict]] = defaultdict(list)
    ledger = operational_events(bundles)
    for event in ledger:
        histories[event["driver_id"]].append(event)
    for events in histories.values():
        events.sort(key=lambda e: (e["occurred_at"], e["trip_ref"]))
    for bundle in bundles:
        now = datetime.fromisoformat(bundle["requested_at"])
        earlier = [e for e in histories[bundle["driver_id"]] if datetime.fromisoformat(e["occurred_at"]) < now]
        analytics = {
            "driver_id": bundle["driver_id"],
            "as_of": bundle["requested_at"],
            "provenance": "earlier terminal events in synthetic driver ledger; no background priors",
            "window_semantics": "[as_of - days, as_of); event time is terminal outcome time",
        }
        for days in (7, 30):
            events = [e for e in earlier if datetime.fromisoformat(e["occurred_at"]) >= now - timedelta(days=days)]
            cancellations = sum(e["cancelled"] for e in events)
            analytics[f"window_{days}d"] = {
                "trips": len(events),
                "cancellations": cancellations,
                "cancellation_rate": round(cancellations / len(events), 4) if events else None,
                "complaints": sum(e["passenger_report"] for e in events),
            }
        bundle["driver_analytics"] = analytics
        bundle["driver_ledger"] = earlier
        bundle["split"] = driver_split(bundle["driver_id"])
        bundle["driver_prior_background"] = {
            "provenance": "synthetic population assumptions, not observed ledger counts",
            "profile_provenance": bundle["driver_profile"].get("profile_provenance", {}),
        }
    return sorted(ledger, key=lambda e: (e["occurred_at"], e["trip_ref"]))
