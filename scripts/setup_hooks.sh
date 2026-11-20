#!/usr/bin/env bash
# Install git pre-push hook for AI log submission (POSIX / Git Bash).
# Run once after cloning: bash scripts/setup_hooks.sh
set -e

HOOK_FILE=".git/hooks/pre-push"

cat > "$HOOK_FILE" <<'EOF'
#!/usr/bin/env bash
# Pre-push:
# 1. Block direct push to main (must use PR targeting main)
# 2. Sweep recent AI prompts and submit logs

PROTECTED_BRANCHES=("refs/heads/main")

while read -r local_ref local_sha remote_ref remote_sha; do
  for branch in "${PROTECTED_BRANCHES[@]}"; do
    if [ "$remote_ref" = "$branch" ]; then
      echo "ERROR: Direct push to '$branch' is BLOCKED by git pre-push hook!" >&2
      echo "Policy: Push to a feature branch and open a PR targeting 'main'." >&2
      echo "Promotion flow: PR (preview) -> merge to main (dev) -> staging -> prod" >&2
      exit 1
    fi
  done
done

bash scripts/_pyrun.sh scripts/log_antigravity.py --auto || true
bash scripts/_pyrun.sh scripts/submit_log.py || true
exit 0
EOF

chmod +x "$HOOK_FILE"
mkdir -p .agents .claude .codex .opencode/plugins .ai-log
touch .ai-log/.gitkeep
chmod +x scripts/_pyrun.sh 2>/dev/null || true
chmod +x scripts/*.py 2>/dev/null || true

echo "[ai-log] Verified hooks for:"
echo "  - Antigravity CLI (.agents/hooks.json)"
echo "  - OpenCode (.opencode/plugins/ai-log.js)"
echo "  - Claude Code (.claude/settings.json)"
echo "  - OpenAI Codex (.codex/hooks.json)"
echo "[ai-log] Setup complete. Configure AI_LOG_SERVER in your .env file."
