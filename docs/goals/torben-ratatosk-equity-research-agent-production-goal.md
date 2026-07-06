# Torben/Ratatosk Equity Research Agent Production Goal

Last updated: 2026-06-27T02:15:07Z.

## Objective

Build Ratatosk Equity Research Agent v0.1 for Torben Finance Radar as a stage-only production loop:

```text
cron -> persisted research episode -> ResearchSignalPacket -> Torben FinanceQualityGate -> FIN card or silence -> paper canary -> blocked live-canary harness
```

The loop must use Ratatosk's existing macro/event, equity mapping, signal QA, memory, and guard concepts. It must not rebuild parallel ingestion/reasoning paths when existing modules are available.

## Non-Negotiable Boundaries

- Do not place live broker orders.
- Do not cancel broker orders.
- Do not clear trading halts or circuit breakers.
- Do not set `RATATOSK_LIVE_TRADING=true` or `ROBINHOOD_LIVE=true`.
- Do not enable options, margin, short execution, or risk-cap widening.
- Do not wake Torben/Signal for generic watchlists, no-data packets, missing thesis, stale data, missing evidence refs, or missing analogs.
- Every stage-only artifact must include zero values for `public_actions_taken`, `external_mutations`, `orders_submitted`, and `broker_orders_submitted`.

## Definition Of Done

1. Ratatosk emits a validated `ResearchSignalPacket` from a persisted research episode.
2. The research cron can run in degraded mode and stays silent with zero mutations.
3. A representative company/sector fixture, including Apple as one example but not as a binary rule, produces one evidence-backed staged research signal or explicit no-trade with reasons.
4. A hot-market-then-dip fixture retrieves historical/regime analogs and emits stage-only hedge/short research-only reasoning or explicit no-trade.
5. Torben finance radar consumes the research packet and produces exactly one `FIN-*` card only for a QA-passed signal.
6. Torben finance radar remains silent for degraded/no-data/no-thesis/stale/missing-analog packets.
7. A paper canary from a persisted research signal writes a real Ratatosk paper position/trade-log artifact.
8. The live-canary harness refuses to place unless exact approval, broker readiness, live flags, halt/breaker state, and pre-trade guard all pass.
9. Production proof includes actual `hermes -p torben cron run torben-finance-radar`, actual Torben latest JSON/TXT artifacts, and `hermes -p torben cron run torben-live-profile-verify`.
10. All mutation counters remain zero for every non-live canary.
11. A handoff artifact records current cutline, files changed, tests run, canary artifacts, runtime proof, blockers, and next commands.

## Current Handoff

Use `docs/goals/torben-ratatosk-equity-research-agent-production-handoff.md` for current proof, artifact paths, and remaining blocked-live state.
