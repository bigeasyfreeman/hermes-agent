# Torben/Ratatosk Finance Radar Production Handoff

Last updated: 2026-06-26T20:07:00Z / 2026-06-26 16:07 EDT.

## Objective

Productionize the Torben-facing finance radar using `docs/goals/torben-ratatosk-finance-production-dod-goal.md` as the definition of done. Default mode remains stage-only: no live broker orders, no broker cancellations, no live trading env flags, no clearing halts/circuit breakers.

## Current cutline

Implemented in this slice:

- Gateway final responses are coerced at adapter boundaries so dict-shaped shortcut payloads cannot reach media extraction as dicts.
- `FinanceQualityGate` suppresses high-scoring but no-live-data/generic candidates before Signal wake and records `silent_reason`, `quality_gate_version`, failed criteria, and suppressed-candidate metadata.
- Torben finance radar now prefers Ratatosk `scripts/equity_scan_packet.py` over the legacy no-data Robinhood v0.1 LLM cron prompt. The legacy path is retained only behind `TORBEN_FINANCE_USE_LEGACY_ROBINHOOD_V01=1` as a control canary.
- Ratatosk now has:
  - `scripts/equity_scan_packet.py` / `ratatosk.equity_scan_packet` for real equity scan evidence packets with zero mutation counters.
  - `scripts/robinhood_equity_readiness.py` / `ratatosk.robinhood_equity_readiness` for no-secret quote/positions/earnings/options readiness reporting.
  - `scripts/equity_signal_to_position_canary.py` / `ratatosk.finance_canary` for stage-only fixture-equivalent signal-to-paper-position artifacts.
- Live Torben profile script at `/Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py` was synced from the repo copy.
- The signal-to-position canary now records a GENUINE Ratatosk paper position + trade-log entry through the real `ratatosk.state.positions` module (isolated `paper-portfolio` store), then reconciles by reading the position back. It no longer fabricates a position dict. Live `state/positions.json` is never mutated.
- Gateway supervision is now genuinely fixed: launchd `kickstart` (after `launchctl enable`) supervises the gateway even though `launchctl bootstrap` returns the documented macOS 26 exit-5 I/O error. KeepAlive auto-restart was proven by killing the supervised pid and observing launchd respawn it. The stale `.gateway-launchd-unsupported` marker was removed and `hermes -p torben gateway status` now reports `Gateway is supervised by launchd`.

## Runtime proof captured

- `HERMES_HOME=/Users/ericfreeman/.hermes/profiles/torben TORBEN_FINANCE_RADAR_PREVIEW=1 .hermes/hermes-agent/venv/bin/python .hermes/profiles/torben/scripts/torben_finance_radar.py`
  - Result: stdout bytes `0`; profile artifact stayed silent.
  - Artifact: `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json`
  - Key fields: `wakeAgent=false`, `silent_reason="Ratatosk equity data source is degraded; no FIN card staged"`, `quality_gate_version="finance_quality_gate_v1"`, `candidate_count=0`, `selected_count=0`, `external_mutations=0`, `orders_submitted=0`, `broker_orders_submitted=0`.
  - Source command was `uv run python scripts/equity_scan_packet.py --json --watchlist state/equity-watchlist.json`; stderr showed current Robinhood auth/data failure `<urlopen error [Errno 61] Connection refused>`.
- `UV_PROJECT_ENVIRONMENT=venv uv run python scripts/robinhood_equity_readiness.py --json`
  - Result: `ready=false`, `failure_kinds=["missing_equity_credentials"]`, `robin_stocks=true`, `yfinance=false`, `ROBINHOOD_LIVE=false`, `RATATOSK_LIVE_TRADING=false`, `secrets_redacted=true`.
- `UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_signal_to_position_canary.py --fixture --json`
  - Result: `status=passed`, `execution_mode=paper`, `order_id=null`, `reconciliation_status=paper_position_recorded`, all mutation counters zero. Latest verified position id: `paper-finance-pos-f5ff6225e022de33`.
  - Artifacts: `/Users/ericfreeman/ratatosk/state/finance-canaries/eqsig-fixture-aapl-2026-06-26.json` and `/Users/ericfreeman/ratatosk/state/finance-canaries/latest.json`.
- `hermes -p torben gateway status`
  - Result: `Gateway is supervised by launchd (PID 38193)`, auto-start/restart available. Verified after `launchctl enable gui/501/ai.hermes.gateway-torben` + `launchctl kickstart -p`. KeepAlive respawn proven (killed pid 38086 -> launchd respawned pid 38193).
- `hermes -p torben cron run torben-finance-radar`
  - Result: succeeded; live profile artifact `wakeAgent=false`, `silent_reason="Ratatosk equity data source is degraded; no FIN card staged"`, `quality_gate_version="finance_quality_gate_v1"`, all mutation counters zero, source command `uv run python scripts/equity_scan_packet.py --json --watchlist state/equity-watchlist.json`.
- `hermes -p torben cron run torben-live-profile-verify`
  - Result: `status=pass`, `errors count: 0` (finance radar not flagged).
- `scripts/robinhood_v01_validate.py --json`
  - Result: `ready=true`, `external_mutations=0`, stage allowed, live order BLOCKED for: missing human consent, circuit breaker tripped at 43.1% drawdown, `RATATOSK_LIVE_TRADING` disabled.
- Genuine paper canary (`scripts/equity_signal_to_position_canary.py --fixture --json`)
  - Result: `status=passed`, `reconciliation_status=paper_position_recorded`, real records in `state/finance-canaries/paper-portfolio/positions.json` (`position_opened`) and `trade-log.jsonl` (`paper_trade_executed`), all mutation counters zero, live portfolio untouched.
- DoD item 8 fixture-FIN proof: a real `build_equity_scan_packet` fixture -> `build_torben_finance_radar_adapter` produced exactly one `FIN-20260626-001` stage-only card with zero mutations and no "No thesis provided".

## Tests run

Hermes:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
venv/bin/python -m pytest tests/gateway/test_torben_gtm_reply_router.py tests/gateway/test_platform_base.py tests/test_torben_finance_radar.py tests/test_signal_coo.py -q
# 240 passed, 2 skipped
```

Ratatosk:

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/test_intelligence/test_pipeline.py tests/test_intelligence/test_equity_full_pipeline.py tests/test_intelligence/test_equity_scan_packet.py tests/test_intelligence/test_robinhood_equity_readiness.py tests/test_intelligence/test_finance_canary.py tests/test_engine/test_executor_robinhood.py -q
# 27 passed
```

## Dirty files touched for this goal

Hermes repo:

- `gateway/run.py`
- `hermes_cli/signal_coo/finance.py`
- `profiles/torben/scripts/torben_finance_radar.py`
- `tests/gateway/test_torben_gtm_reply_router.py`
- `tests/test_torben_finance_radar.py`
- `docs/goals/torben-ratatosk-finance-production-dod-goal.md` (pre-existing untracked goal file)
- `docs/goals/torben-ratatosk-finance-production-handoff.md`

Live Torben profile:

- `/Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py`
- `/Users/ericfreeman/.hermes/profiles/torben/state/torben-finance-radar-latest.json`

Ratatosk repo/runtime:

- `src/ratatosk/equity_scan_packet.py`
- `src/ratatosk/robinhood_equity_readiness.py`
- `src/ratatosk/finance_canary.py`
- `scripts/equity_scan_packet.py`
- `scripts/robinhood_equity_readiness.py`
- `scripts/equity_signal_to_position_canary.py`
- `tests/test_intelligence/test_equity_scan_packet.py`
- `tests/test_intelligence/test_robinhood_equity_readiness.py`
- `tests/test_intelligence/test_finance_canary.py`
- `state/finance-canaries/latest.json`
- `state/finance-canaries/eqsig-fixture-aapl-2026-06-26.json`

## Completion verdict

The goal's DoD is complete as a stage-only production loop. Robinhood equity credentials are absent (`failure_kinds=["missing_equity_credentials"]`), so the live equity scan correctly degrades and stays silent instead of fabricating FIN cards. That satisfies the DoD's explicit degraded-state branch. `yfinance` remains intentionally uninstalled because the DoD makes it optional ("may be") and only permitted after separate install/test/marking as non-executable research data. A live broker canary remains out of scope without separate explicit approval; the default genuine paper canary passed and left durable Ratatosk position/trade-log artifacts.

## Pre-existing unrelated issue observed (not part of this goal)

- `tests/test_intelligence/test_equity_signal.py::test_signal_has_all_required_fields` fails when run AFTER `test_equity_scan.py` in the same process. Root cause: `run_equity_scan()` -> `pipeline._load_env()` injects `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` from `~/ratatosk/.env` (dated 2026-04-05) into `os.environ`, so the later test sees `platform=alpaca` instead of `robinhood`. It passes in isolation, is unrelated to finance-radar code, is not in any DoD verifier command, and is not triggered by the new finance test files. Fix (if pursued) belongs to equity-signal test isolation, not this goal.

## Next commands

```bash
cd /Users/ericfreeman/ratatosk
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/robinhood_equity_readiness.py --json
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_scan_packet.py --json
UV_PROJECT_ENVIRONMENT=venv uv run python scripts/equity_signal_to_position_canary.py --fixture --json

cd /Users/ericfreeman/.hermes/hermes-agent
HERMES_HOME=/Users/ericfreeman/.hermes/profiles/torben TORBEN_FINANCE_RADAR_PREVIEW=1 venv/bin/python /Users/ericfreeman/.hermes/profiles/torben/scripts/torben_finance_radar.py
venv/bin/python -m pytest tests/gateway/test_torben_gtm_reply_router.py tests/gateway/test_platform_base.py tests/test_torben_finance_radar.py tests/test_signal_coo.py -q

hermes -p torben gateway status
hermes -p torben cron list
```
