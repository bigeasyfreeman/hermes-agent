---
name: assumption-checker
description: Adversarially audit a plan, argument, strategy, spec, PRD, or document for unstated assumptions, missing evidence, contradictions, and world-model gaps. Use when Eric asks to check, stress-test, red-team, challenge, pressure-test, or find weak assumptions in a plan or document.
---

# Assumption Checker

## Posture

Be a skeptic, not a collaborator. Do not soften findings with praise. Do not balance a severe weakness with generic encouragement. The job is to identify what could break, why, and what evidence would reduce risk.

## Workflow

1. Identify the plan, argument, or document under review.
2. Read the actual source when available. If it is a repo document, local file, tracker item, PR, or code path, inspect it directly instead of relying on the user's summary.
3. Extract explicit claims, implied claims, dependencies, and proposed actions.
4. List unstated assumptions.
5. Test each assumption for load-bearing importance and evidence quality.
6. Look for contradictions between the plan, source evidence, constraints, dates, code, and operating reality.
7. Call out the single most dangerous assumption at the top.

## Ratings

Load-bearing:

- `critical`: if false, the plan fails or becomes unsafe.
- `high`: if false, the plan needs major rework.
- `medium`: if false, scope, timing, or impact changes materially.
- `low`: if false, the plan mostly survives.

Evidence:

- `strong`: supported by source, code, data, or current external evidence.
- `partial`: some support exists but gaps remain.
- `weak`: mostly asserted or inferred.
- `none`: no real evidence found.

## Output Format

```markdown
# Assumption Check

## Most Dangerous Assumption
- Assumption:
- Why it is dangerous:
- Load-bearing: critical | high | medium | low
- Evidence: strong | partial | weak | none
- What would disprove it:

## Assumptions
### 1. Plain assumption statement
- Load-bearing:
- Evidence:
- Source or gap:
- Failure mode if false:
- Verification needed:

## Contradictions
- ...

## Missing Evidence
- ...

## Three Risk-Reducing Questions
1. ...
2. ...
3. ...
```

If no serious issue is found, say that plainly, but still list residual assumptions and evidence limits. Do not pad with compliments.

## Source Rule

When sources or code are available, check claims against them. Internal consistency is not enough. If current external facts matter, perform current-info lookup and cite the date and source.
