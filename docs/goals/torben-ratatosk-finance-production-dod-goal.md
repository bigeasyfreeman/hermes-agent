# Torben/Ratatosk Finance Radar Production Definition Of Done

Last refreshed: 2026-06-26 15:48 EDT / 2026-06-26T19:48:00Z.

## Objective

Productionize the Torben-facing finance radar so it converges on useful, evidence-backed `FIN-*` review cards without creating broker clutter, generic watchlists, or false live-trading confidence.

This goal is stage-only by default, but it must include a real execution proof. The required canary is an evidence-backed signal that becomes either a Ratatosk paper position/trade record or a reconciled broker position. A new live broker order is allowed only if Eric gives a separate explicit canary approval after the mandate, consent, halt, kill-switch, and pre-trade guard gates pass.

## Current Cutline

Repo/runtime facts verified on 2026-06-26:

- Ratatosk has implemented equity data/signal components: `RobinhoodConnector.get_equity_quotes`, `EarningsScanner`, `OptionsAnalyzer`, `generate_equity_signal`, `run_equity_scan`, `run_equity_full_pipeline`, `skills/equity-scan`, and `state/equity-watchlist.json`.
- The existing Torben finance cron still calls `scripts/robinhood_v01_cron_tick.py --run-llm`; that path mints a bounded LLM run but does not provide live market, broker, option-chain, news, or account context to the model.
- A live `run_equity_scan()` probe returned no markets, no signals, and no earnings because Robinhood authentication failed with `<urlopen error [Errno 61] Connection refused>`.
- Import probe: `robin_stocks=True`, `yfinance=False` in Ratatosk's venv. Package presence is no longer the first blocker; deterministic live auth/data-source proof is.
- Targeted Ratatosk validation passed: `106 passed` across Robinhood connector, earnings scanner, options analyzer, equity signal, pipeline, equity full pipeline, and Robinhood v0.1 tests.
- Targeted Hermes validation passed: `168 passed, 2 skipped` across Torben GTM reply routing, platform base handling, and Torben finance radar tests.
- The gateway `AttributeError: 'dict' object has no attribute 'replace'` is a return-contract bug: a Torben shortcut returns a dict to the platform adapter, which expects text before media extraction.

## External Control Baseline

The production bar should track the same control families expected for automated trading systems:

- Pre-trade financial/risk controls and supervisory procedures: 17 CFR 240.15c3-5, SEC Market Access Rule.
  https://www.ecfr.gov/current/title-17/chapter-II/part-240/subject-group-ECFRc8401dcba174f73/section-240.15c3-5
- Algorithm strategy governance, testing, supervision, and kill-switch expectations: FINRA Regulatory Notice 15-09.
  https://www.finra.org/rules-guidance/notices/15-09
- Systems capacity, integrity, monitoring, incident response, and change-control posture: SEC Regulation SCI FAQ.
  https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/responses-frequently-asked-questions-concerning-regulation-sci

These references do not require Ratatosk to become a broker-dealer system. They are the practical engineering standard for anything that can influence broker actions.

## Non-Negotiable Boundaries

- No live broker order placement, cancellation, option execution, margin, shorting, 0DTE, or risk-cap widening unless Eric separately approves a tiny live canary and all live-finance gates pass.
- Do not clear `state/trading-halt.json`, `state/circuit-breaker.json`, or equivalent halt state.
- Do not set `RATATOSK_LIVE_TRADING=true` or `ROBINHOOD_LIVE=true`.
- No finance Signal wake from generic no-data watchlists such as SPY/QQQ with no thesis, no source refs, and no market packet.
- Torben remains the visible Signal operator. Ratatosk stays hidden/local and emits machine-readable evidence.
- Every visible finance item must have a stable `FIN-*` handle and explicit mutation status.
- `external_mutations=0`, `orders_submitted=0`, and `broker_orders_submitted=0` must remain true for stage-only output.

## Production Definition Of Done

The goal is done when all of these are true:

1. Gateway return contract is fixed.
   - Torben shortcut flows return plain text or a supported reply object to platform adapters.
   - Regression coverage proves dict payloads cannot reach `BasePlatformAdapter.extract_media`.
   - Live Signal test no longer produces the `dict.replace` error.

2. Finance Radar has a quality gate.
   - If Ratatosk output says `unknown_research_only_no_live_market_data`, has no live data packet, or lacks thesis/evidence refs, Torben records an artifact and stays silent.
   - Generic candidates cannot wake the user only because they score above `0.70`.
   - Suppressed payloads include `silent_reason`, `quality_gate_version`, and the failed criteria.

3. Torben consumes the real equity scan path or explicitly degrades.
   - Preferred production source is `run_equity_scan()` / `state/market-cache/equity/latest.json`, not the current no-data cron prompt.
   - If Robinhood auth or the data source fails, the finance radar reports degraded state only when actionable, otherwise stays silent.
   - `yfinance` may be a read-only fallback only after it is installed, tested, and marked as non-executable research data.

4. Every surfaced `FIN-*` candidate is evidence-backed.
   - Required fields: symbol, proposed action, thesis, edge, conviction, market-implied probability when available, quote timestamp, data freshness, catalyst/news/earnings refs, risk notes, invalidation condition, recommended review action, and guard result.
   - "No thesis provided" is a hard failure above the review bar.

5. Stage-only safety remains proven.
   - Ratatosk v0.1 validation is green.
   - Finance radar artifacts retain zero public/broker mutations.
   - Tests cover unsafe mutation counts and fail closed.

6. A proper finance canary proves signal-to-position behavior.
   - The canary starts from a non-synthetic signal with live or fixture-equivalent market evidence, thesis, edge, conviction, and risk notes.
   - The signal must produce either a Ratatosk paper trade/position artifact or a reconciled existing broker position.
   - The canary output records signal id, candidate id, order/position id, execution mode, guard result, mutation counters, and reconciliation status.
   - If the canary is paper/simulated, broker mutation counters remain zero.
   - If the canary is live, the artifact must include explicit approval, mandate, consent, halt/kill-switch state, pre-trade guard pass, broker result, reconciliation, and rollback/exit note.

7. Context compaction/handoff is productionized for this loop.
   - Long-running ADLC work writes a handoff artifact with objective, current cutline, dirty files, tests run, blocked gates, pending approvals, and next commands.
   - A resumed agent can continue without rereading the whole thread.

8. Operational proof exists.
   - Targeted unit tests pass.
   - A dry-run/canary demonstrates no wake on no-live-data output.
   - A fixture with a valid equity scan candidate produces exactly one stage-only `FIN-*` card.
   - A proper signal-to-position canary passes and leaves durable artifacts.
   - Torben gateway is supervised by launchd or an equivalent restartable service, not only an ad hoc detached process.

## Task Decomposition

### P0 - Fix Gateway Return Contract

Objective: stop the `dict.replace` crash and prevent future shortcut handlers from leaking structured payloads into platform text processing.

Implementation:

- Unwrap shortcut dicts to `final_response` before returning from the gateway message handler, or make `_maybe_handle_torben_gtm_reply()` return an explicit text reply at the adapter boundary.
- Keep structured payloads only for transcript/audit/logging.
- Add adapter-boundary regression coverage for Torben GTM shortcut replies.

Verification:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest tests/gateway/test_torben_gtm_reply_router.py tests/gateway/test_platform_base.py -q
```

Done when a live or fixture Signal reply cannot trigger `AttributeError: 'dict' object has no attribute 'replace'`.

### P0 - Add Finance Radar Quality Gate

Objective: prevent the exact bad alert class: no-live-data SPY/QQQ watchlists with no thesis.

Implementation:

- Add a `FinanceQualityGate` in `hermes_cli/signal_coo/finance.py`.
- Reject or silence candidates when market regime is unknown/no-live-data, evidence refs are empty, thesis is absent, quote/data freshness is absent, or all risk notes only say research/no data.
- Emit structured suppression metadata in the latest JSON artifact.

Verification:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest tests/test_torben_finance_radar.py tests/test_signal_coo.py -q
```

Done when the historical SPY/QQQ no-data fixture produces `wakeAgent=false` with a useful `silent_reason`.

### P0 - Route Torben Finance To Real Equity Evidence

Objective: stop using the no-data LLM cron prompt as the main production source for finance radar cards.

Implementation:

- Add a Ratatosk command/script entry point that runs `run_equity_scan()` and prints one JSON object with source freshness, errors, markets, signals, and mutation counters.
- Update `profiles/torben/scripts/torben_finance_radar.py` to prefer this evidence packet.
- Retain the Robinhood v0.1 cron-tick path only as a bounded scheduler/control canary, not as a candidate source unless it receives a market context packet.

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_intelligence/test_pipeline.py tests/test_intelligence/test_equity_full_pipeline.py -q

cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest tests/test_torben_finance_radar.py -q
```

Done when Torben can distinguish "valid evidence-backed candidates", "data-source degraded", and "no actionable signal" without waking on placeholder analysis.

### P1 - Prove Or Replace Robinhood Equity Data Auth

Objective: make the data source deterministic enough for production Signal alerts.

Implementation:

- Add a no-secret auth/data readiness probe that checks Robinhood equity quote, positions, earnings, and option-chain availability.
- Record failure kinds without secrets.
- If Robinhood cannot be made deterministic, document and implement a production read-only data source fallback. Prefer official, reliable APIs for production automation; do not use browser scraping for executable signals.

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/robinhood_equity_readiness.py --json
```

Done when auth failure is an explicit degraded gate and cannot produce `FIN-*` candidates.

### P1 - Upgrade Candidate Schema And Rendering

Objective: make surfaced finance cards decision-grade.

Implementation:

- Extend the Ratatosk-to-Torben adapter to map equity signal fields into `FIN-*` cards.
- Require edge, conviction, market-implied probability, catalyst/news refs, live data freshness, risk notes, invalidation, and guard result.
- Deduplicate by signal id, symbol, action, catalyst id, and time horizon.

Verification:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest tests/test_torben_finance_radar.py tests/test_signal_coo.py -q
```

Done when no visible candidate can render as "No thesis provided" or omit evidence.

### P1 - Add End-To-End Signal-To-Position Canary

Objective: prove the finance loop works beyond message shape: a real candidate must become a trade or position artifact.

Implementation:

- Fixture 1: no-live-data Ratatosk output -> artifact only, no wake.
- Fixture 2: data-source auth failure -> degraded artifact, no generic candidate.
- Fixture 3: valid equity scan signal -> exactly one `FIN-*` review card.
- Fixture 4: approved paper canary -> Ratatosk records a paper trade/position with signal id, thesis, edge, guard result, and reconciliation status.
- Fixture 5: unsafe mutation count -> hard failure card and no staged candidate.
- Optional live canary -> only after separate explicit approval and all live-finance gates pass. Use the smallest permitted notional, long-only, no options unless separately authorized, and record broker result plus reconciliation.

Verification:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest tests/test_torben_finance_radar.py -q

cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_intelligence/test_equity_full_pipeline.py tests/test_engine/test_executor_robinhood.py -q
```

Done when all no-data/degraded/unsafe fixtures pass and the signal-to-position canary leaves durable proof. A paper canary is sufficient for default completion; a live canary is sufficient only if it also proves approval, guard pass, broker result, reconciliation, and exit/rollback handling.

### P2 - Productionize Handoff And Compaction For ADLC Runs

Objective: make long engineering loops restartable.

Implementation:

- Add a small handoff writer/command for ADLC loops.
- Include objective, scope, current cutline, dirty files, tests run, runtime probes, unresolved decisions, and next commands.
- Wire this into the goal instructions and optionally into compaction/reset status.

Verification:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest tests/tui_gateway/test_compaction_status.py tests/tui_gateway/test_goal_command.py -q
```

Done when a fresh session can continue this goal from the handoff file without relying on chat history.

### P2 - Fix Gateway Supervision Proof

Objective: avoid relying on a detached gateway process for Torben production behavior.

Implementation:

- Repair launchd supervision or add equivalent restartable service proof.
- Update Torben operating docs with start/stop/status/restart and health checks.

Verification:

```bash
hermes -p torben gateway status
hermes -p torben cron list
```

Done when status proves supervised restart behavior and cron/gateway health is not dependent on a one-off detached process.

### P3 - Tiny Live Finance Canary (Separate Explicit Approval Required)

Do not run a new live broker order by implication. A live canary can be added to this goal only after Eric explicitly approves that specific canary and the execution plan confirms:

- mandate and consent artifacts,
- no circuit breaker/halt,
- broker flags intentionally enabled,
- pre-trade guard pass,
- order review before place,
- reconciliation after order,
- halt on divergence.

If those gates do not pass, the proper production canary is a paper trade/position or a reconciliation against an existing broker position.

## Paste-Ready Goal Prompt

Use this prompt for the next execution goal:

```text
Goal: Productionize the Torben/Ratatosk Finance Radar stage-only operating loop using /Users/ericfreeman/.hermes/hermes-agent/docs/goals/torben-ratatosk-finance-production-dod-goal.md as the definition of done.

Do not enable live trading, clear circuit breakers, place/cancel broker orders, or set live broker env flags unless I separately approve a specific tiny live canary after the gates pass. Keep Torben as the only visible Signal operator. The default canary must still prove signal-to-position behavior through a Ratatosk paper trade/position or a reconciled existing broker position.

Start with a current-state audit against the goal document. Then implement the P0 items first: gateway return-contract fix, finance quality gate, and routing Torben finance to real Ratatosk equity evidence or explicit degraded state. Preserve existing dirty work unless it is part of the task. Run the listed verifiers and provide evidence that no-live-data outputs stay silent, valid evidence-backed candidates stage exactly one FIN card, and all mutation counters remain zero.
```
