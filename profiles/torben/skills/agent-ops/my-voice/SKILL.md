---
name: my-voice
description: Write, rewrite, or review text in Eric's authentic voice across contexts, using a calibrated register model rather than a generic tone preset. Use whenever Eric asks for copy, email, posts, documentation, edits, tone review, or writing "in my voice".
---

# My Voice

## Calibration Status

This skill is not fully calibrated until Eric provides 5-10 real writing samples and approves the voice model. Until then, do not claim certainty about Eric's voice. Use only known guardrails and ask for samples when voice fidelity matters.

Known provisional guardrails from existing Torben operating instructions:

- Be tight, direct, concrete, and practical.
- Avoid padded empathy, generic polish, corporate filler, and AI-sounding openers.
- Prefer candid, specific phrasing over smooth marketing language.
- For technical content, accuracy beats voice. Never bend facts to sound like Eric.

## First-Run Interview

Ask Eric for 5-10 real writing samples across different contexts:

- emails,
- posts,
- documentation,
- casual messages,
- technical explanations,
- high-stakes stakeholder writing.

For each sample, ask for audience and context if not obvious.

## Analysis Before Finalization

Analyze the samples and propose:

1. Distinct registers, such as directive, relational, analytical, business, technical, public-post, or casual.
2. What distinguishes each register.
3. Sentence-level patterns Eric actually uses.
4. Anti-patterns: words, openers, constructions, and AI-prose tells to avoid.
5. Rules for choosing a register based on audience and stakes.

Show the analysis to Eric and ask for approval or corrections before treating it as the final model.

## Skill Update Rule

After Eric approves the model, update this skill or add a referenced voice model file so future sessions do not re-derive it. Do not silently finalize a voice model without approval.

## Required Final Model Shape

When calibrated, include:

```markdown
## Register Model

### Register Name
- Use when:
- Distinguishing traits:
- Sentence patterns:
- One short sample:

## Anti-Patterns
- Never use:
- Avoid openers:
- Avoid constructions:
- AI tells to remove:

## Register Selection
- Audience/stakes rule:
```

## Writing Workflow

1. Identify audience, stakes, and desired action.
2. Choose the register. If unclear, ask.
3. Preserve factual accuracy and operational constraints.
4. Draft in Eric's voice without over-stylizing.
5. Remove AI tells: filler transitions, generic praise, overbalanced framing, empty empathy, vague intensifiers, and padded setup.
6. For technical content, verify facts before optimizing voice.

## Review Workflow

When reviewing existing text:

- Mark what sounds unlike Eric.
- Rewrite the smallest useful section.
- Explain the voice delta in concrete terms.
- Do not over-polish if the roughness is part of the register.
