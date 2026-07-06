---
name: session-operating-map
description: Set up and maintain a repo-local operating map for multiple parallel agent sessions, lanes, blockers, and decisions. Use when Eric starts parallel workstreams, asks what is in flight, asks for coordination, or a new session joins an active multi-agent project.
---

# Session Operating Map

## Map Location

Default to `docs/operating-map.md` in the repo root unless the repo already has an operating map convention.

## Read-First Rule

Any session joining the project reads the operating map before starting work. If no map exists and parallel work is starting, create it.

## Map Structure

```markdown
# Operating Map

Last updated: YYYY-MM-DD HH:MM

## Active Lanes

### lane-name
- Objective:
- Owning session:
- Current state: not-started | active | blocked | handoff | verifying
- Blockers:
- Allowed scope:
- Do not touch:
- Next checkpoint:

## Decisions
- YYYY-MM-DD - Decision - Rationale - Owner

## Done
- lane-name - one-line outcome - artifact/PR/path
```

## Lane Discipline

- One lane per concern.
- Name lanes by purpose, not agent number.
- Keep ownership explicit.
- Do not let two lanes edit the same surface without a stated handoff.

## Update Rules

Update a lane when its state meaningfully changes:

- start,
- block,
- handoff,
- verifying,
- done.

Do not use the map as a journal. Keep it current and concise.

## Archive Rules

When a lane finishes:

1. Move it to `Done`.
2. Keep one-line outcome and artifact path.
3. Promote durable lessons into project docs, runbooks, or skills.
4. Remove stale blockers from active view.

## Current Project Setup

When asked to set up the current project:

1. Identify repo root.
2. Read existing plans, goal docs, open runbooks, and dirty worktree state.
3. Populate active lanes from actual in-flight work only.
4. Mark uncertainty instead of inventing owners or state.
