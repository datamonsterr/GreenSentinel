---
name: github-issues
description: Create, triage and link GitHub issues with native types and hard dependencies.
version: 1.3.0
---

# GitHub Issues Management

Follow `CONTRIBUTING.md` and `.agents/jev_skills/github-issue/SKILL.md`; do not maintain another process or backlog. Use actual repository templates and authenticated `gh`, without extracting tokens or credential files.

```bash
gh issue list --state all --search 'case dossier'
gh issue view 123 --json issueType,parent,subIssues,blockedBy
gh issue edit 123 --type Feature
gh issue edit 124 --parent 123
gh issue edit 123 --add-blocked-by 100 --add-label status:blocked \
  --remove-label status:ready,status:in-progress,status:in-review
```

A dependency completely blocks implementation until all direct and ancestor blockers are closed as completed with accepted DoD. Use linked Blocked by sections and native relationships; keep Related links non-blocking. Reject cycles and recheck dependents after closure/reopening. Never invent readiness from partial progress.

GitHub owns descriptions, acceptance/DoD, assignees, milestones and current status. Repository docs hold specs and historical evidence only. Remote management requires applicable user authorization; merging/deploying requires its own authorization.
