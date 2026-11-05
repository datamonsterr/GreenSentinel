---
name: github-pr-workflow
description: Manage issue-linked PRs and CI using the P-063 canonical contributor workflow.
version: 1.2.0
---

# GitHub PR Workflow

Follow `CONTRIBUTING.md` and `.agents/skills/pr-workflow/SKILL.md`. Use an isolated worktree, an issue-number branch and Conventional Commits. Never start dependent implementation until all direct and ancestor Feature blockers have accepted completion.

Fill `.github/PULL_REQUEST_TEMPLATE.md`; optional specialized templates add only domain-specific evidence. Use `--body-file` for multiline descriptions. Every PR links issue/spec, DoD evidence, attributed worklog and journal. Closes means full DoD; Refs means partial scope. Do not close a parent through a child PR unless all parent acceptance is met.

Use authenticated `gh pr view`, `gh pr checks` and `gh run view`. Never extract tokens/credential files, generate another backlog or infer hosted proof from fixtures. Report unavailable checks; run focused checks for documentation/template changes. Merge/deploy only with applicable user authorization, then verify issue closure and reevaluate dependents.
