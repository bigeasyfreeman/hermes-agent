# Torben Loop-Engineering Day-Trader Validation

This validation artifact is for `LE-DT-VAL`. It records the safe validation boundary for the Torben/Ratatosk loop-engineering day-trader work.

## Scope

- Validate stage-only, paper, dry-run, and read-only finance-loop behavior.
- Validate Ponytail/Council review evidence through a direct verifier.
- Validate Torben profile health and finance risk-monitor silence.
- Preserve `RATATOSK_LIVE_TRADING=0`, `ROBINHOOD_LIVE=0`, and `ROBINHOOD_EQUITY_LIVE=0`.
- Do not clear trading halt or circuit-breaker state.
- Do not review, place, submit, or simulate a live broker order through broker mutation APIs.

## Required Gates

Run from the remote host unless noted otherwise:

```bash
cd /Users/ericfreeman/ratatosk
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=venv \
  uv run python scripts/equity_go_live_rehearsal.py --json
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=venv \
  uv run python scripts/equity_go_live_packet.py --latest-research-candidate --skip-mcp-live-probe --json
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=venv \
  uv run python scripts/equity_evidence_wait_packet.py --json
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=venv \
  uv run python scripts/equity_review_gate_verify.py --json
```

Expected result:

- `status=pass`.
- `checks.ponytail_present=true`.
- `checks.council_reviews_present=true`.
- `checks.live_profile_clean=true`.
- `checks.risk_monitor_quiet_wait=true`.
- `checks.role_separation_satisfied=true`.
- `checks.retrospective_verifier_pass=true`.
- `checks.live_status_safely_blocked=true`.
- `checks.evidence_wait_packet_pass=true`.
- `checks.go_live_operator_packet_fail_closed=true`.
- `checks.go_live_rehearsal_matrix_pass=true`.
- `broker_orders_submitted=0`.
- `orders_submitted=0`.
- `public_actions_taken=0`.
- `external_mutations=0`.

ADLC readiness:

```bash
cd /Users/ericfreeman/Downloads/adlc
bin/adlc validate-artifact --schema build-brief --input docs/build-briefs/torben-loop-engineering-day-trader.json --json
bin/adlc emit-work-items --target linear --build-brief docs/build-briefs/torben-loop-engineering-day-trader.json --dry-run --require-ready --json
```

Torben canaries:

```bash
cd /Users/ericfreeman/.hermes/hermes-agent
UV_PROJECT_ENVIRONMENT=.venv uv run pytest tests/test_signal_coo_live_profile_verify.py tests/test_torben_finance_risk_monitor.py -q
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=.venv uv run hermes -p torben cron run torben-finance-loop-heartbeat
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=.venv uv run hermes -p torben cron run torben-finance-risk-monitor
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=.venv uv run hermes -p torben cron run torben-finance-risk-monitor
RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 UV_PROJECT_ENVIRONMENT=.venv uv run hermes -p torben cron run torben-live-profile-verify
```

The first risk-monitor run after a heartbeat refresh may wake once because the risk fingerprint changed. The second risk-monitor run is the steady-state silence check and must leave `wakeAgent=false` before `equity_review_gate_verify.py` is run.

## Latest Evidence Targets

- Review-gate runtime artifact: `/tmp/torben-loop-engineering-resume/review-gate-verifier-runtime-20260701.json`.
- Focused review-gate tests: `/tmp/torben-loop-engineering-resume/review-gate-verifier-focused-tests-20260701.txt`.
- Affected Ratatosk tests: `/tmp/torben-loop-engineering-resume/review-gate-verifier-affected-tests-20260701.txt`.
- Torben profile summary after the review gate: `/tmp/torben-loop-engineering-resume/torben-profile-after-review-gate-verifier-summary-20260701.json`.
- Steady-state review-gate runtime artifact: `/tmp/torben-loop-engineering-resume/review-gate-verifier-runtime-steady-20260701.json`.
- Go-live rehearsal artifact: `/tmp/torben-loop-engineering-resume/go-live-rehearsal-20260701.json`.
- Go-live operator packet artifact: `/tmp/torben-loop-engineering-resume/go-live-operator-packet-20260701.json`.
- Evidence-wait packet artifact: `/tmp/torben-loop-engineering-resume/evidence-wait-packet-20260701.json`.
- Release-aware review-gate refresh validator artifact: `/tmp/torben-loop-engineering-resume/review-gate-refresh-validate-with-hermes-20260702.json`.
- ADLC validation output: `/tmp/torben-loop-engineering-resume/adlc-validate-review-gate-verifier-20260701.json`.
- ADLC work-item output: `/tmp/torben-loop-engineering-resume/adlc-emit-review-gate-verifier-20260701.json`.

## Live-Go Status

This validation can prove production readiness for the stage-only review-gate slice. It cannot prove live broker readiness. The evidence-wait packet proves the current deterministic action is to wait for paper/OOS evidence or new market data with no bounded paper-collection budget, `release_evaluation.status=hold_wait`, and `release_signal_count=0`. If Hermes canaries create fresh paper/OOS evidence, `LE-DT-VAL` uses `/Users/ericfreeman/ratatosk/scripts/equity_review_gate_refresh_validate.py` to record the release-detect packet, refresh paper performance, calibration, experiment evaluation, optimizer, live status, stop condition, isolated risk monitor, Torben profile state, go-live rehearsal, go-live operator packet, and final review gate, then requires the final evidence-wait packet to return to `hold_wait`. The go-live rehearsal matrix proves the gate behavior in isolated examples; it does not grant live authority. The go-live operator packet must remain `status=blocked`, `ready_to_submit=false`, and `commands.one_shot_live_submit=null` until exact approval, active halt/circuit review, live flags, paper/OOS gates, and human risk acknowledgements are satisfied with fresh evidence.
