---
name: goal-prompt-generator
description: Turn an implementation plan, task description, or handoff into a bounded, self-contained goal prompt for another autonomous agent session. Use when Eric asks to package work, write a goal prompt, prepare a task for another session, or create an execution contract.
---

# Goal Prompt Generator

## Purpose

Produce a prompt another competent agent can execute with zero conversation context, and that Eric or the supervising agent can verify without re-deriving the plan.

## Required Structure

Every goal prompt must include:

````markdown
# Goal Prompt: Short Name

## Objective
One paragraph describing the concrete outcome.

## Background
Exact context the receiving session needs. Include repo, branch, paths, current state, and relevant decisions.

## Definition Of Done
- [ ] Verifiable statement.
- [ ] Verifiable statement.

## Allowed Changes
- Files/areas that may be modified.

## Do Not Touch
- Files/areas that must not be modified.
- Unrelated local artifacts to leave alone.

## Required Workflow
1. ...

## Verification Gates
```bash
command
```
Expected result:
- ...

## Stop Conditions
- Halt and ask if ...

## Reporting
- Required final evidence and artifacts.
````

## Self-Containment Rule

The receiving session has none of this conversation. Include:

- absolute repo path,
- branch/worktree instructions,
- relevant issue/PR IDs,
- existing artifacts to read first,
- exact validation commands,
- expected outputs or acceptable failure modes,
- approval boundaries.

Do not rely on "as discussed".

## Quality Check

Before delivering, check:

`Could a competent agent with zero context execute this, and could I verify the result without re-deriving the plan?`

If not, revise.

## Constraints

- Keep scope bounded.
- Prefer one shippable slice.
- Name stop conditions clearly.
- Do not include hidden authority to mutate production, send email, trade, post, merge, or delete branches unless Eric explicitly asked for that authority.

## Output

Return the prompt as Markdown ready to save or paste into another session. If Eric asked for a file, write it to the requested path or a repo-root goal doc.
