# Hermes Loop Budget

## Defaults
- Level: L1/L2.
- High-cadence autonomous loops: disabled unless separately approved.
- Public actions, live finance, and destructive EA mutations: approval-gated.

## Cost Estimates
| Pattern | L1 Realistic Tokens/Day | Decision |
| --- | ---: | --- |
| daily-triage | 276000 | too high at 12/day; keep low-cadence/manual |
| changelog-drafter | 17000 | acceptable when human-triggered |
| issue-triage | 165600 | too high at 12/day; slow cadence or tighten scope |
| post-merge-cleanup | 76000 | acceptable at low cadence with early exit |
| loopy-memory-task-review | local file diff only | acceptable at end of task when entries are genuinely reusable |
| loopy-memory-weekly-review | local file diff only | acceptable weekly; backs up first and does not call an LLM |

## Kill Switch
Pause the relevant Hermes cron, record the reason in `loop-run-log.md`, and do not resume until the owner confirms the cost or safety issue is resolved.
