---
description: "Security rules, secret hygiene, credential leak prevention, and incident response"
activation: always-on
---

# Security & Credential Hygiene Rules

## 1. Environment Secrets Hygiene
- **Never commit credentials**: No live API keys, tokens, or passwords in git.
- `.env` is strictly local and listed in `.gitignore`.
- `.env.example` must only contain dummy placeholders (e.g., `your-key-here`).
- Treat `AI_LOG_API_KEY` and LLM provider keys as confidential team secrets.

## 2. Pre-Commit Audit
Before staging or committing changes, run:
```bash
git diff --cached | grep -iE "api[_-]?key|secret|token|password"
```

## 3. Incident Response for Leaked Keys
If a secret is accidentally committed:
1. **Rotate immediately**: Invalidate the key in the provider dashboard (OpenAI, Phoenix, etc.). This is the only way to revoke access.
2. **Replace with placeholder** in working copy and commit.
3. **Purge git history**: Run `git-filter-repo` to scrub the secret from all commits, then force-push.
4. **Notify team**: Prompt team members to re-clone or rebase their branches.

## 4. Prompt Log Auditing
The `.ai-log/` directory stores raw prompts. Ensure no confidential personal data or secrets exist in logs before publishing or sharing repository forks.
