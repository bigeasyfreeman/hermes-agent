# ADLC Plan: Ratatosk Equity Research Agent for Torben Finance Canary

Last updated: 2026-06-26.

## Review Status

Status: **FOR REVIEW BEFORE BUILD**

This is a planning and research artifact only. It does **not** authorize live trading, clear circuit breakers, set live env flags, or place/cancel broker orders.

## User Intent

Eric wants the Torben/Ratatosk finance loop to generate trade candidates from an agentic research engine, not from generic watchlists or fixture-only canaries.

Examples the implementation must support:

1. A company or sector event occurs while the broader market is moving. Apple announcing increased hardware prices during a market selloff is one representative example, not a binary rule.
   - The engine should identify direct and second-order exposures when relevant, but it must be allowed to conclude that the event does not matter.
   - It should reason about suppliers, semis, consumer hardware, index exposure, options-implied expectations, market regime, and portfolio fit.
   - The pass condition is reasoning quality and evidence discipline, not a predetermined AAPL/QQQ trade.

2. Market is running hot, then dips.
   - The engine should compare the current regime to historical tech bubble / tech drawdown regimes.
   - It should decide whether the right response is no trade, hedge, short candidate, pair trade, or tiny canary.

The desired live canary must be based on a **research-engine-generated signal**, not a manually picked symbol.

## Current State Found

### Current Cron Path

Torben finance cron uses:

```text
/Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py
  -> /Users/ericfreeman/ratatosk/scripts/equity_scan_packet.py
  -> ratatosk.equity_scan_packet.run_equity_scan_packet()
  -> ratatosk.intelligence.pipeline.run_equity_scan()
```

`run_equity_scan()` does call the current equity research function (`generate_equity_signal`) after data collection, but the current live run stops before signal generation because Robinhood equity auth/data is unavailable:

```json
{
  "status": "data_source_degraded",
  "source_freshness": {"status": "auth_failed"},
  "markets": [],
  "signals": [],
  "candidates": [],
  "external_mutations": 0,
  "orders_submitted": 0,
  "broker_orders_submitted": 0
}
```

Current readiness gate:

```json
{
  "ready": false,
  "failure_kinds": ["missing_equity_credentials"],
  "ROBINHOOD_USERNAME_present": false,
  "ROBINHOOD_PASSWORD_present": false,
  "RATATOSK_LIVE_TRADING": false,
  "ROBINHOOD_LIVE": false
}
```

Current live guard:

```text
stage_allowed=true
live_allowed=false
- live Robinhood orders require matching human consent
- circuit breaker tripped at 43.1% drawdown
- RATATOSK_LIVE_TRADING=true is not set
```

### Existing Modules To Reuse

Ratatosk already has strong components:

- `src/ratatosk/intelligence/signal_generator.py`
  - Existing `generate_equity_signal()` fetches historicals, technicals, earnings, options-implied move, news, LLM probability estimate, edge, conviction, and action.
- `src/ratatosk/intelligence/news_gatherer.py`
  - Research cache, LLM/web-like context search, economic data hooks.
- `src/ratatosk/intelligence/macro_events.py`
  - Normalizes macro/geopolitical/corporate events into tradable candidate relationships.
- `src/ratatosk/intelligence/situation_memory.py`
  - BM25-backed historical analogy retrieval, but prediction-market oriented today.
- `src/ratatosk/intelligence/technical.py` and `technical_indicators.py`
  - Deterministic market indicators.
- `src/ratatosk/intelligence/sentiment.py`
  - Sentiment snapshots with source availability and veto/reduce flags.
- `src/ratatosk/intelligence/earnings_scanner.py`
  - Robinhood-backed earnings data.
- `src/ratatosk/intelligence/options_analyzer.py`
  - Options-implied move and advisory-only options candidates.
- `src/ratatosk/intelligence/signal_qa.py`
  - Deterministic signal QA before escalation.
- `src/ratatosk/intelligence/council.py`
  - Multi-persona council with equity asset-class profile.
- `src/ratatosk/intelligence/pipeline_runner.py`
  - Persisted pipeline runs and step outputs.
- `src/ratatosk/equity_scan_packet.py`
  - Existing Torben-facing packet adapter.
- `src/ratatosk/finance_canary.py`
  - Existing stage-only paper signal-to-position canary, now using real position/trade-log artifacts.
- `.hermes/hermes-agent/hermes_cli/signal_coo/finance.py`
  - `FinanceQualityGate` and Torben FIN card adapter.

### Gap

The current path has pieces, but it is not yet a first-class agentic research episode:

- No durable research-agent mandate / system contract.
- No generalized event/regime ingestion layer wired to Torben for company, sector, macro, and market-regime signals. Apple price increases are only one representative fixture, not a special-case strategy.
- No cross-asset impact mapper from event -> tickers -> trade expressions.
- No equity-specific historical regime analog engine for tech bubbles, drawdowns, and market-hot-then-dip patterns.
- No persisted research episode with step-by-step evidence.
- No strict JSON research-signal schema shared by Ratatosk and Torben.
- No live-canary-from-engine-signal harness that requires a real research signal and refuses manual/fixture signals.
- Current `generate_equity_signal()` is symbol-first. The desired engine is event/regime-first and can discover affected symbols.

## ADLC Scope

ADLC here means:

- **Assess**: establish current state, constraints, evidence sources, and acceptance bar.
- **Design**: define contracts, data flow, schemas, prompts, gates, and review decisions.
- **Lift**: implement in safe slices, repo-side first, live-profile sync last.
- **Check**: verify with fixture, degraded, paper, and live-gated canary evidence.

## A — Assess

### A1. Product Requirement

Build `Ratatosk Equity Research Agent v0.1`.

It should run on cron, gather events and market data, reason with LLM constraints, retrieve historical analogs, produce decision-grade research signals, and hand only qualified candidates to Torben as `FIN-*` review cards.

### A2. Non-Negotiable Safety Boundaries

- No live order placement until Eric explicitly approves a specific canary.
- No clearing `state/trading-halt.json`, `state/circuit-breaker.json`, or equivalent halt state without explicit approval.
- No setting `RATATOSK_LIVE_TRADING=true` or `ROBINHOOD_LIVE=true` without explicit approval.
- No options, margin, shorting, 0DTE, or risk-cap widening unless separately approved.
- The research agent may suggest short/hedge expressions, but execution remains blocked unless an allowlist and guard pass.
- Every visible candidate must include mutation counters and guard result.
- No Signal wake on generic watchlists, missing market packet, missing thesis, missing refs, or stale data.

### A3. Current External Blockers

- Robinhood equity credentials are missing.
- Current live data source is unavailable.
- Circuit breaker is tripped at 43.1% drawdown.
- Live flags are off.

These are acceptable for the build because the first stage can be fixture/degraded/paper. They are blockers for a real live broker canary.

### A4. Research Engine Readiness Questions

Decisions Eric should review before build:

1. Should v0.1 permit **short candidates** as research-only outputs, while keeping execution blocked?
   - Recommendation: yes, research-only. Execution blocked until shorting is separately approved.
2. Should v0.1 include **options-derived market-implied probabilities** but forbid option execution?
   - Recommendation: yes. Advisory-only options data is useful for probability/edge, but no option orders.
3. Should v0.1 use **Robinhood only** for equity data, or add a read-only fallback?
   - Recommendation: add a read-only fallback only after explicit dependency/data-source review. Do not scrape browser data.
4. Should historical analogs start as curated regimes, then become data-driven?
   - Recommendation: yes. Curated v0.1 is faster and safer, with schema-compatible future expansion.

## D — Design

### D1. Target Architecture

```text
torben-finance-radar cron
  -> scripts/equity_research_signal_cron.py
    -> EquityResearchEpisodeRunner
      -> collect market data
      -> collect event/news context
      -> map cross-asset exposures
      -> retrieve historical analogs
      -> run constrained LLM research agent
      -> deterministic signal QA
      -> council / arbiter review when required
      -> produce ResearchSignalPacket
  -> Hermes FinanceQualityGate
  -> Torben FIN card or silence
  -> optional paper/live canary harness
```

### D2. New Files

Ratatosk:

```text
src/ratatosk/intelligence/equity_research_agent.py
src/ratatosk/intelligence/equity_research_contract.py
src/ratatosk/intelligence/equity_event_ingestion.py
src/ratatosk/intelligence/cross_asset_impact.py
src/ratatosk/intelligence/equity_historical_analogs.py
src/ratatosk/intelligence/equity_research_schema.py
scripts/equity_research_signal_cron.py
scripts/equity_live_canary_from_signal.py
config/equity_research_agent.yaml
docs/llm-contracts/equity-research-agent.md
tests/test_intelligence/test_equity_research_agent.py
tests/test_intelligence/test_cross_asset_impact.py
tests/test_intelligence/test_equity_historical_analogs.py
tests/test_scripts/test_equity_research_signal_cron.py
tests/test_scripts/test_equity_live_canary_from_signal.py
```

Hermes:

```text
.hermes/hermes-agent/profiles/torben/scripts/torben_finance_radar.py
.hermes/hermes-agent/hermes_cli/signal_coo/finance.py
.hermes/hermes-agent/tests/test_torben_finance_radar.py
```

### D3. Research Agent Contract

Add `docs/llm-contracts/equity-research-agent.md`.

Contract sections:

- Mission: find asymmetric equity opportunities or explicitly say no trade.
- Persona: skeptical analyst, causal-chain first, falsifiable thesis, prefers silence to weak trades.
- Inputs: event packet, quotes, historical prices, earnings, options-implied probabilities, sentiment, current holdings, risk/halt state, historical analogs.
- Required output JSON schema.
- Rejection rules.
- Examples:
  - Company/sector event against broader market regime, e.g. Apple price increase + market dip as one fixture.
  - Hot tech market + dip + bubble analog comparison.
  - No-data scenario.
  - Generic SPY/QQQ watchlist rejection.

### D4. Research Signal Schema

Proposed `ResearchSignalPacket` fields:

```json
{
  "schema_version": "equity_research_signal.v1",
  "episode_id": "eq-research-...",
  "signal_id": "EQ-20260626-AAPL-001",
  "candidate_id": "EQC-20260626-AAPL-001",
  "generated_at": "ISO-8601",
  "source": "ratatosk_equity_research_agent_v1",
  "mode": "stage_only",
  "primary_symbol": "AAPL",
  "related_symbols": ["QQQ", "XLK", "TSM", "AVGO"],
  "proposed_action": "stage_long | stage_short | stage_hedge | stage_pair | hold",
  "execution_expression": {
    "instrument_type": "equity | etf | research_only",
    "side": "buy | sell | hold",
    "quantity_basis": "tiny_canary | review_only",
    "max_notional_usd": null
  },
  "event_refs": [
    {
      "event_id": "evt-...",
      "title": "Apple announces hardware price increases",
      "source": "...",
      "timestamp": "ISO-8601",
      "url": "..."
    }
  ],
  "market_packet": {
    "quote_timestamp": "ISO-8601",
    "data_freshness_seconds": 120,
    "price": 123.45,
    "index_context": {"SPY": {}, "QQQ": {}, "XLK": {}},
    "volume_context": {},
    "options_context": {}
  },
  "historical_analogs": [
    {
      "regime_id": "tech_2021_compression",
      "period": "2021-11 to 2022-06",
      "similarity": 0.73,
      "matching_features": ["mega-cap concentration", "rate pressure", "breadth divergence"],
      "differences": ["earnings revisions less negative today"],
      "lesson": "Prefer hedge/short only after breadth confirmation."
    }
  ],
  "thesis": "...",
  "edge": 0.14,
  "conviction": 0.68,
  "market_implied_probability": 0.52,
  "risk_notes": ["short squeeze risk", "policy reversal risk"],
  "invalidation_condition": "...",
  "recommended_review_action": "stage paper canary | hold | request live approval",
  "guard_result": {
    "stage_allowed": true,
    "live_allowed": false,
    "reasons": ["shorting not enabled", "live flags off"]
  },
  "mutation_counters": {
    "public_actions_taken": 0,
    "external_mutations": 0,
    "orders_submitted": 0,
    "broker_orders_submitted": 0
  }
}
```

### D5. Episode Runner Design

`EquityResearchEpisodeRunner` should persist every step using `PipelineRun`:

```text
state/pipeline/equity_research/runs/<episode_id>/
  run-context.json
  pipeline-log.jsonl
  step-outputs/
    event_ingestion.json
    market_data.json
    cross_asset_impact.json
    historical_analogs.json
    llm_research.json
    signal_qa.json
    council.json
    research_signal_packet.json
```

This gives auditability and lets Torben reference evidence IDs in the `FIN-*` card.

### D6. Event Ingestion

`equity_event_ingestion.py` should support three v0.1 sources:

1. Fixture events for tests.
2. Existing news gatherer for watchlist/company queries.
3. Manual event packet input for explicit test cases.

For a representative company-event fixture such as Apple price increase, input fixture:

```json
{
  "headline": "Apple announces increased hardware prices",
  "summary": "Apple raised prices on multiple hardware lines as demand concerns hit mega-cap tech.",
  "entities": ["Apple"],
  "tickers": ["AAPL"],
  "event_type": "corporate_action",
  "source_urls": ["fixture://apple-price-increase"],
  "observed_at": "2026-06-26T14:00:00Z"
}
```

### D7. Cross-Asset Impact Mapper

`cross_asset_impact.py` should turn event packets into affected symbols:

- Direct: AAPL.
- Indices/ETFs: QQQ, XLK, SPY.
- Suppliers/semis: TSM, QCOM, AVGO, SWKS, CRUS, ARM, NVDA if event context warrants.
- Consumer hardware peers: MSFT, DELL, HPQ as appropriate.

Output fields:

```json
{
  "primary_symbol": "AAPL",
  "impact_candidates": [
    {
      "symbol": "AAPL",
      "relationship": "direct_company",
      "direction_bias": "headwind",
      "confidence": 0.78,
      "rationale": "Price increase may signal demand elasticity risk."
    },
    {
      "symbol": "QQQ",
      "relationship": "index_exposure",
      "direction_bias": "headwind",
      "confidence": 0.62,
      "rationale": "AAPL mega-cap weight can drag Nasdaq exposure."
    }
  ]
}
```

Initial implementation can use deterministic maps and heuristics, with LLM enrichment later.

### D8. Historical Analog Engine

`equity_historical_analogs.py` should start with curated regimes:

```text
tech_1999_dotcom_peak
tech_2000_dotcom_break
tech_2018_vol_shock
covid_2020_liquidity_crash
spec_tech_2021_peak
tech_2022_rate_compression
ai_concentration_2023_2025
```

Each regime should include:

- date range
- narrative
- features
- market behavior
- trade lessons
- failure modes
- suggested risk posture

For hot-market-then-dip, compute a simple feature vector:

```json
{
  "index_drawdown_from_20d_high": 0.035,
  "qqq_vs_spy_relative_strength": -0.012,
  "breadth_proxy": "degraded | unknown",
  "volatility_proxy": "rising | stable | falling",
  "mega_cap_concentration_flag": true,
  "trend_prior": "hot_market",
  "dip_speed": "fast | slow"
}
```

Then retrieve analogs by weighted feature overlap.

### D9. LLM Research Prompt

The LLM should receive compact, structured inputs and must return strict JSON only.

System constraints:

```text
You are Ratatosk Equity Research Agent v0.1.
Prefer no trade to weak trade.
You cannot approve live orders.
You cannot bypass risk gates.
You must produce falsifiable thesis, edge, conviction, risk notes, invalidation, and guard result.
If evidence is missing, output hold/silent with failed criteria.
Short/hedge ideas are research-only unless shorting is explicitly enabled.
No options execution authority.
```

The prompt should force:

- causal chain
- second-order exposure
- analog comparison
- bull case / bear case
- why now
- invalidation
- explicit no-trade option

### D10. Signal QA Additions

Extend `signal_qa.py` or add an equity-specific wrapper to block:

- missing event refs
- missing quote timestamp
- stale data
- missing historical analog when candidate is short/hedge/regime-based
- generic index candidate without causal thesis
- no source refs
- no invalidation condition
- live order requested without consent/gates
- short candidate when short execution not enabled
- option candidate when options execution not enabled

### D11. Torben Adapter Changes

`build_torben_finance_radar_adapter()` should accept `source=ratatosk_equity_research_agent_v1` packets.

Visible `FIN-*` cards should render:

- signal id
- primary / related symbols
- proposed action
- thesis
- edge / conviction
- historical analogs
- event refs
- market freshness
- invalidation
- guard result
- mutation counters
- "stage-only; no broker order placed" language

### D12. Live Canary From Signal

Add `scripts/equity_live_canary_from_signal.py`.

It must refuse unless all are true:

- `signal_id` exists in a persisted research episode.
- signal source is `ratatosk_equity_research_agent_v1`.
- signal status passed QA.
- candidate is not fixture-only unless explicitly paper mode.
- explicit consent artifact exists for this exact `signal_id`.
- broker readiness passes.
- `RATATOSK_LIVE_TRADING=true` and `ROBINHOOD_LIVE=true` are set intentionally.
- halt/circuit breaker state is clear or explicitly overridden by approved artifact.
- pre-trade guard passes.
- proposed order is tiny notional and allowed instrument type.
- order review is written before placement.

The script should support:

```bash
uv run python scripts/equity_live_canary_from_signal.py \
  --signal-id EQ-... \
  --max-notional-usd 25 \
  --long-only \
  --require-approval-artifact state/approvals/EQ-....json \
  --json
```

## L — Lift Implementation Slices

### L0. No-Code Preconditions

- Review this plan.
- Decide whether v0.1 can emit short/hedge research-only candidates.
- Decide whether to add read-only fallback data source now or later.
- Decide which representative signal-class fixtures to include. Apple-pricing should be one company-event fixture, not a hard-coded binary trade case.

### L1. Contract + Schema

Files:

```text
docs/llm-contracts/equity-research-agent.md
src/ratatosk/intelligence/equity_research_schema.py
tests/test_intelligence/test_equity_research_schema.py
```

Acceptance:

- Valid research signal passes schema.
- Missing thesis/event refs/market freshness fails.
- Live order request in signal schema fails unless guard says blocked.

### L2. Historical Analog v0.1

Files:

```text
src/ratatosk/intelligence/equity_historical_analogs.py
state/research/equity-historical-regimes.seed.json
tests/test_intelligence/test_equity_historical_analogs.py
```

Acceptance:

- Hot-market-then-dip fixture retrieves tech/spec-tech analogs.
- Analog output includes similarity, matching features, differences, and lessons.
- Missing analog on short/hedge candidate blocks QA.

### L3. Cross-Asset Impact Mapper

Files:

```text
src/ratatosk/intelligence/cross_asset_impact.py
tests/test_intelligence/test_cross_asset_impact.py
```

Acceptance:

- Company-event fixture, with Apple price increase as one example, maps direct, index, supplier, and sector exposures when evidence warrants. It may also produce no-trade.
- Private/theme-only outputs are marked non-executable.
- Mapper never approves execution.

### L4. Equity Research Episode Runner

Files:

```text
src/ratatosk/intelligence/equity_research_agent.py
scripts/equity_research_signal_cron.py
tests/test_intelligence/test_equity_research_agent.py
tests/test_scripts/test_equity_research_signal_cron.py
```

Acceptance:

- Degraded data source produces `status=data_source_degraded`, no candidates, zero mutations.
- Representative company-event fixture produces either one stage-only research signal or an explicit no-trade with event refs, analogs/regime context, thesis/no-trade rationale, edge/conviction when applicable, and guard blocked-live.
- Hot-market-dip fixture produces either stage-only hedge/short candidate or no-trade with explicit reasons.
- Every episode writes `state/pipeline/equity_research/runs/<id>/...` step outputs.

### L5. Torben Adapter Consumption

Files:

```text
.hermes/hermes-agent/hermes_cli/signal_coo/finance.py
.hermes/hermes-agent/profiles/torben/scripts/torben_finance_radar.py
.hermes/hermes-agent/tests/test_torben_finance_radar.py
```

Acceptance:

- Torben finance radar prefers `scripts/equity_research_signal_cron.py`.
- No-data/degraded packets stay silent.
- Valid research signal produces exactly one `FIN-*` card.
- Missing analog for short/hedge candidate stays silent.
- All mutation counters remain zero.

### L6. Paper Canary From Research Signal

Files:

```text
src/ratatosk/finance_canary.py
scripts/equity_signal_to_position_canary.py
tests/test_intelligence/test_finance_canary.py
```

Acceptance:

- Paper canary refuses non-research-agent signal unless explicitly fixture mode.
- Paper canary records real Ratatosk paper position/trade-log artifact.
- Artifact records signal id, candidate id, position id, execution mode, guard result, mutation counters, reconciliation status.

### L7. Live Canary Harness

Files:

```text
scripts/equity_live_canary_from_signal.py
tests/test_scripts/test_equity_live_canary_from_signal.py
```

Acceptance:

- Missing approval artifact blocks.
- Missing broker credentials blocks.
- Circuit breaker/halt blocks.
- Live flags off blocks.
- Short/options requests block by default.
- Dry-run mode writes would-place order review without broker mutation.
- Live mode only places after all gates pass.

### L8. Profile Sync + Cron

Files:

```text
/Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py
/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json
```

Acceptance:

- Live Torben cron calls research cron, not legacy v0.1 prompt.
- `hermes -p torben cron run torben-finance-radar` succeeds.
- `hermes -p torben cron run torben-live-profile-verify` passes.
- Gateway remains launchd-supervised.

## C — Check Plan

### Required Unit Tests

Ratatosk:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest \
  tests/test_intelligence/test_equity_research_schema.py \
  tests/test_intelligence/test_equity_historical_analogs.py \
  tests/test_intelligence/test_cross_asset_impact.py \
  tests/test_intelligence/test_equity_research_agent.py \
  tests/test_scripts/test_equity_research_signal_cron.py \
  tests/test_scripts/test_equity_live_canary_from_signal.py \
  tests/test_intelligence/test_finance_canary.py \
  tests/test_engine/test_executor_robinhood.py -q
```

Hermes:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest \
  tests/test_torben_finance_radar.py \
  tests/test_signal_coo.py \
  tests/gateway/test_torben_gtm_reply_router.py \
  tests/gateway/test_platform_base.py -q
```

### Required Fixture Proofs

1. No data / Robinhood auth failure:

```text
wakeAgent=false
signals=[]
external_mutations=0
broker_orders_submitted=0
```

2. Representative company/sector event + broader market move, e.g. Apple price increase + market dip:

```text
one research signal OR explicit no-trade
primary_symbol selected from evidence, not hard-coded
related_symbols includes index/supplier exposure when relevant
historical_analogs or regime-context present
FIN card generated only for a passed signal
no broker mutation
```

3. Hot-market-then-dip:

```text
historical analogs retrieved
candidate is hedge/short research-only OR no-trade with reasons
live execution blocked by default
```

4. Live canary dry-run:

```text
order review artifact written
broker_orders_submitted=0
blocked unless approval + credentials + flags + halt clear
```

5. Live canary real mode:

Only after explicit approval and gates pass:

```text
broker_order_id present
reconciliation_status=broker_position_reconciled or broker_order_open_recorded
rollback_exit_note present
```

### Observability Artifacts

Every research episode should leave:

```text
state/pipeline/equity_research/runs/<episode_id>/run-context.json
state/pipeline/equity_research/runs/<episode_id>/pipeline-log.jsonl
state/pipeline/equity_research/runs/<episode_id>/step-outputs/research_signal_packet.json
state/equity-research/latest.json
state/equity-research/latest.txt
```

Torben should leave:

```text
/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json
/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.txt
```

## Proposed Definition of Done

The build is done when:

1. The cron runs `equity_research_signal_cron.py`, not a generic no-data prompt.
2. A degraded data source stays silent with zero mutations.
3. A representative company-event fixture, with Apple as one example, produces either a research-agent signal with cross-asset mapping and one Torben `FIN-*` card, or an explicit no-trade with evidence-backed reasons.
4. Hot-market-dip fixture retrieves historical analogs and produces a defensible short/hedge research-only candidate or explicit no-trade.
5. `FinanceQualityGate` rejects missing market packet, missing thesis, missing analog for short/hedge, and stale data.
6. Paper canary from the research signal records a real Ratatosk paper position/trade-log artifact.
7. Live canary harness refuses to place unless consent, broker auth, flags, halt/breaker, and pre-trade guard pass.
8. All mutation counters remain zero except in separately approved live canary mode.
9. Handoff artifact and next commands are updated.
10. Live Torben profile verify passes after cron sync.

## Implementation Risks

1. **Data source fragility**
   - Robinhood equity auth is currently unavailable.
   - Mitigation: support degraded/silent path and optionally add reviewed read-only fallback later.

2. **LLM overreach**
   - Risk: model invents causal chains or overstates short conviction.
   - Mitigation: strict schema, source refs, analog requirement, QA gate, council review.

3. **Shorting / options safety**
   - Risk: research output looks executable.
   - Mitigation: stage-only by default, short/options execution disabled, explicit guard result.

4. **Generic market narratives**
   - Risk: every dip becomes “bubble analog.”
   - Mitigation: deterministic features + analog similarity threshold + no-trade path.

5. **Test/env drift**
   - Existing unrelated issue: `test_equity_signal.py::test_signal_has_all_required_fields` can fail after `test_equity_scan.py` because `_load_env()` injects Alpaca credentials from `.env` into process env.
   - Mitigation: do not include that order-dependent broad suite in this slice unless separately fixing test isolation.

## Open Review Decisions

Please review these before build:

1. **Allow research-only short/hedge candidates in v0.1?**
   - Recommended: yes, but execution hard-blocked.

2. **Allow options data as advisory context?**
   - Recommended: yes, no option execution.

3. **Start with curated historical regimes?**
   - Recommended: yes, then later data-driven similarity.

4. **Do we add read-only non-Robinhood market data fallback in this build?**
   - Recommended: defer unless Robinhood auth remains blocked and you want a production data fallback now.

5. **Should the first live canary be long-only even if research suggests short?**
   - Recommended: yes. If research suggests short, stage it and either paper it or ask for separate shorting authorization.

## Paste-Ready Build Goal

```text
Goal: Build Ratatosk Equity Research Agent v0.1 for the Torben Finance Radar using /Users/ericfreeman/.hermes/hermes-agent/docs/goals/torben-ratatosk-equity-research-agent-adlc-plan.md as the implementation plan.

Do not enable live trading, clear circuit breakers, place/cancel broker orders, approve shorting/options/margin, or set live broker env flags unless I separately approve a specific tiny live canary after the gates pass.

Implement ADLC slices L1-L6 first: research contract/schema, historical analog engine, cross-asset mapper, equity research episode runner, Torben adapter consumption, and paper canary from a research-engine signal. Keep L7 live canary harness dry-run/blocked until explicit approval and broker readiness exist.

Acceptance: degraded data stays silent; representative signal-class fixtures include a company/sector event such as Apple price increase but do not hard-code the trade outcome; passed research signals can produce one evidence-backed FIN card; hot-market-dip fixture retrieves historical analogs and emits stage-only short/hedge/no-trade reasoning; paper canary records a real Ratatosk paper position/trade-log artifact; all mutation counters remain zero.
```

---

# Independent Verification and Corrections (reviewer pass)

Last updated: 2026-06-26. This section is an independent re-derivation of the scope. It corrects the plan above where the first reading treated existing, working modules as greenfield. Read this section as authoritative where it conflicts with the original draft.

## Why this matters

The original plan proposed building net-new `cross_asset_impact.py`, `equity_event_ingestion.py`, an event/regime-first runner, and a "research soul" prompt as if none existed. Direct inspection shows Ratatosk already ships most of the event-first research spine. Building parallel modules would duplicate logic, fork the contract, and create two divergent event->equity paths. The real gap is narrower: orchestration into a persisted research-signal episode, an equities regime-analog layer, the shared signal schema, the Torben adapter consumption, and the live-canary-from-signal harness.

## What already exists (verified in repo, do NOT rebuild)

1. Event ingestion. `src/ratatosk/intelligence/macro_event_scanner.py` already scans GDELT and RSS into normalized event payloads (`scan_global_news_events`, `scan_global_rss_events`) across curated topics including `ai_semiconductor`, `monetary_policy`, `trade_policy`, `banking_credit`. Do not build a new `equity_event_ingestion.py`; extend this. Tests: `tests/test_intelligence/test_macro_event_scanner.py` (102 lines).

2. Event normalization. `src/ratatosk/intelligence/macro_events.py` -> `macro_event_research_packet()` normalizes headlines into `MacroEvent` + `EventEquityCandidate` with `direction_bias`, `tradability`, `requires_council`, second-order sectors/tickers. Tests: `tests/test_intelligence/test_macro_events.py`.

3. Cross-asset mapping. `src/ratatosk/intelligence/equity_mapper.py` -> `EquityMapper.map_event_to_equities()` already maps events to correlated equities/ETFs with conviction and an LLM novel-mapping path (`KNOWN_CORRELATIONS` plus `llm_call`). Do not build a new `cross_asset_impact.py`; extend this map (it currently lacks an explicit AAPL->suppliers/semis cluster). Tests: `tests/test_intelligence/test_equity_mapper.py` (92 lines).

4. Event-first evaluator. `src/ratatosk/intelligence/signal_generator.py` -> `macro_research_packet_to_equity_evaluations()` already takes an event/packet, filters to directly tradable US stocks/ETFs, evaluates each via `generate_equity_signal()`, and returns paper-only signals with sizing zeroed and `execution_enabled=False`. This is the event/regime-first path the first reading said was missing. Tests: `tests/test_intelligence/test_macro_event_equity_evaluations.py` (95 lines, 7 pass).

5. Existing CLI. `scripts/macro_event_research.py` already turns headlines/scans into research packets (`--headline`, `--scan-global`, `--write`). It currently stops at packet creation and does NOT call the evaluator or emit a Torben-facing signal. That is the true integration seam.

6. Causal-chain reasoning persona. `src/ratatosk/intelligence/council_personas/causal_chain.py` already prompts for step-by-step event->equity causal validity and second-order effects (supply chain, sector rotation, sentiment spillover, policy feedback). The "skeptical analyst soul" the first reading wanted to author is largely this persona plus `arbiter.py` (the capital-protection challenger gate). Reuse, do not re-author.

7. Historical analogy retrieval. `src/ratatosk/intelligence/situation_memory.py` -> `retrieve_historical_analogies()` (BM25 over past situations with Brier-weighted lessons) plus `historical_priors.py`. These are prediction-market shaped today, but the retrieval mechanism exists and should be reused for the equities analog layer rather than reinvented.

8. Safety gates already wired. `signal_qa.run_signal_qa`, `council.run_council` (equity asset-class profile), `arbiter` (executor calls `_review_with_arbiter` above size threshold), `engine/trading_controls.py`, `engine/risk_manager.py`, `engine/safe_mode.py`. The macro passive signals already set `requires_signal_qa`, `requires_council_or_arbiter`, `requires_risk_manager_before_execution`, `execution_enabled=False`, `paper_only=True`.

## The actual gap (corrected, narrower scope)

After verification, only these are genuinely missing:

- G1. No CLI/cron that runs the full event-first chain end to end: scan/ingest -> packet -> `macro_research_packet_to_equity_evaluations()` -> QA/council -> persisted research-signal packet. `macro_event_research.py` stops at packet creation.
- G2. No equities-specific regime/analog layer (the "hot market then dip vs tech bubble" comparison). `situation_memory` is prediction-market shaped and has no curated equity regime seeds or a market-state feature vector.
- G3. No single shared `ResearchSignalPacket` schema that both Ratatosk emits and Torben/`FinanceQualityGate` consumes. Today there are two shapes: `equity_scan_packet` (symbol-scan) and `macro_event_equity_evaluation_report` (event-first). They are not unified.
- G4. Torben finance radar consumes only `equity_scan_packet.py`. It cannot yet consume the event-first evaluation report.
- G5. No live-canary-from-signal harness that requires a persisted, QA-passed, research-engine signal id and refuses manual/fixture symbols.
- G6. `EquityMapper.KNOWN_CORRELATIONS` has no generalized mega-cap hardware / supplier / index exposure cluster. Apple is one representative example, but the fix should model a reusable company-event exposure class rather than an Apple-only rule.
- G7. No `docs/llm-contracts/` directory exists in either repo. The contract file is genuinely new (the only large net-new doc), but its content should reference the existing `causal_chain` persona and `arbiter`, not duplicate them.

## Corrections to the original file list

Replace the original D2 "New Files" with this. Net-new is far smaller than the draft implied.

Reuse and extend (no new module):
- `src/ratatosk/intelligence/macro_event_scanner.py` (G1 ingestion)
- `src/ratatosk/intelligence/macro_events.py` (event normalization)
- `src/ratatosk/intelligence/equity_mapper.py` (G6: add mega-cap hardware/semis correlation cluster)
- `src/ratatosk/intelligence/signal_generator.py` (`macro_research_packet_to_equity_evaluations` is the orchestration core)
- `src/ratatosk/intelligence/council_personas/causal_chain.py` + `arbiter.py` (the "soul"/skeptic)
- `src/ratatosk/intelligence/situation_memory.py` (analog retrieval mechanism)
- `scripts/macro_event_research.py` (extend to optionally evaluate + emit a signal packet)

Genuinely new (justified):
- `src/ratatosk/intelligence/equity_research_schema.py` - G3, the unified `ResearchSignalPacket` both repos import. Necessary because two divergent packet shapes exist today and Torben cannot consume the event-first one.
- `src/ratatosk/intelligence/equity_regime_analogs.py` + `state/research/equity-historical-regimes.seed.json` - G2, the equities regime/bubble analog layer. Necessary because `situation_memory` has no equity regime seeds or market-state feature vector; the "hot then dip vs bubble" comparison has no home today.
- `scripts/equity_research_signal_cron.py` - G1, the end-to-end episode runner cron entrypoint. Necessary because nothing currently runs ingest->evaluate->QA->emit as one persisted episode.
- `scripts/equity_live_canary_from_signal.py` - G5, gated live canary. Necessary and must refuse non-research-engine signals.
- `docs/llm-contracts/equity-research-agent.md` - G7, references existing persona/arbiter instead of re-authoring them.

Thin changes (not new modules):
- `.hermes/hermes-agent/hermes_cli/signal_coo/finance.py` - teach `build_torben_finance_radar_adapter` to accept the unified `ResearchSignalPacket` (G4).
- `.hermes/hermes-agent/profiles/torben/scripts/torben_finance_radar.py` - prefer `equity_research_signal_cron.py`, keep `equity_scan_packet.py` as fallback.

## Why each new change is necessary (explicit justification)

- `equity_research_schema.py`: removes the two-shape fork (G3). Without one schema, Torben's quality gate cannot enforce the same required fields across symbol-scan and event-first sources, which is exactly the "no thesis / no refs" failure class the DoD forbids.
- `equity_regime_analogs.py` + seed: the user's second example ("market hot then dip, compare to historical tech bubbles") has no implementation surface today. `situation_memory` indexes resolved prediction markets, not equity macro regimes. A deterministic market-state feature vector plus curated regimes is the smallest honest way to support that ask without LLM hallucination.
- `equity_research_signal_cron.py`: the pieces exist but are not chained or persisted as one auditable episode; this is the integration the first reading mislabeled as "build the engine."
- `equity_live_canary_from_signal.py`: required so the live canary is provably sourced from a QA-passed engine signal, not a hand-picked symbol. This is the user's stated Option B requirement.
- `EquityMapper` correlation clusters should model reusable exposure classes (mega-cap hardware, semis/suppliers, index concentration, sector ETFs). The Apple case should be one fixture proving the class, not bespoke Apple logic.
- llm-contract doc: durable mandate so future runs do not re-derive constraints; must point at `causal_chain` + `arbiter` to avoid a third competing reasoning prompt.

## Revised effort estimate

Original draft implied ~8 new modules. Verified scope is ~4 genuinely new files plus targeted extensions to ~6 existing modules. This is roughly a 40 percent reduction in new surface and removes two duplicate event/mapping modules that would have forked existing tested logic.

## Corrections to acceptance/DoD

Add to the Check phase:
- Regression-guard: the existing 7 macro-event-equity evaluation tests and the equity_mapper tests must still pass after extension (they pass today).
- Unification test: one `ResearchSignalPacket` fixture must be accepted by BOTH the Ratatosk emitter and the Hermes `FinanceQualityGate` adapter.
- Determinism test: the representative company-event fixture, with Apple as one example, must map through reusable supplier/semis/index exposure classes via `KNOWN_CORRELATIONS` without requiring the LLM novel path. It must not assert a predetermined trade direction.

## Uncertainties / decisions still open

1. Reuse `situation_memory` retrieval for equity regimes, or keep `equity_regime_analogs.py` fully separate? Recommendation: separate module for the seed/feature-vector, but reuse the BM25 retrieval helper to avoid a second retrieval engine.
2. Should the unified schema supersede `equity_scan_packet` entirely, or wrap it? Recommendation: wrap first (adapter), supersede later, to avoid breaking the currently-green Torben path.
3. Confirm whether `arbiter` alone is sufficient as the skeptic gate for event-first equity, or whether a dedicated equity-research persona is warranted. Recommendation: start with `causal_chain` + `arbiter`; add a persona only if review shows gaps.


## User Clarification: Avoid Apple-as-Binary-Rule Bug

Eric clarified that the Apple example is not meant to become a binary use case. This is now a tracked scope bug to fix before implementation.

Bug: the draft could be misread as `Apple price increase + market dip -> fixed trade candidate`. That is wrong.

Correct behavior:

- Apple is one representative fixture in a broader signal-class suite.
- The engine must evaluate company, sector, macro, and regime signals against the broader market.
- A company event may imply AAPL, suppliers, ETFs, hedge/short candidates, or no trade.
- The acceptance target is evidence-backed reasoning and safe gating, not a predetermined symbol/action.
- Tests must assert schema, causal chain quality, exposure mapping, analog/regime use, and guard behavior. They must not assert `if Apple then trade`.

Implementation implication: build reusable exposure classes and market-regime reasoning, then use Apple as one fixture to prove the class.

## Net verdict

Agent 2's ADLC structure, safety posture, schema sketch, slices, and live-canary gating are sound and worth keeping. The one substantive error is treating the event-first research spine as missing. It exists, is tested, and is not wired to cron or Torben. Re-scope L3/L4 from "build new mapper + ingestion" to "wire and extend existing macro-event spine," keep L1/L2/L5/L6/L7, and the build gets smaller, safer, and faster.
