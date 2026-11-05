# Contributing to GreenSentinel

Use [GitHub Issues](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues) for features, user stories, tasks, bugs, ownership, priorities, dependencies and progress. Keep acceptance criteria and Definition of Done (DoD) in the issue. Do not copy the backlog or issue bodies into Markdown files. Repository docs hold product specifications, design decisions and historical evidence; link them from issues.

## Choose the smallest useful issue

| Template | GitHub type | Use it for |
|---|---|---|
| Feature | Feature | One independently demonstrable product or engineering capability, including a feature-sized data/QA outcome |
| User Story | Task + `user-story` label | An actor's goal and observable behavior; use As / I want / So that and Given / When / Then |
| Task | Task | A coherent technical deliverable that enables a feature or story |
| Bug | Bug | A reproducible failure or confirmed specification mismatch |
| Documentation | Task + `documentation` label | A specification, decision or contributor-documentation change |

Start with the [issue chooser](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/new/choose). Search open and closed issues first. Use a clear outcome-based title, context/specification links, scope, acceptance/DoD checklist and validation plan. Add one accountable assignee, a priority (`priority:P0`, `priority:P1`, `priority:P2`) and a milestone when scheduled. Existing source IDs belong in issue context, not in a parallel task register.

A feature may stand alone. Add a User Story or Task as a native sub-issue only when it has a separately assignable and verifiable outcome. Do not create all three levels by default; keep mechanical implementation steps in the issue checklist. A parent is complete only when its own acceptance criteria and all required sub-issues are accepted. Existing `feature` and `bug` labels are compatibility tags; native issue type is authoritative.

## Dependencies are hard blockers

For a prerequisite, add its issue link and the required accepted outcome under **Blocked by** in the Feature issue, and add the native GitHub **Blocked by** relationship. If Feature A depends on Feature B, A and all its dependent stories/tasks are completely blocked: no implementation starts until B is closed as completed with accepted DoD covering its entire scope. A partial PR, a `not planned` closure or some completed sub-issues do not satisfy the dependency.

All prerequisites must be accepted before work starts. Keep one `status:blocked` label while any blocker is unresolved; remove `status:ready`, `status:in-progress` and `status:in-review`. Check direct blockers and any ancestor Feature's blockers before claiming a child issue. Detect self-links and cycles before adding dependencies; resolve a cycle by changing scope, never by pretending one side is ready. If a prerequisite reopens, block the dependent work again.

Use **Related** for useful context that does not stop work. Parent/sub-issue links describe scope and ownership; they do not replace dependency links. A deferred issue stays blocked outside the active milestone until explicitly scheduled.

```bash
# Issue 123 depends on accepted completion of issue 100.
gh issue edit 123 --add-blocked-by 100 --add-label status:blocked \
  --remove-label status:ready,status:in-progress,status:in-review
```

When every blocker is accepted, move the issue to ready. Keep dependency links for traceability; do not erase them to make an issue appear unblocked. If GitHub relationship editing is unavailable, keep the explicit linked Blocked by section and blocked label, report the missing native link, and do not start work.

## Deliver an issue

1. Read the issue, its ancestor Features and the linked specs. Verify every blocker is accepted. Choose ready work, assign its owner and set `status:in-progress`.
2. Use an isolated branch/worktree; preserve other contributors' edits. Name the branch with the issue number and a short intent.
3. Implement the issue's agreed outcome. Add relevant tests and record observed results; resolve business ambiguity before dependent implementation.
4. Open a PR against `main` using the default PR template. Set the issue to `status:in-review`. Link the specification and evidence for each DoD item.
5. Use `Closes #N` only for fully accepted scope. Use `Refs #N` for partial work. A child PR references its parent Feature unless it completes the parent's full DoD too.
6. After authorized merge and required checks, verify issue closure. Recheck dependent issues and move them to ready only when every prerequisite is accepted. Closed issue state means done; no separate done label or Markdown status ledger.

Use exactly one delivery label: `status:ready`, `status:in-progress`, `status:blocked` or `status:in-review`. `priority:P0` is release-critical, P1 supporting work and P2 optional/deferred. `scope:deferred` excludes future work from the active milestone. A Project board is optional and should mirror these fields, not introduce another manually maintained status.

## Branch and validation examples

```bash
git fetch origin
git worktree add .worktrees/issue-123 -b feat/123-case-dossier origin/main
```

From that worktree, run the checks appropriate to the change. For Python implementation:

```bash
bash scripts/check.sh
```

For frontend commands and database/browser proof, follow [the POC test matrix](docs/testing/MANUAL_TEST_POC_V2.md). Documentation/template changes need frontmatter, repository-link and whitespace checks; include relevant CI results. Report blocked/skipped checks with the exact error. Do not change scope or dependencies to make a check pass.

Record commit, environment, commands/results and artifact links in the PR. Distinguish fixtures/local checks, migrated isolated-database proof and hosted browser observations. Never invent unavailable GPS, traffic, policy sources or acceptance evidence. Manual test reports live in `docs/testing/`; CI retains machine artifacts.

Every PR links an attributed [worklog entry](docs/worklog/WORKLOG.md) or daily entry and the [journal](docs/journal/JOURNAL.md). These capture historical work and evidence, not copies of current issue checklists/status. Read each subfolder README before updating those records. AI usage logging is automatic; do not run log scripts manually.

## Agent workflow

Use authenticated `gh` to inspect actual issues, native types, parents and blockers before acting. Start from the selected issue template, preserve source IDs and existing evidence, and use `--body-file` for multiline text. Do not create a Codex-only issue or assume a `codex` label exists. Do not regenerate a Markdown backlog.

```bash
gh issue list --state all --search 'case dossier'
gh issue create --title 'Render source-backed case dossier' \
  --type Feature --body-file /tmp/feature.md --assignee YOUR_LOGIN \
  --label priority:P0 --label status:ready
# Attach an independently assignable task to a Feature.
gh issue edit 124 --parent 123
```

GitHub creation using `--body-file` should receive a filled body without template YAML frontmatter. Verify native type, assignee, milestone, labels and dependencies after mutation. Do not merge or deploy without applicable user authorization. Keep all task updates in GitHub.

## Product scope and credentials

[PRD](docs/ba/PRD.md) and [MVP](docs/ba/MVP.md) govern Phase 1. The user confirmed strict PRD scope: analyst confirmation is required for dismissal and sanctions; driver mobile expansion remains deferred. PR #40 is existing implementation to review, not approval to change those rules. Keep task-specific reconciliation in the relevant GitHub issue.

This repository is public. Keep real credentials in ignored local `.env` files; use only placeholders in `.env.example`. Never extract or print token/credential files during GitHub operations. Rotate exposed keys and follow the security runbook. Report vulnerabilities through [private reporting](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/security/advisories/new).

Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
