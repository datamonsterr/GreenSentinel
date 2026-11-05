# Engineering Worklog Guide & Specifications

> **MANDATORY RULE**: Any AI agent or developer updating documents in `docs/worklog/` **MUST** read this `README.md` first before creating or modifying entries.

## 1. Purpose & Scope
The engineering worklog captures daily granular development activities, member contributions, and verifiable outputs for Demo Day deliverable #9.

## 2. Filename Conventions
- Primary rolling worklog: [`WORKLOG.md`](docs/worklog/WORKLOG.md) (maintained in this folder).
- Milestone / Daily archives: `YYYY-MM-DD.md` (e.g., [`2026-09-12.md`](docs/worklog/2026-09-12.md)).

## 3. Required Questions to Answer
Every daily worklog entry **MUST** explicitly address these 5 core questions:
1. **Member Attribution**: Who performed the work (full name)?
2. **Task Specifics**: What exact technical task was worked on?
3. **Task Status**: What is the current status (`✅ Done`, `🔄 WIP`, `❌ Blocked`)?
4. **Verifiable Output**: What concrete file, commit, PR, or test output was produced (must include clickable link)?
5. **Time & Summary**: How much time was spent on each task, and what is the overall daily summary of progress?

## 4. Standard Entry Template

```markdown
## YYYY-MM-DD

| Member | Task Description | Status | Deliverable / Output | Time |
|---|---|---|---|---|
| [Name] | [Specific task description] | ✅ Done | [`filename`](file:///path) | 1.5h |
| [Name] | [Ongoing task] | 🔄 WIP | [Branch/PR link] | 2.0h |
| [Name] | [Blocked task] | ❌ Blocked | [Blocker reason] | - |

**Daily Summary:** [1-2 sentences summarizing daily velocity, major blockers, or breakthroughs]
```

## 5. Required Skills
- `write-a-doc`: Orchestrates document drafting and verifies question coverage.
- `rtk`: Maintains compact table formatting without prose redundancy.
