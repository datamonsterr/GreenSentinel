---
name: github-issue
description: Create and manage Feature, User Story, Task, Bug and Documentation issues using the repository workflow.
---

# GitHub Issue Workflow

Read `CONTRIBUTING.md`; it is the canonical process. GitHub Issues are the sole task source. Never generate or update a Markdown backlog or copy issue bodies into repository docs.

1. Search open and closed issues before creating work. Read linked specs and existing implementation; retain source IDs and evidence.
2. Choose `.github/ISSUE_TEMPLATE/feature.md`, `user-story.md`, `task.md`, `bug.md` or `documentation.md`. Fill outcome/context, scope, observable acceptance/DoD and validation. Use native types Feature, Task for story/task/docs, Bug for bugs; label stories `user-story` and docs `documentation`.
3. Add one accountable assignee, priority and scheduled milestone. Use native parent/sub-issues only for independently assigned outcomes; mechanical steps remain checklists. Do not create a three-level hierarchy by default.
4. Feature **Blocked by** links are hard dependencies. Add the native relationship, record the accepted outcome needed, reject self-links/cycles and set `status:blocked`. No implementation, including dependent child work, starts until every direct/ancestor prerequisite closes as completed with accepted DoD. Informational links belong under Related. Report missing relationship permissions instead of starting blocked work.
5. Write the filled body without YAML frontmatter to a temporary file and use authenticated `gh issue create --type <Feature|Task|Bug> --body-file <file>`. Verify type, owner, labels, milestone, parents and blockers afterward. Never extract credential files or assume a `codex` label.
6. Follow ready / in-progress / blocked / in-review labels and GitHub closed state. On prerequisite closure/reopening, recheck all dependent gates; a not-planned closure is not accepted completion.
7. PRs use `Refs #N` for partial work and `Closes #N` only for complete evidenced DoD. A child PR references its parent unless it completes the parent too. Link specs, worklog/journal and accurate fixture/database/hosted evidence.

Issue creation and metadata setup may proceed when requested as GitHub task management. Do not infer merge/deploy authorization. Follow the strict PRD release boundary documented in `CONTRIBUTING.md`.
