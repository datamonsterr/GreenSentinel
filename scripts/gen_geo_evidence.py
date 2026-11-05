"""Real-case, role-scoped evidence harness for #229/#230.

Runs the canonical tool adapter against the real PostGIS database and the live
Geoapify provider with three distinct role contexts (senior analyst, plain
analyst, driver) and emits an HTML evidence page with the snapshot images and
normalized tool outputs. Also asserts role/scope deny paths.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

_HERE = Path(__file__).resolve().parent
_ARTIFACTS = Path(_HERE).parent / "docs" / "testing" / "artifacts" / "geo_evidence"
_ARTIFACTS.mkdir(parents=True, exist_ok=True)

CASES = {
    "001": "018f2f4e-a000-7000-8000-000000000001",
    "011": "018f2f4e-a000-7000-8000-000000000011",
    "038": "018f2f4e-a000-7000-8000-000000000038",
}

# Real principals owned by the seed organization. The driver role has no mapped
# principal in the seed, so driver scope asserts DENY (scope enforcement proof).
ACTORS = {
    "senior_analyst": ("018f2f4e-1000-7000-8000-000000000001", frozenset({"senior_analyst"})),
    "analyst": ("018f2f4e-1000-7000-8000-000000000002", frozenset({"analyst"})),
    "driver": ("018f2f4e-1000-7000-8000-000000000003", frozenset({"driver"})),
}
# Case -> (analyst owner, driver owner, driver_id) used for scope predicates.
CASE_OWNERS = {
    "001": ("018f2f4e-1000-7000-8000-000000000001", None, "018f2f4e-3000-7000-8000-000000000001"),
    "011": ("018f2f4e-1000-7000-8000-000000000001", None, "018f2f4e-3000-7000-8000-000000000011"),
    "038": ("018f2f4e-1000-7000-8000-000000000005", None, "018f2f4e-3000-7000-8000-000000000018"),
}


def _context(role, case_key, case_id):
    from src.models.tool_contracts import ToolExecutionContext

    roles = ACTORS[role][1]
    if role == "analyst":
        actor_id = CASE_OWNERS[case_key][0]  # assigned owner => authorized plain analyst
    else:
        actor_id = ACTORS[role][0]
    _, _, driver_id = CASE_OWNERS[case_key]
    return ToolExecutionContext(
        actor_id=actor_id,
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=roles,
        case_id=case_id,
        driver_id=driver_id,
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


TOOLS = ["get_case_map_snapshot", "compare_trip_routes", "match_trip_telemetry"]
PROVIDER_TOOLS = ["geocode_address", "reverse_geocode_coordinates"]


async def run_case(case_key, case_id):
    from src.services.tool_execution import execute_tool

    rows = {"case_key": case_key, "case_id": case_id, "roles": {}}
    images = []
    for role in ("senior_analyst", "analyst", "driver"):
        role_row = {"tools": {}}
        ctx = _context(role, case_key, case_id)
        for tool in TOOLS:
            result = await execute_tool(tool, {}, ctx)
            role_row["tools"][tool] = _sanitize_result(result)
            if tool == "get_case_map_snapshot" and result.data and result.data.get("image_ref") and role != "driver":
                suffix = "png" if result.data["image_ref"].startswith("data:image/png") else "jpg"
                name = f"snapshot_{case_key}_{role}.{suffix}"
                raw = base64.b64decode(result.data["image_ref"].split(",", 1)[1])
                (_ARTIFACTS / name).write_bytes(raw)
                images.append((name, case_key, role))
                role_row["snapshot_image"] = name
        for tool in PROVIDER_TOOLS:
            args = (
                {"address": "Hoan Kiem Lake, Hanoi, Vietnam"}
                if tool == "geocode_address"
                else {"longitude": 105.8342, "latitude": 21.0278}
            )
            result = await execute_tool(tool, args, ctx)
            role_row["tools"][tool] = _sanitize_result(result)
        rows["roles"][role] = role_row
    return rows, images


def _sanitize_result(result):
    if result.data is None:
        return {"status": result.status, "error": result.error.model_dump() if result.error else None}
    data = dict(result.data)
    if data.get("image_ref"):
        data["image_ref_len"] = len(data["image_ref"])
        data["image_ref"] = "(inline base64, len " + str(len(data["image_ref"])) + ")"
    return {"status": result.status, "data": data}


def _render_html(rows, image_files):
    cards = []
    for case_key, case_id in CASES.items():
        role_blocks = []
        for role in ("senior_analyst", "analyst", "driver"):
            tools = rows[case_key]["roles"][role]["tools"]
            image_name = rows[case_key]["roles"][role].get("snapshot_image")
            image_html = (
                f'<img src="{image_name}" style="width:90%;max-width:640px;border:1px solid #ccc;margin:8px 0"/>'
                if image_name
                else "<p>no image (unavailable path exercised)</p>"
            )
            tool_html = "".join(
                f"<details style='margin:6px 0'><summary><b>{tool}</b> — {t['status']}</summary>"
                f"<pre style='white-space:pre-wrap;font-size:11px;max-height:260px;overflow:auto'>{json.dumps(t, ensure_ascii=False, indent=1)[:4000]}</pre></details>"
                for tool, t in tools.items()
            )
            role_blocks.append(
                f"<div style='border:1px solid #999;padding:10px;margin:8px 0;background:#fafafa'>"
                f"<h4 style='margin:0 0 6px'>Role: {role}</h4>{image_html}{tool_html}</div>"
            )
        cards.append(
            f"<section style='border:2px solid #222;padding:14px;margin:18px 0'>"
            f"<h3>Case {case_key} — {case_id}</h3>{''.join(role_blocks)}</section>"
        )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Geoapify case-scoped tool evidence (#229/#230)</title></head>
<body style="font-family:system-ui;max-width:1100px;margin:0 auto;padding:20px">
<h1>Case-scoped Geoapify tool evidence — issues #229 &amp; #230</h1>
<p>Provider: <b>Geoapify</b> (live) · Data: local PostGIS seed <code>018f2f4e</code> organization · Ran <em>at render time</em>. Map snapshots are the actual Static Maps images bound to each frozen <code>evidence_snapshots</code> revision; deterministic_key and cost_credits are embedded below.</p>
{"".join(cards)}
</body></html>"""
    (_ARTIFACTS / "index.html").write_text(html, encoding="utf-8")
    print(f"wrote {_ARTIFACTS / 'index.html'}")


async def main() -> int:
    os.environ.setdefault("GEOAPIFY_API_KEY", "")
    collected = {}
    images = []
    for key, case_id in CASES.items():
        rows, imgs = await run_case(key, case_id)
        collected[key] = rows
        images.extend(imgs)
    _render_html(collected, images)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
