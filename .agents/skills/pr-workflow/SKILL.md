---
name: pr-workflow
description: Follow CONTRIBUTING for issue-linked PR delivery, evidence and review.
---

# Pull Request Workflow

Read `CONTRIBUTING.md` as the canonical workflow. Fill `.github/PULL_REQUEST_TEMPLATE.md` directly; specialized templates in `.github/PULL_REQUEST_TEMPLATE/` are optional extensions.

Before implementation, inspect the issue's direct and ancestor Feature blockers. Dependencies are hard gates; do not start dependent work until every prerequisite is completed with accepted DoD. Use an isolated worktree and preserve others' edits.

Every PR links an issue and applicable spec/source IDs. Use `Refs #N` for partial delivery and `Closes #N` only for complete evidenced DoD. A child PR references its parent unless the parent's complete DoD is also met. Link attributed worklog/daily entry and journal; read their subfolder guides first. Never copy the issue backlog into Markdown.

Run checks appropriate to the change. Python implementation uses `bash scripts/check.sh`; documentation/templates use frontmatter, link and whitespace checks plus relevant CI. Record commands/results and distinguish fixtures, isolated database and hosted/browser proof. Report blocked checks honestly. Review diff for secrets, update affected specs, set issue in-review and verify required CI.

Do not merge or deploy without applicable user authorization. After accepted completion, verify closure and recheck dependent issues; a not-planned closure does not unblock work.
