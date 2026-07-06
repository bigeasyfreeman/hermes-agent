# Torben Finance Stage-Only Runbook

Torben coordinates finance through Ratatosk, but Torben remains the only
Signal-facing operator.

## Current Mode

Finance is stage-only.

`profiles/torben/scripts/torben_finance_radar.py` calls Ratatosk's equity
research/radar path and adapts the result into Torben `FIN-*` review actions.
The radar is a broad opportunity radar, not a blue-chip watchlist. It should
scan existing holdings, user watchlists, small/mid-cap catalysts,
underfollowed company events, sector dislocations, unusual volume/news deltas,
earnings/revenue inflections, product or technical catalysts, and sourced
insider/institutional-flow signals where available.

The script may run Ratatosk's bounded no-tools LLM analysis when evidence
crosses the trigger bar. The LLM receives market-research context and can
produce watchlist/candidate objects, but it does not receive broker order tools.
Quiet repeated scans must write no-change artifacts without padded summaries.

Eric resolved `TBC-DECIDE-LIVE-FINANCE` on 2026-06-26 as a testing-only tiny
live finance canary. That approval does not override Ratatosk's circuit breaker,
trading halt, pre-trade guard, consent, or reconciliation requirements.

## Silent Success

The finance radar stays silent when:

- no Robinhood v0.1 tick is due.
- Ratatosk returns no candidates.
- candidates are below `TORBEN_FINANCE_MIN_SCORE` (default `0.70`).
- the same candidate fingerprint was already delivered.
- a scheduled scan has no meaningful broad-universe delta.

The latest local artifacts are:

- `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json`
- `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.txt`
- `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-state.json`

## Action Boundary

When a candidate crosses the review bar, Torben stages a `FIN-*` action with:

- `mutation_type=broker_order_candidate`
- `mutation_status=stage_only_not_ordered`
- `provider=ratatosk_robinhood_v01`
- `order_tools_available=false`
- `orders_submitted=0`
- `external_mutations=0`
- `execution_blocked_until` including `TBC-DECIDE-LIVE-FINANCE`
- `scan_window`
- `opportunity_universe_version`
- `candidate_class_counts`
- `underfollowed_signal_count`
- `llm_triggered` or `no_llm_reason`

The visible Signal text must say that no order was placed, cancelled, modified,
or approved.

## Scan Cadence

The default scheduled shape is a few market-day scans, not a constant noisy
report:

- market open
- midday
- late afternoon

The sanitized cron snapshot uses `35 9,12,15 * * 1-5`. Runtime deployments may
keep a different schedule temporarily, but the artifact must expose
`scan_windows_count >= 2` or a degraded reason. Notifications remain
actionable-only: no meaningful delta means no Signal wake.

Config knobs:

- `TORBEN_FINANCE_SCAN_WINDOW`
- `TORBEN_FINANCE_SCAN_WINDOWS`
- `TORBEN_FINANCE_OPPORTUNITY_UNIVERSE_VERSION`
- `TORBEN_FINANCE_OPPORTUNITY_UNIVERSE_SCOPE`

## Live Trading Gate

Do not clear the active circuit breaker or trading halt from this runbook.

Live broker execution requires:

- resolved `TBC-DECIDE-LIVE-FINANCE` for a testing-only tiny canary.
- written mandate and consent artifacts.
- configured and healthy Robinhood connector.
- kill switch and circuit breaker allowing execution.
- pre-trade guard pass.
- review-before-order proof.
- reconciliation-after-order proof.
- halt-on-divergence proof.

Current live preflight result:

- `UV_PROJECT_ENVIRONMENT=venv RATATOSK_LIVE_TRADING=true ROBINHOOD_LIVE=true uv run python scripts/robinhood_v01_validate.py --json`
- Result: stage validation ready, `external_mutations=0`, live decision blocked
  by missing matching consent and `Circuit breaker tripped at 43.1% drawdown`.
- Guard-only check with explicit consent and live env gates set still returned
  `allowed=false` because the global halt is active.

## Canary Commands

Run from `/Users/ericfreeman/.hermes/hermes-agent`:

```bash
HERMES_HOME=/Users/ericfreeman/.hermes/profiles/torben \
TORBEN_FINANCE_RADAR_PREVIEW=1 \
TORBEN_FINANCE_RADAR_FORCE_WAKE=1 \
TORBEN_FINANCE_PHASE=postmarket \
UV_PROJECT_ENVIRONMENT=venv uv run --extra dev python \
  profiles/torben/scripts/torben_finance_radar.py
```

Expected:

- `wakeAgent=true`.
- text contains `No order was placed`.
- text names the broad opportunity universe.
- latest JSON has `external_mutations=0`.
- latest JSON has `broker_orders_submitted=0`.
- latest JSON has `scan_window`.
- latest JSON has `opportunity_universe_version`.
- latest JSON has `scan_windows_count >= 2`.
- latest JSON has `quiet_scan_llm_triggered=false`.
- preview mode does not append a durable ledger action.

Run the Ratatosk validator:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/robinhood_v01_validate.py --json
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_robinhood_v01 -q
```

Focused Robinhood executor tests must pass before any live finance gate is
considered resolved.
