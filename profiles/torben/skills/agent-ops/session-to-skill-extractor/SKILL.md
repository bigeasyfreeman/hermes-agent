---
name: session-to-skill-extractor
description: At the end of substantial work, decide whether any solved pattern is worth preserving as a new skill or an update to an existing one, and draft it for review. Use when Eric says wrap up, asks whether anything is worth keeping, or a non-trivial session ends.
---

# Session To Skill Extractor

## High Bar

Most sessions yield nothing. `Nothing worth extracting` is a good answer.

Extract only when the pattern is:

- recurring: Eric will plausibly need it again,
- non-obvious: a fresh session would not just derive it,
- codifiable: it can be written as a procedure, checklist, script, or guardrail.

## Workflow

1. Identify the session's solved problems and repeated moves.
2. Separate project-specific facts from reusable process.
3. Search the existing skill library first.
4. If an existing skill covers 80 percent of the pattern, propose an update instead of a new skill.
5. If a new skill is justified, draft it in the standard skill format with trigger conditions.
6. Put drafts somewhere for Eric's review. Never silently install into the live skill library unless Eric asked for installation.

## Sanitization Rule

Generalize the pattern. Strip project, client, secret, token, account, and private operational specifics. Keep project-specific facts in repo-local runbooks or docs.

## Output Format

```markdown
# Skill Extraction Review

## Verdict
new skill | update existing skill | nothing worth extracting

## Reasoning
- Recurring:
- Non-obvious:
- Codifiable:

## Existing Skill Check
- Checked:
- Overlap:

## Proposed Draft Or Update
- Name:
- Trigger:
- What it would preserve:
- Review path:
```

## Draft Rules

- Include YAML frontmatter with `name` and `description`.
- Put trigger conditions in the description.
- Keep SKILL.md concise.
- Include scripts or references only when they remove real repeated work.

## End-Of-Session Test

When testing on the current session, evaluate the actual setup work. It may be better captured as a runbook entry or operating-map note instead of a skill.
