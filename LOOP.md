# Hermes Stack Loop Contract

## Scope
Hermes is the live Torben operating surface for RTK infrastructure, Safe Skill Factory governance, finance radar delivery, GTM research, EA work, and handoff/changelog drafting. All loops start at L1/L2 and remain approval-gated.

## Loops
| Loop | Cadence | Output | Gate | Canary |
| --- | --- | --- | --- | --- |
| RTK Infra Loop | On install/change | RTK rewrite proof and rollback notes | No Caveman, no global aliases, fail-open hook | `rtk gain`, `rtk rewrite "git status"`, `rtk git status` |
| Safe Skill Factory Loop | On skill capture | Staged `SKILL.md` plus validation proof | Exact confirm, no `plugin.py`, no failed validation | fake `HERMES_HOME` plugin and handler canary |
| Torben Finance Loop | Every 30m and on demand | `torben-finance-radar-latest.json` and optional FIN card | Stage-only; broker/order counters must stay zero | `hermes -p torben cron run torben-finance-radar` |
| Torben GTM Loop | Scheduled radar and engagement runs | Staged opportunity/reply/content artifacts plus automation policy decision | Auto-surface recommendations allowed; no post/reply/schedule/send without explicit approval; 45m radar delivery cooldown suppresses back-to-back cards | `torben-gtm-radar`, `torben-gtm-engagement-radar` |
| Torben EA Loop | Morning, 5m watches, Gmail pull | Brief/prep/alignment artifacts plus automation policy decision | Auto-surface recommendations and relationship-learning questions allowed; no email/calendar mutation without explicit approval or approved policy | morning brief, calendar watchdog, meeting prep, Gmail pubsub, `torben_automation_policy_verify.py` |
| Handoff / Changelog Draft Loop | On release or goal close | `docs/goals/*handoff.md` and run log entries | Human review before external publication | final canary suite plus mutation counters |
| Torben Loopy Memory Loop | End of task, weekly review when scheduled | Tagged entries in `~/.hermes/profiles/torben/memories/MEMORY.md` plus dated backups | Profile memory only, no secrets, dry-run unless applied, mark stale before delete | `torben_memory_loop.py task-review --json`, `torben_memory_loop.py weekly-review --json` |

## Safety Gates
- Auto-merge is disabled. Human review remains required for public repo changes.
- Finance live trading is disabled: do not set `RATATOSK_LIVE_TRADING=true` or `ROBINHOOD_LIVE=true`.
- Broker orders, order cancellation, halt clearing, options, margin, shorts, and risk-cap widening require explicit separate approval.
- GTM public posts, replies, schedules, sends, and social mutations require explicit separate approval.
- GTM recommendations and drafts may be auto-invoked only under `profiles/torben/config/torben-automation-policy.yaml`; public mutations require account/content/risk allowlists, approval mode, rollback path, and audit log path.
- EA email sends/deletes/archives and calendar creates/updates/reschedules require explicit approval unless an existing approved policy explicitly allows the action.
- EA recommendations and relationship-learning questions may be auto-surfaced; acting on learned relationships requires Eric's answer or a trusted source.
- Finance research refreshes and paper-canary recommendations may be auto-invoked; live orders remain blocked without a scoped live-trading policy, mandate, kill switch, guard, reconciliation, and audit log.
- Every production-facing artifact must include mutation counters or an explicit degraded reason.
- Memory loops may only edit the active profile's `memories/MEMORY.md`; legacy untagged entries are preserved, and managed entries must carry `trust`, `date`, `source`, and `status`.
- A green unit test, lint result, or audit score is not completion proof without runtime canaries and artifact paths.

## Budget
- Default level: L1/L2 low-cadence loops only.
- Daily triage and issue-triage estimates exceed suggested caps at high frequency; keep them manual or low-cadence until separately approved.
- Kill switch: disable or pause the relevant Hermes cron before repeated expensive runs, then document the pause and owner in `loop-run-log.md`.
- RTK may compress command output, but uncompressed artifact paths must remain inspectable.

## Worktree Isolation
The live Hermes root was dirty at baseline, so new loop artifacts are intentionally narrow and path-scoped. Future source changes should happen in a branch/worktree with baseline capture before copying go-live artifacts back into the live profile root.

## Verifier Contract
The verifier checks current-state evidence only:
- command output from the required canary,
- JSON artifact counters and approval flags,
- loop run-log entry,
- rollback path,
- explicit unresolved blocker list.

## Rollback
- RTK: `rtk init --agent hermes --uninstall || true`; `brew uninstall rtk`.
- Skill Factory: disable `skill_factory`, remove `~/.hermes/plugins/skill_factory`, remove staged drafts under `~/.hermes/skill-factory/staged/`.
- Loop artifacts: restore or remove `LOOP.md`, `STATE.md`, `loop-budget.md`, `loop-run-log.md`, `patterns/registry.yaml`, and related `.codex/agents` stubs.
- Loopy memory loop: remove `profiles/torben/scripts/torben_memory_loop.py`, remove the Loopy memory tool registrations if no longer wanted, and restore the relevant `memories/backups/MEMORY-*.md` backup before applying any memory rollback.
