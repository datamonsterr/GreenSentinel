#!/usr/bin/env bash
# Cross-platform Python launcher for AI log hooks.
# Tries python3 → python → py -3 on PATH; on Windows, falls back to common
# Python install locations because Git Bash launched by some hooks gets a
# stripped PATH that omits the Windows Python directory.
# Designed to be sourced or called as: bash scripts/_pyrun.sh <script> [args...]
#
# Exits 0 silently if no Python is found — hooks must never block the AI tool.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Each candidate must actually start: a venv whose base interpreter was removed (e.g. after
# an OS reset) still has an executable python, so existence alone is not enough.
_works() { "$@" -c "import sys" >/dev/null 2>&1; }

PY=()
for cand in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/.venv/Scripts/python.exe"; do
  if [ -x "$cand" ] && _works "$cand"; then PY=("$cand"); break; fi
done
if [ "${#PY[@]}" -eq 0 ]; then
  if command -v python3 >/dev/null 2>&1 && _works python3; then
    PY=(python3)
  elif command -v python >/dev/null 2>&1 && _works python; then
    PY=(python)
  elif command -v py >/dev/null 2>&1 && _works py -3; then
    PY=(py -3)
  fi
fi
if [ "${#PY[@]}" -eq 0 ]; then
  # PATH lookup failed — probe standard Windows install locations.
  shopt -s nullglob 2>/dev/null || true
  for cand in     /c/Users/*/AppData/Local/Programs/Python/Python*/python.exe     "/c/Program Files/Python"*/python.exe     "/c/Program Files (x86)/Python"*/python.exe     /c/Python*/python.exe; do
    if [ -x "$cand" ] && _works "$cand"; then PY=("$cand"); break; fi
  done
  shopt -u nullglob 2>/dev/null || true
  [ "${#PY[@]}" -gt 0 ] || exit 0
fi

# Array expansion keeps paths with spaces (e.g. "D:/Vin AI/...") intact.
exec "${PY[@]}" "$@"
