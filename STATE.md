# Hermes Stack State

## Baseline
- Captured: 2026-06-27.
- Baseline proof directory: `/tmp/hermes-stack-go-live-baseline-20260627T050458`.
- Hermes baseline loop-audit: L0, score 39.
- Torben gateway baseline: launchd-supervised and healthy.
- Torben crons baseline: finance, GTM, Gmail, calendar, meeting prep, and live-profile verification active.
- RTK baseline: not installed before this go-live pass.

## RTK Infra
- Status: installed through Homebrew as `rtk 0.42.4`.
- Hermes integration: `~/.hermes/plugins/rtk-rewrite` enabled in `~/.hermes/config.yaml`.
- Caveman: not installed.
- Global aliases: not added.
- Rollback: `rtk init --agent hermes --uninstall || true`; `brew uninstall rtk`.

## Safe Skill Factory
- Status: enabled user plugin `skill_factory`.
- Command: `/skill-factory`.
- Staging root: `~/.hermes/skill-factory/staged/<slug>/`.
- Active meta-skill: `~/.hermes/skills/meta/skill-factory/SKILL.md`.
- Safety posture: installs only `SKILL.md`; refuses failed validation, missing confirm, staged `plugin.py`, and unconfirmed overwrite.

## Finance
- Status: stage-only / approval-gated.
- Latest artifact: `~/.hermes/profiles/torben/state/torben-finance-radar-latest.json`.
- Required zero counters: `public_actions_taken`, `external_mutations`, `orders_submitted`, `broker_orders_submitted`.
- Ratatosk source: `/Users/ericfreeman/ratatosk/state/equity-research/latest.json`.
- Automation policy: research and paper-canary recommendations may auto-surface; live orders are blocked by `torben-automation-policy.yaml` until a scoped live-trading policy exists.

## GTM
- Status: staged research and engagement only.
- Latest artifacts:
  - `~/.hermes/profiles/torben/state/torben-gtm-radar-latest.json`
  - `~/.hermes/profiles/torben/state/torben-gtm-engagement-radar-latest.json`
  - `~/.hermes/profiles/torben/state/gtm-content-packages/`
- Public action counters required: `posted=0`, `replied=0`, `scheduled=0`, `sent=0`, `public_actions_taken=0`.
- Automation policy: GTM recommendations and drafts may auto-surface; public post/reply/schedule/send remains approval-required. The radar adapter has a 45m delivery cooldown for back-to-back runs.

## EA
- Status: read-only / approval-gated.
- Latest verification artifact: `~/.hermes/profiles/torben/state/torben-live-profile-verify-latest.json`.
- EA loop artifact: `~/.hermes/profiles/torben/state/ea-loop-latest.json`.
- Mutation counters required: `emails_sent`, `emails_deleted`, `emails_archived`, `calendar_events_created`, `calendar_events_updated`, `external_mutations`.
- Automation policy: EA recommendations and relationship-learning questions may auto-surface; sending, archiving/deleting/labeling, and calendar edits require explicit allowlist policy plus approval.

## Automation Policy
- Policy file: `~/.hermes/profiles/torben/config/torben-automation-policy.yaml`.
- Repo snapshot: `profiles/torben/config/torben-automation-policy.yaml`.
- Latest verifier artifact: `~/.hermes/profiles/torben/state/torben-automation-policy-latest.json`.
- Current validation: `status=pass`; GTM recommendation `allowed`; GTM public post `approval_required`; EA recommendations `allowed`; EA mutations `approval_required`; finance research/paper canary `allowed`; finance live order `blocked`.

## Loopy Memory
- Status: implemented as profile-scoped tooling, not live-scheduled by this patch.
- Toolset: `loopy` exposes `loopy_memory_task_review` and `loopy_memory_weekly_review`.
- Profile script: `profiles/torben/scripts/torben_memory_loop.py`.
- Live target path: `~/.hermes/profiles/torben/memories/MEMORY.md`.
- Safety posture: dry-run by default; writes only the active profile memory path; refuses credential-shaped entries; weekly pass backs up first and marks `stale` or `needs-review` without hard-deleting.
- Legacy memory entries remain unmodified unless explicitly migrated later.

## Open Risks
- Hosted/social/broker execution remains intentionally blocked pending explicit human approval.
- The live root had pre-existing dirty source changes; this pass preserves them and narrows new loop artifacts to documented paths.
