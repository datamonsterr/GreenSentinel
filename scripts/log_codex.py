#!/usr/bin/env python3
"""Recover this repository's actual user messages from Codex rollout files."""

import hashlib
import json
import os
from pathlib import Path

from log_hook import normalize

ROOT = Path(__file__).resolve().parent.parent
INJECTED = ("<environment_context>", "<recommended_plugins>", "# AGENTS.md instructions", "<skill>", "<turn_aborted>")


def records(path: Path):
    """Ignore incomplete last lines while Codex is still writing a rollout."""
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        yield value
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return


def collect(sessions: Path, log_dir: Path) -> int:
    """Deduplicate against both pending and archived entries, preserving source IDs."""
    os.chdir(ROOT)
    seen = {
        entry.get("entry_id") for path in log_dir.rglob("*.jsonl") for entry in records(path) if entry.get("entry_id")
    }
    additions = []
    for path in sorted(sessions.rglob("*.jsonl")):
        rows = list(records(path))
        meta = next((r.get("payload", {}) for r in rows if r.get("type") == "session_meta"), {})
        cwd = meta.get("cwd")
        if not cwd or not Path(cwd).resolve().is_relative_to(ROOT):
            continue
        model = next((r.get("payload", {}).get("model", "") for r in rows if r.get("type") == "turn_context"), "")
        for index, row in enumerate(rows):
            payload = row.get("payload", {})
            if row.get("type") != "response_item" or payload.get("role") != "user":
                continue
            content = payload.get("content", [])
            parts = [part.get("text", "") for part in content if part.get("type") == "input_text"]
            prompt = "".join(part for part in parts if not part.lstrip().startswith(INJECTED)).strip()
            if not prompt:
                continue
            entry_id = hashlib.sha256(f"codex:{meta.get('id', path.name)}:{index}".encode()).hexdigest()
            if entry_id in seen:
                continue
            entry = normalize(
                {
                    "prompt": prompt,
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": meta.get("id", ""),
                    "model": model,
                },
                "codex",
            )
            if entry is None:
                continue
            entry.update(entry_id=entry_id, ts=row.get("timestamp") or entry["ts"], prompt=prompt)
            additions.append(entry)
            seen.add(entry_id)
    if additions:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "session.jsonl").open("a", encoding="utf-8") as stream:
            for entry in additions:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(additions)


def main() -> None:
    codex_dir = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    log_dir = Path(os.environ.get("AI_LOG_DIR", str(ROOT / ".ai-log"))).resolve()
    count = collect(codex_dir / "sessions", log_dir)
    print(f"[ai-log] Recovered {count} Codex prompts.")


if __name__ == "__main__":
    main()
