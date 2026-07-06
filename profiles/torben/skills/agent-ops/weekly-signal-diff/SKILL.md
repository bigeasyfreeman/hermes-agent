---
name: weekly-signal-diff
description: Compare a defined weekly signal input set against the previous run and report only meaningful changes. Use when Eric asks for a weekly signal diff, signal review, changed assumptions, dead threads, emerging patterns, or wants a baseline/diff across notes, folders, project state, or topics.
---

# Weekly Signal Diff

## Purpose

Compare configured inputs against the last recorded state and report the meaningful deltas: new signals, shifted assumptions, dead threads, and emerging patterns. This is a diffing skill, not a re-summarization skill.

## First-Run Interview

Before the first real run, ask Eric for:

- Inputs to watch: folders, specific notes files, project state files, searches, topics, trackers, or repo artifacts.
- What counts as meaningful in this workflow: examples of signal, noise, stale threads, assumption shifts, and threshold for surfacing.
- Report destination: chat only, a file path, Signal-facing summary, or a profile note.

If any of these are unknown, ask and stop. Do not invent watched inputs.

## State File

Maintain state at:

`HERMES_HOME/state/weekly-signal-diff/state.json`

If `HERMES_HOME` is not explicit, use the active Hermes profile home. For Torben this is normally `/Users/ericfreeman/.hermes/profiles/torben`.

The state file must include:

- `version`
- `configured_at`
- `last_run_at`
- `inputs`: id, type, path/query/topic, check method, meaning threshold
- `observations_by_input`: hashes, timestamps, counts, extracted claims, open threads, assumptions, and source pointers
- `reported_changes`: previous reported change ids to prevent repeats

Do not store secrets, tokens, private credentials, or full sensitive payloads. Store source pointers and compact observations.

## Input Checks

Each input must define how to check it:

- `folder`: list changed files since last run, inspect relevant changed files, store file hashes and extracted signals.
- `file`: hash file, compare key sections, store assumption/thread/signal observations.
- `search`: run the configured local search query, record matching source ids and extracted claims.
- `project_state`: read explicit state artifacts, compare status, blockers, shipped items, counters, and decision changes.
- `topic`: search configured corpora for the topic, compare new evidence and changed framing.

If an input is inaccessible, report it as degraded with the path/query and continue with other inputs.

## Baseline Run

When no prior state exists:

1. Read the configured inputs.
2. Record the baseline observations in the state file.
3. Report `Baseline recorded`, not a fake diff.
4. Tell Eric exactly which inputs were recorded and what observation types were captured.

## Diff Run

On later runs:

1. Load the previous state.
2. Re-check each configured input.
3. Compare observations, not just summaries.
4. Rank changes by importance across all sources.
5. Update the state only after the diff report is produced.

Importance ordering:

1. Changes that alter an active decision or plan.
2. New signal with a clear next action.
3. Assumption shifts or contradictions.
4. Threads that died, stalled, or became irrelevant.
5. Emerging patterns across sources.
6. Low-risk context changes.

## Output Format

Use this shape:

```markdown
# Weekly Signal Diff - YYYY-MM-DD

## Most Important Change
- Change:
- Why it matters:
- Evidence:
- Suggested action:

## Meaningful Changes
### 1. Short title
- Type: new signal | shifted assumption | dead thread | emerging pattern | blocker | status change
- Importance: high | medium | low
- Evidence:
- Previous state:
- Current state:
- What to do:

## Quiet Areas
- Inputs checked with no meaningful change:

## Follow-Ups
1. ...
```

Suggest at most three follow-ups. If there are none, write `No follow-ups suggested`.

## Quiet Week Rule

No-change is a valid result. If nothing meaningful changed, answer briefly:

```markdown
# Weekly Signal Diff - YYYY-MM-DD

No meaningful changes.

Checked: input-a, input-b, input-c.
State updated: path/to/state.json.
```

Never pad a quiet week.
