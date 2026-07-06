---
name: brain-dump-processor
description: Process messy multi-topic input into cleanly separated, evaluated ideas. Use when Eric shares a voice memo transcript, rambling notes, a brain dump, pasted unstructured thinking, or says "process this", "brain dump", "voice memo", "turn this into ideas", "extract the ideas", or asks Torben/Hermes to file messy thinking into dated notes.
---

# Brain Dump Processor

## Purpose

Turn messy multi-topic input into distinct, evaluated idea notes that can become future work items, runbooks, product workflow changes, or founder/operator decisions.

Default filing destination: `HERMES_HOME/notes/brain-dumps/`

If `HERMES_HOME` is not explicit, use the active profile home. For Torben on this host, that is normally `/Users/ericfreeman/.hermes/profiles/torben/notes/brain-dumps/`.

Default file format: one dated Markdown file per processed dump, named `YYYY-MM-DD-HHMM-brief-slug.md`.

## Before Processing

If either of these is missing, ask before writing files:

- Filing destination: default to `HERMES_HOME/notes/brain-dumps/` only after confirming no workflow-specific destination was supplied.
- Evaluation domains: default to Torben, product workflow strategy, runbooks, and founder/operator ideas.

If both are known, proceed without asking.

## Workflow

1. Preserve the raw dump as source context in the note. Clean obvious transcription artifacts, but do not rewrite meaning.
2. Split the dump into genuinely distinct ideas. Do not summarize the whole dump into one mushy theme.
3. Evaluate each idea independently using the domain criteria below.
4. Flag contradictions, tension, or changed assumptions within the same dump.
5. File the result as a dated Markdown note in the destination folder.
6. Reply with the file path and the top ideas or decisions, not the full note unless Eric asks.

## Distinct-Idea Rule

Create separate ideas when any of these differ:

- Different intended outcome.
- Different user, buyer, operator, or system affected.
- Different implementation surface, such as Torben behavior, product workflow, runbook, ticketing, cron, agent prompt, or validation gate.
- Different risk, blocker, or decision needed.
- One thought is strategic and another is an execution step.

Merge only when two fragments are truly the same idea repeated with different wording.

## Per-Idea Format

Use this exact section shape for each idea:

```markdown
### Idea N: Short Name

**Idea:** One sentence.

**Context:** What Eric was circling around, including relevant constraints or examples.

**Assessment:** Worth pursuing / Maybe / Not now. Explain honestly why, including leverage, urgency, risk, and whether it fits current priorities.

**Contradictions Or Tensions:** Note conflicts with another statement in the same dump, or write `None found`.

**Suggested Next Step:** One concrete action. Prefer a test, runbook, ticket, scope doc, decision question, or small implementation slice.
```

## Evaluation Criteria

Favor ideas that:

- Make Torben more reliable, actionable, or aligned with Eric's operating model.
- Improve product workflow strategy with a clearer loop, forcing function, or decision surface.
- Produce reusable runbooks or flows that reduce repeated manual reasoning.
- Help founder/operator execution by clarifying priorities, buyer/user value, delegation, or the next decision.
- Can be validated with a concrete artifact, canary, test, or observable behavior.

Downgrade ideas that:

- Are broad vibes without a forcing function.
- Create another parallel system instead of improving an existing loop.
- Depend on ambiguous ownership, hidden manual steps, or unbounded agent judgment.
- Add automation before the approval boundary, validation gate, or rollback path is clear.
- Sound useful but do not name the next decision or action.

## Contradiction Handling

Flag contradictions inside the same dump. Look for:

- "I want this automated" versus "keep approval gated."
- "This should be simple" versus a proposed workflow with many moving parts.
- "Do not add entropy" versus a new tool, profile, prompt, or process that duplicates existing behavior.
- "We need signal" versus a proposal that creates more reports without an action threshold.
- A goal that changes halfway through the dump.

Do not over-police normal exploration. A tension is useful when it affects execution, scope, safety, or priority.

## Note Template

Every filed note should use this top-level shape:

```markdown
# Brain Dump - YYYY-MM-DD HH:MM

## Source

- Input type: voice transcript | brain dump | notes | unknown
- Processed at: ISO-8601 timestamp
- Filing destination: path
- Evaluation domains: Torben, product workflow strategy, runbooks, founder/operator ideas
- Source id: optional workflow/transcript/tool id

## Raw Dump

> Preserve the original text here. If long, keep it readable with paragraphs.

## Extracted Ideas

### Idea 1: ...

## Cross-Dump Summary

- Highest leverage idea:
- Fastest next step:
- Defer or discard:
- Open questions:
```

## Filing Rules

- Create the destination folder if it does not exist.
- Use local time for filenames.
- Slug from the most important idea, lower-case words joined with hyphens.
- If the note comes from a future tool or workflow, preserve any provided source id, transcript id, or workflow id in the `Source` section.
- Never store secrets, tokens, or private credentials from a dump. Replace them with `[REDACTED]`.
- If the dump asks for external mutation, split the idea from the mutation approval. Do not send email, change calendars, archive/delete Gmail, post, trade, or mutate providers merely because a brain dump suggested it.

## Chat Response

After filing, keep the chat response short:

- File path.
- Number of ideas extracted.
- Highest leverage idea.
- The next action Eric should take.

If Eric only wants the processed output in chat and explicitly says not to file it, provide the same structure without writing a note.
