---
name: stakeholder-update-email
description: Draft or send short truthful stakeholder update emails after work ships with stakeholder-visible impact. Use when work merges, ships, changes user-facing behavior, affects a stakeholder, or Eric asks for an update email.
---

# Stakeholder Update Email

## First-Run Interview

Before sending or drafting recurring updates, ask:

- Recurring stakeholders and what each cares about.
- Whether to always draft or send directly after explicit confirmation.
- Sending mechanism, such as Resend API, Gmail, or another provider.
- Whether Eric should be CC'd.
- Any stakeholder-specific tone or format constraints.

If send mechanics are unknown, draft only.

## Gate

If nothing stakeholder-visible changed, say so and send nothing.

Stakeholder-visible means a recipient would care about changed behavior, access, timeline, evidence, decision, risk, or next step. Internal refactors usually do not qualify unless they change reliability, security, cost, or delivery date in a way the stakeholder cares about.

## Writing Rules

- Use the recipient's vocabulary, not implementation detail.
- Never call anything done unless it was verified.
- If something shipped partially, say exactly which part shipped.
- Keep it short.
- Do not hide blockers or caveats that affect the stakeholder.
- Do not include sensitive internal details unless appropriate for that stakeholder.

## Format

```text
Subject: [short concrete subject]

Hi [Name],

What changed:
[1-2 sentences]

What it means for you:
[1-2 sentences]

What is next:
[1 sentence]

Best,
Eric
```

Adjust greeting/signoff to Eric's known preference or stakeholder context.

## Send/Draft Mechanics

- Draft by default.
- Sending requires Eric's explicit confirmation in the current turn.
- Before sending, show recipient, cc, subject, body, and provider.
- After sending, verify provider response and report message id or artifact.

## Test/Draft Mode

When asked to test this skill, draft from the most recent shipped work with known evidence. If no recent stakeholder-visible shipped work is available, say so and ask for a target.
