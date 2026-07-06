# Torben Weekly Behavior Audit Runbook

The weekly behavior audit reviews Torben's work surfaces for patterns worth
preserving as skills or repo-local runbook updates. It is a learning and
efficiency loop, not an execution loop.

## Inputs

The audit may inspect redacted metadata and compact artifacts from:

- finance radar cards
- EA email/calendar decisions
- article and GTM drafts
- QA findings and testing runbooks
- delegation closeouts and operating-map entries
- shipped artifacts and stakeholder updates

Do not include raw email bodies, calendar descriptions, portfolio secrets,
client-private material, credentials, or token contents in the audit artifact.

## Extraction Bar

A candidate must be all three:

- recurring: likely to happen again
- non-obvious: a fresh session would not simply derive it
- codifiable: can become a procedure, checklist, script, guardrail, skill, or
  runbook entry

Every accepted candidate must include a validation plan. Most weeks should be
allowed to return `nothing_worth_extracting`.

## Knowledge Split

Global reusable behavior can become a skill candidate.

Project-specific selectors, routes, test accounts, seed data, cleanup quirks,
client details, or repo facts must become repo-local runbook updates instead of
global skills.

## Artifacts

The runtime writes:

- `state/torben-weekly-behavior-audit-latest.json`
- `state/torben-weekly-behavior-audit-latest.txt`

Required fields:

- `source_manifest`
- `redaction_posture`
- `recurring_patterns_count`
- `rejected_patterns_count`
- `proposed_skill_count`
- `proposed_runbook_update_count`
- `review_status`
- `candidates`
- `rejected_patterns`
- `live_installs=0`
- `external_mutations=0`

## Canary Commands

Run from `/Users/ericfreeman/.hermes/hermes-agent` with a fixture:

```bash
HERMES_HOME=/Users/ericfreeman/.hermes/profiles/torben \
TORBEN_WEEKLY_BEHAVIOR_AUDIT_FIXTURE=/tmp/weekly-behavior-audit-fixture.json \
UV_PROJECT_ENVIRONMENT=venv uv run --extra dev python \
  profiles/torben/scripts/torben_weekly_behavior_audit.py
```

Expected:

- accepted candidates have `recurring=true`, `non_obvious=true`,
  `codifiable=true`, and `validation_plan`.
- accepted candidates have `live_installed=false`.
- one-off or weak patterns are rejected.
- no external mutations occur.

Focused tests:

```bash
UV_PROJECT_ENVIRONMENT=venv uv run --extra dev python -m pytest \
  tests/test_torben_weekly_behavior_audit.py -q
```
