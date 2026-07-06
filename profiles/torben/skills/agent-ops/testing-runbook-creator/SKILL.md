---
name: testing-runbook-creator
description: Capture repo-specific testing, verification, smoke-test, QA, and debugging knowledge as a repo-local runbook. Use for any testing or verification activity in a repo, whether or not Eric says "runbook".
---

# Testing Runbook Creator

## Trigger Rule

Use this skill for any repo testing activity:

- tests,
- smoke tests,
- QA,
- debug reproduction,
- browser verification,
- CLI verification,
- release validation,
- manual workflow checks.

Do not wait for Eric to ask for a runbook.

## Runbook Location

Default to `docs/testing-runbook.md` in the repo root unless the repo already has a testing runbook or docs convention. If no repo root is clear, find it first.

## Read-First Rule

Before testing, read the runbook section relevant to the feature/page/workflow if it exists. Follow the existing recipe. If it is wrong or stale, update it in the same session.

## Entry Format

Use this entry shape:

```markdown
## Feature Or Workflow Name

Last verified: YYYY-MM-DD

### Scope
- Page/workflow/feature:
- Repo area:

### Setup And Seed Data
- ...

### Safe Actions
- ...

### Destructive Or External Actions
- ...

### Steps
1. ...

### Verification Commands
```bash
command
```

Expected result:
- ...

### Evidence
- Screenshot/log/artifact paths:

### Cleanup
- ...

### Known Failure Modes
- ...
```

## Record-As-You-Go Rule

Record discoveries while testing, not as an end-of-session afterthought. If you learn a route, selector, seed requirement, fake account, environment variable, cleanup quirk, or expected output, add it to the runbook when learned.

## Update Rule

When reality differs from the runbook:

1. Trust current verified behavior.
2. Update the runbook.
3. Mention the change in the final report.

## Safety

Separate safe checks from destructive or external actions. Email sends, posts, calendar mutations, broker orders, deletes, production writes, and paid actions require explicit approval and should be documented as destructive/external.

## Final Report

After testing, report:

- What was tested.
- Result.
- Exact commands or manual checks.
- Evidence path.
- Runbook path and section updated.
