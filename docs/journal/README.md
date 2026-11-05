# Engineering Journal Guide & Specifications

> **MANDATORY RULE**: Any AI agent or developer updating documents in `docs/journal/` **MUST** read this `README.md` first before creating or modifying entries.

## 1. Purpose & Scope
The engineering journal records weekly reflections, high-level sprint progress, resolved roadblocks, and strategic technical decisions for Demo Day deliverable #8.

## 2. Filename Conventions
- Primary rolling journal: [`JOURNAL.md`](docs/journal/JOURNAL.md) (maintained in this folder).
- Milestone / Sprint deep-dives: `week-NN.md` (e.g., [`week-01.md`](docs/journal/week-01.md), `week-02.md`).

## 3. Required Questions to Answer
Every weekly journal entry **MUST** explicitly address these 5 core questions:
1. **Sprint Objectives**: What were the planned goals for the week, and which ones were achieved?
2. **Completed Artifacts**: What production code, tools, or documents were delivered?
3. **Roadblocks & Obstacles**: What unexpected technical challenges, bugs, or harness issues occurred?
4. **Solutions & Outcomes**: Exactly how was each roadblock resolved, and what was the verifiable result?
5. **Key Learnings & Next Steps**: What engineering insights were gained, and what are the prioritized goals for next week?

## 4. Standard Entry Template

```markdown
## Week N: [Start Date] - [End Date]

### Objectives
- [x] [Goal 1]
- [ ] [Goal 2]

### Completed Work
- [Detailed achievement with clickable file link]

### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| [Issue description] | [Exact technical fix] | [Verifiable result] |

### Key Learnings
1. [Core takeaway 1]
2. [Core takeaway 2]

### Next Week Plan
- [ ] [Planned task 1]
```

## 5. Required Skills
- `write-a-doc`: Follows standard documentation formatting and checks.
- `rtk`: Enforces zero conversational filler, high information density, and clean diffs.
- `mnemoverse`: Queries and persists high-value architectural lessons across sessions.
