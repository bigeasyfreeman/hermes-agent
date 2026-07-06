---
name: visible-delegation
description: Delegate work to another agent session visibly through named tmux sessions, with supervisor monitoring and independent verification. Use when Eric asks to delegate, run work in parallel, hand off to another agent, or supervise a child agent session.
---

# Visible Delegation

## Host Preflight

Before using this skill, verify:

- `tmux` is installed.
- The delegate agent CLI is installed.
- Eric has confirmed which agent CLI to use for delegate sessions.

Known Torben host preflight:

- `tmux` was installed with Homebrew during setup.
- `codex` is available at `/opt/homebrew/bin/codex`.
- `opencode` is available at `/opt/homebrew/bin/opencode`.
- `claude` and `kimi` were not found on PATH during setup.

If Eric has not chosen the delegate CLI for this task, ask.

## Launch Procedure

1. Build a self-contained goal prompt. Use `goal-prompt-generator` if available.
2. Create a named tmux session:

```bash
tmux new-session -d -s <safe-session-name> -c <repo-or-workdir>
```

3. Start the delegate agent in that session with the goal prompt.
4. Tell Eric how to watch:

```bash
tmux attach -t <safe-session-name>
```

5. Record the session name, workdir, objective, and verification gates.

## Session Naming

Use names like:

- `delegate-<repo>-<short-task>`
- `lane-<short-purpose>`

Avoid vague names like `agent1`.

## Monitoring Rules

Check at sensible intervals based on task length. Intervene when:

- the delegate loops on the same failure,
- scope drifts beyond the goal prompt,
- destructive commands appear without approval,
- secrets or token contents are being printed,
- the delegate claims completion without running gates,
- the session stalls on a question.

Be patient when:

- tests are still running,
- dependencies are installing,
- the agent is reading relevant files,
- a long but bounded command is progressing.

## Results Protocol

When the delegate claims completion:

1. Inspect the tmux output.
2. Inspect the worktree or artifacts.
3. Run the verification gates yourself.
4. Only report success if the gates pass or the known external blocker is clearly documented.
5. If verification fails, either send a narrow correction to the delegate or take over.

## Cleanup

Close sessions when done:

```bash
tmux kill-session -t <session-name>
```

Do not abandon idle delegate sessions. If a session must remain open, state why and how Eric can attach.
