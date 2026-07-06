# Torben Delegation And Flywheel Runbook

Use this runbook when a Torben lane splits into parallel work, uses a delegate
agent, or reaches closeout after non-trivial work.

## Delegation Rules

1. Create or update the operating map before delegation.
2. Package the task with a self-contained goal prompt.
3. Launch the delegate in a visible tmux session.
4. Monitor for scope drift, destructive commands, stuck loops, or missing
   verification.
5. When the delegate claims completion, the supervising session reruns the
   verification gates before reporting success.
6. Close the tmux session after results are captured.

Hidden background delegates are not allowed.

## Required Closeout Fields

- lane name
- owning session
- tmux/session ref if delegated
- objective
- definition of done
- verification commands and result
- blocker or done state
- skill/runbook extraction decision

## Skill Extraction Rule

At closeout, evaluate whether the session produced a reusable pattern.

Extract only if it is:

- recurring
- non-obvious
- codifiable

If an existing skill covers most of it, propose an update instead of a new
skill. If the pattern is project-specific, write a repo-local runbook update.

Never silently install a skill into the live library.

## Verification

Focused primitive check:

```bash
~/.hermes/hermes-agent/.venv/bin/hermes -p torben skills list \
  | rg "weekly-signal-diff|session-operating-map|goal-prompt-generator|visible-delegation|session-to-skill-extractor"
```

Expected: every named skill is present.
