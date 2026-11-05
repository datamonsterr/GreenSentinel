---
name: github
description: Work with GitHub issues, pull requests and CI through the P-063 contributor workflow.
---

# GitHub

Read `CONTRIBUTING.md` for issue types, scope, hard dependencies and delivery. Use authenticated `gh`; never extract credentials. GitHub Issues are the task source of truth. Do not create a Markdown backlog.

Use `.agents/jev_skills/github-issue/SKILL.md` for issue management and `.agents/skills/pr-workflow/SKILL.md` for PRs. Fill the default PR template directly; specialized templates are optional. Use Conventional Commits with the actual changed scope.

```bash
gh pr view 75 --json title,body,state,isDraft
gh pr checks 75
gh run view RUN_ID --log
```

Do not start work blocked by unresolved prerequisites. Use Refs for partial scope, Closes only for accepted full DoD. Do not merge or deploy without applicable user authorization.
