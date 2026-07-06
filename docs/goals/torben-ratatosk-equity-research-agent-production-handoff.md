# Torben/Ratatosk Equity Research Agent Production Handoff

Last updated: 2026-06-27T09:01:06Z.

## Verdict

Stage-only production loop is implemented and verified. Ratatosk now uses the
hosted `robinhood-agentic-mcp` server as the production broker-auth/read/review
boundary. Live trading remains intentionally blocked.

Current live blockers:

- The existing `robinhood-agentic-mcp` server is authenticated and ready; raw
  Robinhood username/password credentials are not required for this path.
- Exact approval for `EQ-20260627-AAPL-E78D6F` is expired, unapproved, missing
  `account_number`, missing approver/timestamp, missing risk acknowledgements,
  and not scoped as `one_shot_live_canary`.
- `RATATOSK_LIVE_TRADING=false`.
- `ROBINHOOD_LIVE=false`.
- Ratatosk trading halt and circuit breaker are active in current state.
- Research packet/quote data is stale or fixture-derived; research guard has
  `live_allowed=false`.
- Current market is closed/off-hours, so Agentic MCP quote fallback correctly
  emits `latest_available_market_packet` with no staged candidate.
- Latest-candidate approval generation is intentionally refusing right now:
  latest research has zero candidates and is not a live market packet.
- Unscoped status now explicitly blocks submit readiness with
  `status_not_signal_scoped` and warns that it resolved an older AAPL promotion
  while latest research is `EQ-20260627-DEGRADED`.
- Blocked status no longer emits a copy-pasteable one-shot live-submit command;
  `commands.one_shot_live_submit=null` until exact signal-scoped status reports
  `ready_to_submit=true`.
- The live-submit command itself now also requires a prior matching dry-run MCP
  review artifact, so manually passing `--execute-live-order` cannot skip the
  dry-run authorization step.

## Baseline Captured

Hermes:

- Version: `Hermes Agent v0.17.0 (2026.6.19)`, upstream `9b2af36d`, local `bd601569 (+6 carried commits)`, Python `3.11.15`.
- Torben gateway: `Gateway is supervised by launchd (PID 44755)`.
- Torben cron: `torben-finance-radar` is active, every 30 minutes, no-agent, last run ok; `torben-live-profile-verify` is active every 15 minutes.
- Torben status: Signal configured, gateway running under launchd, 13 active scheduled jobs.
- Latest finance artifact path: `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json`.

Ratatosk readiness:

- `scripts/robinhood_equity_readiness.py --json`: `ready=false`, `failure_kinds=["missing_equity_credentials"]`.
- Import state: `robin_stocks=true`, `yfinance=false`.
- Live flags: `RATATOSK_LIVE_TRADING=false`, `ROBINHOOD_LIVE=false`.

## Implemented Cutline

Ratatosk:

- Added LLM contract: `/Users/ericfreeman/ratatosk/docs/llm-contracts/equity-research-agent.md`.
- Added strict shared schema: `/Users/ericfreeman/ratatosk/src/ratatosk/intelligence/equity_research_schema.py`.
- Added curated regime analog retrieval: `/Users/ericfreeman/ratatosk/src/ratatosk/intelligence/equity_regime_analogs.py`.
- Added seed regimes: `/Users/ericfreeman/ratatosk/state/research/equity-historical-regimes.seed.json`.
- Extended existing `EquityMapper` with company hardware pricing exposure classes; no parallel mapper.
- Added persisted episode runner and cron CLI: `/Users/ericfreeman/ratatosk/src/ratatosk/intelligence/equity_research_agent.py` and `/Users/ericfreeman/ratatosk/scripts/equity_research_signal_cron.py`.
- Upgraded paper canary to accept `--signal-id` for persisted research signals.
- Added blocked live-canary harness: `/Users/ericfreeman/ratatosk/src/ratatosk/equity_live_canary.py` and `/Users/ericfreeman/ratatosk/scripts/equity_live_canary_from_signal.py`.

Hermes/Torben:

- `FinanceQualityGate` consumes `ratatosk_equity_research_agent_v1` packets with `primary_symbol`, nested `market_packet`, `event_refs`, and `historical_analogs`.
- Gate rejects stale packets, missing thesis, missing refs, missing analogs for hedge/short/regime ideas, and candidate-level nonzero mutation counters.
- Torben profile script now prefers `scripts/equity_research_signal_cron.py`, records explicit fallback metadata, and falls back to `scripts/equity_scan_packet.py` when the research cron is degraded/unavailable.
- Live profile script synced: `/Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py`.

## Runtime Proof

### 2026-06-27T02:23Z Live-Profile Drift Fix Verification

Root cause: `torben_live_profile_verify.py` compares every enabled relative cron script in the live Torben profile against the repo snapshot with a byte-for-byte comparison. The reported failure was produced when `/Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py` and `/Users/ericfreeman/.hermes/hermes-agent/profiles/torben/scripts/torben_finance_radar.py` drifted.

Current proof:

- `cmp` between repo snapshot and live profile `torben_finance_radar.py`: exit `0`.
- SHA-256 for both files: `534de3856440e85fbe301f63455d427480c7356ec968618bb3437203e6c531b7`.
- Actual `hermes -p torben cron run torben-live-profile-verify`: succeeded.
- Latest verifier artifact: `/Users/ericfreeman/.hermes/profiles/torben/state/torben-live-profile-verify-latest.json`.
  - `status=pass`.
  - `wakeAgent=false`.
  - `errors=[]`.
  - `warnings=[]`.
  - `torben-finance-radar` check: `exists=true`, `compiles=true`, `last_status=ok`, `last_error=null`, `last_delivery_error=null`, `snapshot_in_sync=true`.
  - Investigation request cleared.

Fresh handoff rerun:

- Company hardware pricing fixture: `EQ-20260627-AAPL-E78D6F`, episode `eq-research-20260627T022148101656Z-company-hardware-pricing`, zero mutations.
- Hot-market-dip fixture: `EQ-20260627-QQQ-A024C2`, episode `eq-research-20260627T022155829081Z-hot-market-dip`, `stage_hedge`, three analogs, zero mutations.
- Live degraded research path: `eq-research-20260627T022204218958Z-live`, `status=data_source_degraded`, `candidate_count=0`, `source_freshness.status=auth_failed`, zero mutations.
- Paper canary from `EQ-20260627-AAPL-E78D6F`: `status=passed`, `reconciliation_status=paper_position_recorded`, position `paper-finance-pos-32569a9bb96d2162`, broker orders `0`.
- Blocked live harness from `EQ-20260627-AAPL-E78D6F`: `status=blocked`; `robinhood-agentic-mcp` broker auth is ready; `$25` AAPL is now represented as a market `dollar_amount` review plan; remaining reasons are approval exactness, `circuit_breaker_active`, fixture/live-allowed guards, `ratatosk_live_trading_disabled`, `robinhood_live_disabled`, and `trading_halt_active`; broker orders `0`.
- Actual `hermes -p torben cron run torben-finance-radar`: succeeded.
- Latest finance artifact remains silent: `wakeAgent=false`, `silent_reason="Ratatosk equity data source is degraded; no FIN card staged"`, `candidate_count=0`, `selected_count=0`, `public_actions_taken=0`, `external_mutations=0`, `orders_submitted=0`, `broker_orders_submitted=0`.

Ratatosk fixture canaries:

- Company hardware pricing:
  - Episode: `/Users/ericfreeman/ratatosk/state/pipeline/equity_research/runs/eq-research-20260627T020836214054Z-company-hardware-pricing`.
  - Signal: `EQ-20260627-AAPL-1FB4B3`.
  - Packet: `status=qa_passed`, `primary_symbol=AAPL`, `proposed_action=stage_long`, mutation counters all zero.
- Hot-market-dip:
  - Episode: `/Users/ericfreeman/ratatosk/state/pipeline/equity_research/runs/eq-research-20260627T020348558151Z-hot-market-dip`.
  - Signal: `EQ-20260627-QQQ-978359`.
  - Packet: `status=qa_passed`, `proposed_action=stage_hedge`, historical analogs present, mutation counters all zero.

Ratatosk degraded canary:

- Latest: `/Users/ericfreeman/ratatosk/state/equity-research/latest.json`.
- Episode: `eq-research-20260627T020900225515Z-live`.
- Status: `data_source_degraded`, `candidate_count=0`, mutation counters all zero.
- Research packet path: `/Users/ericfreeman/ratatosk/state/pipeline/equity_research/runs/eq-research-20260627T020900225515Z-live/step-outputs/research_signal_packet.json`.

Torben preview and cron:

- Fixture preview rendered exactly one `FIN-20260627-001` card from the equity research agent with no broker/public mutations.
- Default preview produced no stdout and latest artifact had `wakeAgent=false`.
- Actual `hermes -p torben cron run torben-finance-radar`: succeeded.
- Actual `hermes -p torben cron run torben-live-profile-verify`: succeeded; latest verifier artifact has `status=pass`, `errors=[]`.
- Current finance artifact: `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json`.
  - `wakeAgent=false`.
  - `silent_reason="Ratatosk equity data source is degraded; no FIN card staged"`.
  - `candidate_count=0`, `selected_count=0`.
  - Fallback metadata: `preferred_source=ratatosk_equity_research_agent_v1`, `fallback_reason=research_cron_degraded`, research command `scripts/equity_research_signal_cron.py --json`.
  - `public_actions_taken=0`, `external_mutations=0`, `orders_submitted=0`, `broker_orders_submitted=0`.

Paper canary:

- Command:
  - `UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_signal_to_position_canary.py --signal-id EQ-20260627-AAPL-1FB4B3 --paper --json`
- Artifact: `/Users/ericfreeman/ratatosk/state/finance-canaries/EQ-20260627-AAPL-1FB4B3.json`.
- Result: `status=passed`, `reconciliation_status=paper_position_recorded`.
- Paper position: `paper-finance-pos-2282aab753a52378`.
- Trade id: `paper-finance-trade-0f8efafae9342bb2`.
- Position store: `/Users/ericfreeman/ratatosk/state/finance-canaries/paper-portfolio`.
- Broker orders: `0`.

Blocked live canary:

- Command:
  - `UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_canary_from_signal.py --signal-id EQ-20260627-AAPL-1FB4B3 --max-notional-usd 25 --long-only --dry-run --json`
- Artifact: `/Users/ericfreeman/ratatosk/state/live-canaries/EQ-20260627-AAPL-1FB4B3.json`.
- Result: `status=blocked`, `broker_orders_submitted=0`.
- Blocking reasons now exclude broker credentials because `robinhood-agentic-mcp` OAuth is ready and exclude sub-one-share notional because the canary uses a market `dollar_amount` review plan. Remaining blockers are approval exactness, `circuit_breaker_active`, fixture/live-allowed guards, `ratatosk_live_trading_disabled`, `robinhood_live_disabled`, and `trading_halt_active`.

## Tests Run

Ratatosk:

```bash
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_macro_event_equity_evaluations.py \
  tests/test_scripts/test_macro_event_research.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py -q
# 36 passed
```

Hermes:

```bash
venv/bin/python -m pytest \
  tests/test_torben_finance_radar.py \
  tests/test_signal_coo.py \
  tests/gateway/test_torben_gtm_reply_router.py \
  tests/gateway/test_platform_base.py -q
# 245 passed, 2 skipped
```

Focused post-stale-gate check:

```bash
venv/bin/python -m pytest tests/test_torben_finance_radar.py tests/test_signal_coo.py -q
# 82 passed
```

Focused live-profile drift check:

```bash
venv/bin/python -m pytest tests/test_signal_coo_live_profile_verify.py tests/test_torben_finance_radar.py tests/test_signal_coo.py -q
# 98 passed
```

## Dirty Worktree Notes

There were substantial pre-existing dirty changes in both repos before this slice. New work was layered onto the current worktree without reverting unrelated files.

Ratatosk new/touched files from this slice include:

- `docs/llm-contracts/equity-research-agent.md`
- `scripts/equity_research_signal_cron.py`
- `scripts/equity_live_canary_from_signal.py`
- `src/ratatosk/equity_live_canary.py`
- `src/ratatosk/intelligence/equity_mapper.py`
- `src/ratatosk/intelligence/equity_regime_analogs.py`
- `src/ratatosk/intelligence/equity_research_agent.py`
- `src/ratatosk/intelligence/equity_research_schema.py`
- `src/ratatosk/finance_canary.py`
- `state/equity-research/`
- `state/live-canaries/`
- `state/research/equity-historical-regimes.seed.json`
- `tests/test_intelligence/test_equity_mapper_company_events.py`
- `tests/test_intelligence/test_equity_regime_analogs.py`
- `tests/test_intelligence/test_equity_research_schema.py`
- `tests/test_scripts/test_equity_research_signal_cron.py`
- `tests/test_scripts/test_equity_live_canary_from_signal.py`

Hermes/Torben new/touched files from this slice include:

- `docs/goals/torben-ratatosk-equity-research-agent-production-goal.md`
- `docs/goals/torben-ratatosk-equity-research-agent-production-handoff.md`
- `hermes_cli/signal_coo/finance.py`
- `profiles/torben/scripts/torben_finance_radar.py`
- `/Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py`
- `tests/test_torben_finance_radar.py`

## Next Commands

Re-run the stage-only proof ladder:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_research_signal_cron.py --fixture company-hardware-pricing --json
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_research_signal_cron.py --fixture hot-market-dip --json
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_research_signal_cron.py --json
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_signal_to_position_canary.py --signal-id EQ-20260627-AAPL-1FB4B3 --paper --json
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_canary_from_signal.py --signal-id EQ-20260627-AAPL-1FB4B3 --max-notional-usd 25 --long-only --dry-run --json

cd /Users/ericfreeman/.hermes/hermes-agent
HERMES_HOME=/Users/ericfreeman/.hermes/profiles/torben TORBEN_FINANCE_RADAR_PREVIEW=1 TORBEN_FINANCE_RESEARCH_FIXTURE=company-hardware-pricing venv/bin/python /Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py
HERMES_HOME=/Users/ericfreeman/.hermes/profiles/torben TORBEN_FINANCE_RADAR_PREVIEW=1 venv/bin/python /Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py
hermes -p torben cron run torben-finance-radar
hermes -p torben cron run torben-live-profile-verify
```

## 2026-06-27 ADLC Live-Promotion Productionization Addendum

Added a no-mutation promotion ladder between persisted research signals and the
blocked/dry-run live canary:

- Ratatosk runbook: `/Users/ericfreeman/ratatosk/docs/equity-live-promotion-productionization.md`.
- Promotion gate: `/Users/ericfreeman/ratatosk/src/ratatosk/equity_live_promotion.py`.
- Agentic MCP broker-auth probe: `/Users/ericfreeman/ratatosk/src/ratatosk/robinhood_agentic_mcp.py`.
- Readiness CLI: `/Users/ericfreeman/ratatosk/scripts/equity_live_promotion_readiness.py`.
- Approval request CLI: `/Users/ericfreeman/ratatosk/scripts/equity_live_approval_request.py`.
- Canary now embeds the promotion-readiness artifact before writing a would-place review.

The gate remains fail-closed. It blocks missing/invalid exact approvals, missing
broker auth when neither Agentic MCP OAuth nor raw fallback credentials are
ready, disabled live flags, active halt/breaker state,
`live_allowed=false`, stale/degraded/fixture research, nonzero mutation
counters, non-long-only candidates, and unpriceable canary packets. Sub-one-share
equity canaries are represented as `review_equity_order` market-dollar plans
using `dollar_amount` and `market_hours=regular_hours`. Broker orders and
external mutations remain `0`.

The supported broker-auth path is now the hosted `robinhood-agentic-mcp` OAuth
server in `/Users/ericfreeman/.hermes/profiles/torben`; raw
`ROBINHOOD_USERNAME` / `ROBINHOOD_PASSWORD` env vars are fallback only.

Current approval request:

- Generated exact request artifact:
  `/Users/ericfreeman/ratatosk/state/approvals/EQ-20260627-AAPL-E78D6F.json`.
- It is intentionally `approved=false` with every risk acknowledgement still
  `false`.
- Running the dry-run canary with that artifact now leaves only these blocker
  classes: `approval_not_approved`, missing risk acknowledgements,
  `circuit_breaker_active`, fixture/live-allowed guards,
  `ratatosk_live_trading_disabled`, `robinhood_live_disabled`, and
  `trading_halt_active`.
- The would-place review plan is `order_type=market`,
  `quantity_basis=dollar_amount`, `dollar_amount=25.00`, `market_hours=regular_hours`;
  broker orders, external mutations, and orders submitted remain `0`.

Focused verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/robinhood_equity_readiness.py --broker-auth-mode agentic-mcp --json
# ready=true, broker_auth_mode=agentic_mcp, tool_count=44, secrets_redacted=true

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  -q
# 15 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  -q
# 44 passed
```

## 2026-06-27 Agentic MCP Runtime Follow-Up

Ratatosk now uses the existing hosted Agentic MCP server for both broker-auth
readiness and live quote fallback. When the legacy raw Robinhood connector
cannot authenticate, the equity scan falls back to the read-only
`robinhood-agentic-mcp` `get_equity_quotes` tool and returns a
`latest_available_market_packet` instead of marking the source degraded. The
fallback is non-mutating and does not invoke order-placement tools.

Current live runtime proof:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_scan_packet.py --json >/tmp/ratatosk-equity-scan-packet.json 2>/tmp/ratatosk-equity-scan-packet.stderr
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_research_signal_cron.py --json >/tmp/ratatosk-equity-research-live.json 2>/tmp/ratatosk-equity-research-live.stderr
```

Observed result:

- `status=no_actionable_signal`
- `source_freshness.status=latest_available_market_packet`
- MCP-backed quote packet contained 20 equity markets
- stderr was empty after fallback-aware logging cleanup
- broker orders, orders submitted, external mutations, and public actions were
  all `0`

Torben cron proof:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
hermes -p torben cron run torben-finance-radar
hermes -p torben cron run torben-live-profile-verify
```

Observed `torben-finance-radar-latest.json`:

- `ratatosk_status=no_actionable_signal`
- `candidate_count=0`
- `selected_count=0`
- `wakeAgent=false`
- `source_refresh.status=success`
- `source_refresh.stderr_tail=""`
- broker orders, orders submitted, external mutations, and public actions were
  all `0`

Expanded verification after the MCP fallback/logging follow-up:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  -q
# 60 passed
```

Remaining live gates are intentionally human/risk gates: exact approval must be
approved with risk acknowledgements, circuit breaker and trading halt must be
explicitly cleared, live flags must be scoped to a separately approved
invocation, and a live research candidate must be present. None of those were
auto-cleared.

## 2026-06-27 Account-Explicit MCP Review Follow-Up

The hosted Robinhood MCP schema requires an explicit `account_number` for both
`review_equity_order` and `place_equity_order`; it also says not to infer or
default that value from `get_accounts`. Ratatosk now treats that account number
as a human-provided approval field, not as a discovered credential.

Changes added after the runtime follow-up:

- Approval request templates are now clearly pending: `approved=false`,
  `approved_by=""`, `approved_at=null`, every risk acknowledgement is `false`,
  and `account_number=""`.
- Promotion readiness blocks with `approval_missing_account_number` until the
  exact approval artifact includes the explicit Agentic account number.
- Runtime auth prefers healthy `agentic_mcp` over raw Robinhood env credentials
  when both are present.
- The dry-run canary can call non-submitting MCP `review_equity_order` after
  all promotion gates pass, redacts account fields in artifacts, and still
  never calls `place_equity_order`.

Current exact request artifact:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_approval_request.py \
  --signal-id EQ-20260627-AAPL-E78D6F \
  --max-notional-usd 25 \
  --long-only \
  --requested-by eric \
  --output state/approvals/EQ-20260627-AAPL-E78D6F.json \
  --json
```

Current blocked canary proof now includes:

- `approval_missing_account_number`
- `approval_missing_approved_by`
- `approval_missing_or_invalid_approved_at`
- missing risk acknowledgements
- `approval_not_approved`
- `circuit_breaker_active`
- fixture/live-allowed blockers
- `ratatosk_live_trading_disabled`
- `robinhood_live_disabled`
- `trading_halt_active`
- `mcp_review.attempted=false` because promotion is not ready
- broker orders, orders submitted, external mutations, and public actions are
  all `0`

The current answer to "what do I have to provision credentials for?" is:
no raw Robinhood username/password for this path; provide the explicit Agentic
Robinhood account number in the exact approval artifact, then separately
approve/acknowledge the one-shot canary and clear the halt/breaker/live flags
only for the approved invocation.

## 2026-06-27 Guarded Live Submit Implementation Follow-Up

Ratatosk now has the actual Agentic MCP live-submit path implemented, but it is
not reachable by default. `scripts/equity_live_canary_from_signal.py` accepts
`--execute-live-order`; without that flag, a non-dry-run canary still blocks
with `live_order_placement_disabled_in_v0_1`.

Live submit gates now enforced before `place_equity_order`:

- exact approval artifact is valid
- `approval_scope=one_shot_live_canary`
- explicit Agentic `account_number` is present in the approval artifact
- every risk acknowledgement is true
- `RATATOSK_LIVE_TRADING=true` and `ROBINHOOD_LIVE=true`
- halt and circuit breaker are clear
- research packet is fresh, non-fixture, QA-passed, live-allowed, long-only,
  and has zero mutation counters
- broker auth mode is `agentic_mcp`
- MCP `review_equity_order` succeeds first
- MCP review response has no alerts, warnings, errors, or review text
- `--execute-live-order` is explicit

The place call sends MCP `place_equity_order` with the same reviewed order plus
a deterministic `ref_id` derived from the signal and approval context, so
retries use the same idempotency key. Artifacts redact account fields.

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 74 passed
```

Current live-safe probe with `--execute-live-order` remains blocked because the
real artifact is still unapproved, missing account/approver/timestamp/risk
acks, scoped live flags are off, halt/breaker are active, and the fixture signal
is now stale/not live-allowed. MCP review and live submission were both
`attempted=false`; broker orders, orders submitted, external mutations, and
public actions were all `0`.

Torben proof after this change:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
hermes -p torben cron run torben-finance-radar
hermes -p torben cron run torben-live-profile-verify
```

Both succeeded. Finance radar remained silent with
`ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
`source_refresh.stderr_tail=""`, and all mutation counters at `0`.

Additional hardening after this verification: a live submit now blocks if MCP
`review_equity_order` returns any alert/warning/error payload even when the tool
itself returns `ok=true`; tests cover that review-alert path and prove
`place_equity_order` is not called.

## 2026-06-27 Read-Only Go-Live Status Follow-Up

Added a read-only operator status command:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_status.py --json
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_status.py --signal-id EQ-20260627-AAPL-E78D6F --json
```

It probes Agentic MCP readiness, reads the latest approval/promotion/canary
artifacts or exact signal-scoped artifacts, recomputes the promotion gate in
memory using current time/env, reports `ready_to_submit`, aggregates blockers,
emits next human actions, and summarizes mutation counters. It does not call
broker review/place or mutate state.

It now also emits `credentials.provisioning`, a machine-readable operator
checklist:

- `use_existing_mcp_agent_server=true`
- `broker_secret_boundary=torben_profile_robinhood_agentic_mcp`
- `mcp_server_name=robinhood-agentic-mcp`
- `mcp_oauth_status=ready` when the Torben-hosted OAuth state is usable
- `required_to_provision`: MCP OAuth state, explicit Agentic Robinhood
  `account_number` in the exact approval artifact, and a complete one-shot live
  canary approval
- `not_required_to_provision`: raw `ROBINHOOD_USERNAME`,
  `ROBINHOOD_PASSWORD`, or raw Robinhood session secrets in Ratatosk

Current observed status:

- `ready_to_submit=false`
- `go_live_blocked=true`
- `status_refresh.promotion_recomputed=true`
- `ready_to_submit=true` now also requires exact signal-scoped status and a
  fresh dry-run MCP review for the same signal after the exact approval
  timestamp; stale dry-run reviews are blocked
- the dry-run MCP review request must match the recomputed current order plan
  before status will report submit-ready
- MCP ready with 44 tools and required read/review tools present
- raw Robinhood username/password not required
- Agentic account number is still required in the approval artifact
- credential provisioning currently reports MCP OAuth `ready`,
  `agentic_robinhood_account_number=missing`, and
  `one_shot_live_canary_approval=missing_or_incomplete`
- all mutation counters remain `0`
- blockers are approval/account/risk-ack/scope, halt/breaker, stale fixture
  signal, scoped live flags off, and live guard false

Torben finance radar was rerun after this addition and still succeeded with
`ratatosk_status=no_actionable_signal`, empty `stderr_tail`, and all mutation
counters at `0`.

## 2026-06-27 Exact Signal-Scoped Status Verification

The operator status command now accepts `--signal-id`, so go-live checks can be
bound to one exact persisted signal instead of whichever approval/promotion/
canary artifact is latest.

Current exact signal check:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_status.py --signal-id EQ-20260627-AAPL-E78D6F --json
```

Observed result:

- `requested_signal_id=EQ-20260627-AAPL-E78D6F`
- `resolved_signal_id=EQ-20260627-AAPL-E78D6F`
- `ready_to_submit=false`
- `go_live_blocked=true`
- `status_refresh.read_only=true`
- `status_refresh.broker_review_attempted=false`
- `status_refresh.broker_place_attempted=false`
- MCP ready with 44 tools, required read/review tools present, and
  `secrets_redacted=true`
- raw Robinhood username/password credentials are not required
- required human credential/input is still the explicit Agentic
  `account_number` in the exact approval artifact
- `credentials.provisioning` reports
  `broker_secret_boundary=torben_profile_robinhood_agentic_mcp`,
  `mcp_oauth_status=ready`, `agentic_robinhood_account_number=missing`, and
  `one_shot_live_canary_approval=missing_or_incomplete`
- current blockers are `approval_expired`, missing account/approver/timestamp,
  missing risk acknowledgements, unapproved scope, halt/breaker active, stale
  fixture research, stale quote/research packet, live flags off, and
  `live_allowed=false`
- broker orders, orders submitted, external mutations, and public actions are
  all `0`

Latest verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_status.py scripts/equity_live_status.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 74 passed
```

Torben runtime verification:

```bash
hermes -p torben cron run torben-finance-radar
hermes -p torben cron run torben-live-profile-verify
```

Both succeeded. Latest finance artifact:
`wakeAgent=false`, `silent_reason="Ratatosk produced no research candidates"`,
`candidate_count=0`, `selected_count=0`, `ratatosk_status=no_actionable_signal`,
`source_refresh.status=success`, `public_actions_taken=0`,
`external_mutations=0`, `orders_submitted=0`, and
`broker_orders_submitted=0`.

## 2026-06-27 Credential Checklist Runtime Follow-Up

The current answer to provisioning is now encoded in
`scripts/equity_live_status.py`, not only in prose. Exact status for
`EQ-20260627-AAPL-E78D6F` reports:

- existing MCP server should be used: `use_existing_mcp_agent_server=true`
- broker secret boundary: `torben_profile_robinhood_agentic_mcp`
- MCP OAuth status: `ready`
- MCP server name: `robinhood-agentic-mcp`
- required but missing: explicit Agentic `account_number` in
  `/Users/ericfreeman/ratatosk/state/approvals/EQ-20260627-AAPL-E78D6F.json`
- required but incomplete: one-shot live canary approval
- not required in Ratatosk: `ROBINHOOD_USERNAME`, `ROBINHOOD_PASSWORD`, or raw
  Robinhood session secrets

Verification after adding the checklist:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_status.py scripts/equity_live_status.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_scripts/test_equity_live_status.py -q
# 7 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 74 passed
```

Live-safe probes after the checklist:

- `scripts/robinhood_equity_readiness.py --broker-auth-mode agentic-mcp --json`
  returned `ready=true`, `broker_auth_mode=agentic_mcp`,
  `failure_kinds=[]`, and `secrets_redacted=true`.
- Exact status remained `ready_to_submit=false`,
  `go_live_blocked=true`, `status_refresh.read_only=true`,
  `broker_review_attempted=false`, `broker_place_attempted=false`, and all
  mutation counters `0`.
- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded; latest artifact
  had `wakeAgent=false`, `ratatosk_status=no_actionable_signal`,
  `source_refresh.status=success`, empty `stderr_tail`, and all mutation/order
  counters `0`.

## 2026-06-27 MCP Market-Open Candidate Path Follow-Up

Fixed the remaining MCP-only production gap: after raw Robinhood auth failed,
Ratatosk could read quotes through `robinhood-agentic-mcp`, but the fallback
always emitted `signals=[]`. Separately, the live research episode runner ignored
real scan candidates and always converted live runs into degraded/no-action
packets. That meant the MCP-only broker path could never produce a non-fixture
research signal to promote, even during market hours.

Implemented behavior:

- `run_equity_scan()` now passes market-open state into the Agentic MCP fallback.
- When the market is open, MCP quote fallback can stage at most one conservative
  long-only candidate if all quote gates pass:
  `live_market_packet`, active/traded quote, price at least 3% above adjusted
  prior close, and bid/ask spread no more than 2%.
- Outside market hours, latest-available MCP quotes still produce no candidate.
- `run_equity_research_episode()` now persists a real scan candidate as a
  validated `qa_passed` `mcp_quote_momentum` research packet instead of
  discarding it into `no_actionable_signal`.
- The generated packet remains stage-only and zero-mutation, but its guard is
  live-promotable after explicit approval because `live_allowed=true` is carried
  inside a blocked guard state.
- Promotion readiness now has test coverage proving a market-open MCP candidate
  can reach `status=ready` once exact approval, account number, risk
  acknowledgements, scoped live flags, clear halt/breaker, and MCP auth are
  supplied.

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/intelligence/pipeline.py src/ratatosk/intelligence/equity_research_agent.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_intelligence/test_equity_scan.py tests/test_scripts/test_equity_research_signal_cron.py tests/test_scripts/test_equity_live_promotion_readiness.py -q
# 25 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 77 passed
```

Current live-safe runtime after the change:

- `scripts/equity_scan_packet.py --json`: `status=no_actionable_signal`,
  `market_open=false`, `source_freshness.status=latest_available_market_packet`,
  `market_count=20`, `candidate_count=0`, `signals=[]`, all mutation/order
  counters `0`.
- `scripts/equity_research_signal_cron.py --json`:
  `status=no_actionable_signal`, `candidate_count=0`, packet
  `status=no_actionable_signal`, guard `live_allowed=false`, all mutation/order
  counters `0`.
- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded; latest artifact
  had `wakeAgent=false`, `silent_reason="Ratatosk produced no research candidates"`,
  `ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
  empty `stderr_tail`, and all mutation/order counters `0`.

## 2026-06-27 Latest-Candidate Approval Guard Follow-Up

Closed the next operator gap: status could be scoped to older promotion/canary
artifacts while the latest research run had already moved on to
`no_actionable_signal`. A human could still manually run the approval request
CLI with an old signal id, so the production path now has a guarded latest
research resolver.

Implemented behavior:

- `latest_research_candidate_context()` reads
  `/Users/ericfreeman/ratatosk/state/equity-research/latest.json` and returns a
  fail-closed readiness object.
- `scripts/equity_live_approval_request.py --latest-research-candidate` writes
  an approval request only when the latest research artifact has exactly one
  live, QA-passed, Torben-worthy candidate with a live-promotable guard.
- If the latest research run is no-action, stale/latest-available, missing a
  candidate, non-live, invalid, or not Torben-worthy, the command exits blocked
  and writes no approval artifact.
- `scripts/equity_live_status.py --json` now includes
  `latest_research_candidate` and a guarded
  `create_latest_research_approval_request` command.

Current live result:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_approval_request.py --latest-research-candidate --max-notional-usd 25 --long-only --requested-by eric --json
```

Observed result:

- `status=blocked`
- `reason=latest_research_candidate_not_ready`
- `approval_request_written=false`
- no `/Users/ericfreeman/ratatosk/state/approvals/EQ-20260627-DEGRADED.json`
  file was written
- latest candidate context:
  `status=no_actionable_signal`, `candidate_count=0`,
  `signal_id=EQ-20260627-DEGRADED`,
  `source_freshness.status=latest_available_market_packet`,
  `guard.live_allowed=false`
- validation reasons included `latest_research_candidate_count_not_one`,
  `latest_research_guard_live_not_allowed`,
  `latest_research_not_live_market_packet:latest_available_market_packet`,
  `latest_research_packet_not_torben_worthy`, and
  `latest_research_status_not_success:no_actionable_signal`

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_promotion.py src/ratatosk/equity_live_status.py scripts/equity_live_approval_request.py scripts/equity_live_status.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_scripts/test_equity_live_promotion_readiness.py tests/test_scripts/test_equity_live_status.py -q
# 16 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 80 passed
```

Live-safe probes after this guard:

- `scripts/equity_live_status.py --json` reported
  `latest_research_candidate.ready=false`, `ready_to_submit=false`,
  `go_live_blocked=true`, MCP ready with 44 tools, status refresh read-only,
  `broker_review_attempted=false`, `broker_place_attempted=false`, and all
  mutation/order counters `0`.
- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded; latest artifact
  had `wakeAgent=false`, `silent_reason="Ratatosk produced no research candidates"`,
  `candidate_count=0`, `selected_count=0`,
  `ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
  empty `stderr_tail`, and all mutation/order counters `0`.

## 2026-06-27 Status Scope Warning Follow-Up

Closed another operator ambiguity: `scripts/equity_live_status.py --json`
could resolve the latest approval/promotion/canary artifact while the latest
research run pointed somewhere else. The status payload now includes
`status_scope` so the operator can see whether the check is exact-signal scoped,
which signal was resolved, which signal is latest research, and what warnings
apply.

Current unscoped status:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_status.py --json
```

Observed status scope:

- `exact_signal_scoped=false`
- `resolved_signal_id=EQ-20260627-AAPL-E78D6F`
- `latest_research_signal_id=EQ-20260627-DEGRADED`
- `latest_research_ready=false`
- warnings:
  `status_not_signal_scoped`,
  `resolved_signal_differs_from_latest_research`,
  `latest_research_candidate_not_ready`

The same status output keeps the current fail-closed proof:

- `latest_research_candidate.ready=false`
- latest research `status=no_actionable_signal`
- `candidate_count=0`
- latest research validation reasons include
  `latest_research_candidate_count_not_one` and
  `latest_research_not_live_market_packet:latest_available_market_packet`
- `ready_to_submit=false`
- `go_live_blocked=true`
- `status_refresh.read_only=true`
- `broker_review_attempted=false`
- `broker_place_attempted=false`
- MCP ready with 44 tools
- all mutation/order counters `0`

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_status.py scripts/equity_live_status.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_scripts/test_equity_live_status.py -q
# 8 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 81 passed
```

Live-safe probes after this change:

- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded.
- Latest finance artifact had `wakeAgent=false`,
  `silent_reason="Ratatosk produced no research candidates"`,
  `candidate_count=0`, `selected_count=0`,
  `ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
  empty `stderr_tail`, and all mutation/order counters `0`.

## 2026-06-27 Live Submit Command Gate Follow-Up

Closed another operator-safety gap: `scripts/equity_live_status.py --json`
used to emit a copy-pasteable one-shot live-submit command even while
`ready_to_submit=false`. The submit code was still fail-closed, but the status
surface should not hand out a live-submit command until the full readiness proof
is green.

Implemented behavior:

- `commands.one_shot_live_submit` is now `null` while blocked.
- `command_gates.one_shot_live_submit.available=false` while blocked.
- The command gate includes `reason=ready_to_submit_false`,
  `requires_ready_to_submit=true`, and the current blocker list.
- When exact signal-scoped status reports `ready_to_submit=true`, the command
  remains a normal copy-pasteable command string.

Current observed status:

- `ready_to_submit=false`
- `go_live_blocked=true`
- `commands.one_shot_live_submit=null`
- `command_gates.one_shot_live_submit.available=false`
- `command_gates.one_shot_live_submit.reason=ready_to_submit_false`
- `status_refresh.read_only=true`
- `broker_review_attempted=false`
- `broker_place_attempted=false`
- all mutation/order counters `0`

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_status.py scripts/equity_live_status.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_scripts/test_equity_live_status.py -q
# 8 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 81 passed
```

Live-safe probes:

- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded.
- Latest finance artifact had `wakeAgent=false`,
  `silent_reason="Ratatosk produced no research candidates"`,
  `candidate_count=0`, `selected_count=0`,
  `ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
  empty `stderr_tail`, and all mutation/order counters `0`.

## 2026-06-27 Exact-Scope Submit-Ready Gate Follow-Up

Tightened the final operator-status gate: `ready_to_submit=true` now requires
the status command itself to be scoped with `--signal-id <SIGNAL_ID>`. Unscoped
status remains useful for dashboards and discovery, but it adds the
`status_not_signal_scoped` blocker and never emits the one-shot live-submit
command.

Current verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_status.py scripts/equity_live_status.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_scripts/test_equity_live_status.py -q
# 8 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 81 passed
```

Current live read-only proof:

- `scripts/equity_scan_packet.py --json`: `status=no_actionable_signal`,
  `market_open=false`, `source_freshness.status=latest_available_market_packet`,
  `candidate_count=0`, `signals=[]`, all mutation/order counters `0`.
- `scripts/equity_research_signal_cron.py --json`:
  `status=no_actionable_signal`, `signal_id=EQ-20260627-DEGRADED`,
  `candidate_count=0`, `guard.live_allowed=false`, all mutation/order counters
  `0`.
- `scripts/equity_live_approval_request.py --latest-research-candidate ...`
  refused with `reason=latest_research_candidate_not_ready`,
  `approval_request_written=false`, and no output artifact.
- Unscoped `scripts/equity_live_status.py --json` reported
  `ready_to_submit=false`, `go_live_blocked=true`,
  `status_scope.exact_signal_scoped=false`,
  `status_not_signal_scoped` in both `status_scope.warnings` and `blockers`,
  `commands.one_shot_live_submit=null`, MCP OAuth `ready`, and all
  mutation/order counters `0`.
- Exact `scripts/equity_live_status.py --signal-id EQ-20260627-AAPL-E78D6F --json`
  reported `status_scope.exact_signal_scoped=true` but still
  `ready_to_submit=false` because the old signal is expired/unapproved, missing
  account/approver/risk acknowledgements, stale/fixture/live-disallowed, halt
  and circuit breaker are active, and live flags are off.
- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded; latest artifact
  had `wakeAgent=false`, `silent_reason="Ratatosk produced no research candidates"`,
  `candidate_count=0`, `selected_count=0`,
  `ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
  `source_refresh.stderr_tail=""`, and all mutation/order counters `0`.

## 2026-06-27 Prior Dry-Run Submit Authorization Follow-Up

Closed a final submit-path gap: a manually typed
`scripts/equity_live_canary_from_signal.py --execute-live-order` can no longer
reach the fresh MCP review/place path unless a prior matching dry-run canary
artifact exists for the same signal and current order plan. The prior artifact
must be `status=dry_run`, MCP `review_equity_order` must be `ok=true`, review
alerts/warnings/errors/text must be absent, mutation/order counters must be
zero, the review order must match the recomputed order plan, and the dry-run
must be after approval, before approval expiry, and inside the freshness window.

Verification:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_promotion.py src/ratatosk/equity_live_canary.py scripts/equity_live_canary_from_signal.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_scripts/test_equity_live_canary_from_signal.py -q
# 13 passed

UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_regime_analogs.py \
  tests/test_intelligence/test_equity_mapper.py \
  tests/test_intelligence/test_equity_mapper_company_events.py \
  tests/test_intelligence/test_equity_scan.py \
  tests/test_intelligence/test_equity_scan_packet.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_intelligence/test_robinhood_agentic_mcp.py \
  tests/test_intelligence/test_robinhood_equity_readiness.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_scripts/test_equity_live_promotion_readiness.py \
  tests/test_scripts/test_equity_live_status.py \
  -q
# 84 passed
```

Current blocked live-submit probe:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_live_canary_from_signal.py \
  --signal-id EQ-20260627-AAPL-E78D6F \
  --max-notional-usd 25 \
  --long-only \
  --approval-artifact state/approvals/EQ-20260627-AAPL-E78D6F.json \
  --execute-live-order \
  --json
```

Observed result:

- `status=blocked`.
- Prior dry-run authorization was required and invalid because the existing
  artifact is not a clean matching dry-run:
  `prior_dry_run_status_not_dry_run`,
  `prior_dry_run_review_missing_or_failed`, and
  `prior_dry_run_order_mismatch`.
- MCP review was not attempted: `mcp_review.reason=promotion_not_ready`.
- MCP place was not attempted: `live_submission.reason=promotion_not_ready`.
- Broker orders, orders submitted, external mutations, and public actions all
  remained `0`.

Fresh live-safe probes after this change:

- `scripts/equity_research_signal_cron.py --json` remained
  `status=no_actionable_signal`, `signal_id=EQ-20260627-DEGRADED`,
  `candidate_count=0`, `source_freshness.status=latest_available_market_packet`,
  `guard.live_allowed=false`, and all mutation/order counters `0`.
- `scripts/equity_live_status.py --json` remained
  `ready_to_submit=false`, `go_live_blocked=true`,
  `status_scope.exact_signal_scoped=false`, latest research candidate
  `ready=false`, `commands.one_shot_live_submit=null`, all mutation/order
  counters `0`, and now includes the prior-dry-run blockers from the blocked
  submit probe in the unavailable command gate.
- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded; latest artifact
  had `wakeAgent=false`, `candidate_count=0`, `selected_count=0`,
  `ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
  `source_refresh.stderr_tail=""`, and all mutation/order counters `0`.

## 2026-06-27 Final Verification Refresh

Latest verification on this host:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m py_compile src/ratatosk/equity_live_status.py scripts/equity_live_status.py src/ratatosk/equity_live_promotion.py src/ratatosk/equity_live_canary.py scripts/equity_live_canary_from_signal.py
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_scripts/test_equity_live_status.py tests/test_scripts/test_equity_live_canary_from_signal.py -q
# 21 passed
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_intelligence/test_equity_research_schema.py tests/test_intelligence/test_equity_regime_analogs.py tests/test_intelligence/test_equity_mapper.py tests/test_intelligence/test_equity_mapper_company_events.py tests/test_intelligence/test_equity_scan.py tests/test_intelligence/test_equity_scan_packet.py tests/test_intelligence/test_finance_canary.py tests/test_intelligence/test_robinhood_agentic_mcp.py tests/test_intelligence/test_robinhood_equity_readiness.py tests/test_scripts/test_equity_research_signal_cron.py tests/test_scripts/test_equity_live_canary_from_signal.py tests/test_scripts/test_equity_live_promotion_readiness.py tests/test_scripts/test_equity_live_status.py -q
# 84 passed
```

Live-safe runtime proof:

- Agentic MCP broker readiness is green: OAuth ready, required read/review tools
  present, `tool_count=44`, and raw Robinhood username/password are not required
  in Ratatosk.
- `scripts/equity_scan_packet.py --json` used MCP quote data but remained
  `status=no_actionable_signal`, `market_open=false`, `candidates=[]`,
  `signals=[]`, with all mutation/order counters `0`.
- `scripts/equity_research_signal_cron.py --json` refreshed latest research to
  `EQ-20260627-DEGRADED`, `candidate_count=0`, `torben_worthy=false`,
  `guard.live_allowed=false`, with all mutation/order counters `0`.
- `scripts/equity_live_approval_request.py --latest-research-candidate ...`
  refused with `reason=latest_research_candidate_not_ready`,
  `approval_request_written=false`, and no output artifact.
- Unscoped `scripts/equity_live_status.py --json` remains
  `ready_to_submit=false`, `go_live_blocked=true`,
  `status_scope.exact_signal_scoped=false`, has `status_not_signal_scoped` in
  blockers, `commands.one_shot_live_submit=null`, MCP ready, and all
  mutation/order counters `0`.
- Exact `scripts/equity_live_status.py --signal-id EQ-20260627-AAPL-E78D6F --json`
  remains exact-scoped but blocked on expired/unapproved approval, missing
  account/risk fields, stale or fixture research, halt/breaker, live flags off,
  and prior dry-run authorization blockers.
- A guarded `scripts/equity_live_canary_from_signal.py --execute-live-order`
  probe without live env flags remained `status=blocked`; MCP review was not
  attempted, MCP place was not attempted, `live_submit_requested=true`,
  `live_submit_authorized=false`, `allow_live_submit=false`, and
  broker/order/mutation counters stayed `0`.
- `hermes -p torben cron run torben-live-profile-verify` succeeded.
- `hermes -p torben cron run torben-finance-radar` succeeded; latest artifact
  at `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json`
  has `wakeAgent=false`,
  `silent_reason="Ratatosk produced no research candidates"`,
  `candidate_count=0`, `selected_count=0`,
  `ratatosk_status=no_actionable_signal`, `source_refresh.status=success`,
  `source_refresh.stderr_tail=""`, and all mutation/order counters `0`.
