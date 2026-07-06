from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from hermes_cli.signal_coo.action_ledger import ActionLedger
from hermes_cli.signal_coo.finance import build_torben_finance_radar_adapter
from profiles.torben.scripts import torben_finance_loop_heartbeat, torben_finance_radar


def _ratatosk_run(*, score: float = 0.82, can_place_order_directly: bool = False) -> dict:
    return {
        "status": "llm_completed",
        "source": "ratatosk_equity_scan_v1",
        "phase": "open",
        "scan_timestamp": "2026-06-26T13:59:00Z",
        "source_freshness": {"status": "live_market_packet", "quote_timestamp": "2026-06-26T13:59:00Z"},
        "markets": [
            {
                "symbol": "SPY",
                "price": 612.34,
                "bid": 612.30,
                "ask": 612.38,
                "volume": 1234567,
                "quote_timestamp": "2026-06-26T13:59:00Z",
                "data_freshness": "live_market_packet",
            }
        ],
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
        "llm_error": None,
        "llm_run": {
            "run_id": "llm-test-001",
            "cron_tick_id": "ratatosk-robinhood-v01-open:2026-06-26T09:45:00-04:00",
            "phase": "open",
            "token_budget": 2500,
            "order_tools_available": False,
        },
        "llm_result": {
            "market_regime": "risk-on but confirmation required",
            "no_trade_reason": "candidate is for review only; no order tools exposed",
            "watchlist": ["SPY"],
            "signals": [
                {
                    "symbol": "SPY",
                    "confidence": score,
                    "can_trade_directly": False,
                    "summary": "Broad-market confirmation signal.",
                }
            ],
            "candidates": [
                {
                    "symbol": "SPY",
                    "score": score,
                    "edge": 0.18,
                    "conviction": score,
                    "market_implied_probability": 0.54,
                    "direction": "long",
                    "proposed_action": "review long equity",
                    "instrument_type": "equity",
                    "candidate_type": "watchlist_only",
                    "can_place_order_directly": can_place_order_directly,
                    "eligible_for_pretrade_guard": False,
                    "thesis": "SPY confirmed trend breadth with fresh quote support and defined downside.",
                    "research_note": "SPY confirmed trend breadth with fresh quote support and defined downside.",
                    "source_refs": ["quote:SPY:2026-06-26T13:59:00Z", "news:breadth-20260626"],
                    "risk_notes": ["Gap risk if breadth reverses after open."],
                    "invalidation_condition": "Hold if SPY loses prior session VWAP on rising volume.",
                    "recommended_review_action": "Review paper canary only; do not place a broker order.",
                    "guard_result": {
                        "status": "stage_only_blocked",
                        "orders_submitted": 0,
                        "broker_orders_submitted": 0,
                        "external_mutations": 0,
                    },
                    "constraints": ["cash-only", "no-margin", "no-shorts"],
                    "quote_timestamp": "2026-06-26T13:59:00Z",
                    "data_freshness": "live_market_packet",
                }
            ],
        },
    }


def test_finance_radar_stages_high_score_candidate_without_broker_mutation(tmp_path):
    payload = build_torben_finance_radar_adapter(
        _ratatosk_run(),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["selected_count"] == 1
    assert payload["public_actions_taken"] == 0
    assert payload["external_mutations"] == 0
    assert payload["orders_submitted"] == 0
    assert payload["broker_orders_submitted"] == 0
    assert "No order was placed" in payload["text"]
    action = payload["actions"][0]
    assert action["handle"] == "FIN-20260626-001"
    assert action["scope"] == "fin"
    assert action["status"] == "staged"
    state = action["executor_state"]
    assert state["mutation_type"] == "broker_order_candidate"
    assert state["mutation_status"] == "stage_only_not_ordered"
    assert state["provider"] == "ratatosk_equity_scan_v1"
    assert state["order_tools_available"] is False
    assert state["orders_submitted"] == 0
    assert state["external_mutations"] == 0
    assert "TBC-DECIDE-LIVE-FINANCE" in state["execution_blocked_until"]
    assert payload["quality_gate_version"] == "finance_quality_gate_v1"
    assert payload["quality_gate_failed_criteria"] == []
    assert "No thesis provided" not in payload["text"]
    assert "Edge/conviction:" in payload["text"]
    assert "Evidence refs:" in payload["text"]


def test_finance_radar_silent_for_below_threshold_watchlist(tmp_path):
    payload = build_torben_finance_radar_adapter(
        _ratatosk_run(score=0.58),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["reason"] == "no fresh Ratatosk candidate reached the 0.70 review threshold"
    assert payload["selected_count"] == 0
    assert payload["text"] == ""
    assert payload["llm_judge"]["invoked"] is True
    assert payload["llm_judge"]["order_tools_available"] is False
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_dedupes_delivered_candidate(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.json")
    state_path = tmp_path / "finance-state.json"
    now = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)

    first = build_torben_finance_radar_adapter(
        _ratatosk_run(),
        ledger=ledger,
        state_path=state_path,
        now=now,
    )
    second = build_torben_finance_radar_adapter(
        _ratatosk_run(),
        ledger=ledger,
        state_path=state_path,
        now=now,
    )

    assert first["wakeAgent"] is True
    assert second["wakeAgent"] is False
    assert second["suppressed_duplicate_count"] == 1


def test_finance_radar_rejects_direct_order_candidate_even_when_score_is_high(tmp_path):
    payload = build_torben_finance_radar_adapter(
        _ratatosk_run(score=0.91, can_place_order_directly=True),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["selected_count"] == 0
    assert payload["silent_reason"] == "candidate failed finance quality gate"
    assert "unsafe_direct_order_capability" in payload["quality_gate_failed_criteria"]
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_fails_loud_if_ratatosk_reports_stage_only_mutation(tmp_path):
    run = _ratatosk_run(score=0.91)
    run["external_mutations"] = 1
    run["orders_submitted"] = 1

    payload = build_torben_finance_radar_adapter(
        run,
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["status"] == "fail_closed"
    assert payload["reason"] == "ratatosk_reported_stage_only_mutation"
    assert payload["actions"] == []
    assert payload["external_mutations"] == 1
    assert payload["broker_orders_submitted"] == 1
    assert "I did not stage a FIN review card" in payload["text"]


def test_finance_radar_silences_no_live_data_spy_watchlist_even_above_threshold(tmp_path):
    run = _ratatosk_run(score=0.91)
    run["llm_result"]["market_regime"] = "unknown_research_only_no_live_market_data"
    run["llm_result"]["no_trade_reason"] = "No live market data; generic watchlist only."
    candidate = run["llm_result"]["candidates"][0]
    candidate.pop("thesis", None)
    candidate.pop("research_note", None)
    candidate.pop("source_refs", None)
    candidate.pop("quote_timestamp", None)
    candidate.pop("data_freshness", None)
    candidate["risk_notes"] = ["research only; no live data"]
    run["markets"] = []

    payload = build_torben_finance_radar_adapter(
        run,
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["selected_count"] == 0
    assert payload["silent_reason"] == "candidate lacked live or fixture-equivalent market evidence"
    assert payload["quality_gate_version"] == "finance_quality_gate_v1"
    assert "run_reports_no_live_market_data" in payload["quality_gate_failed_criteria"]
    assert "missing_thesis" in payload["quality_gate_failed_criteria"]
    assert payload["suppressed_candidates"][0]["quality_gate"]["passed"] is False


def test_finance_radar_maps_real_equity_scan_signal_to_one_fin_card(tmp_path):
    run = {
        "task": "ratatosk_equity_scan_packet",
        "source": "ratatosk_equity_scan_v1",
        "status": "success",
        "scan_timestamp": "2026-06-26T14:00:00Z",
        "source_freshness": {"status": "fixture_equivalent", "quote_timestamp": "2026-06-26T14:00:00Z"},
        "markets": [
            {
                "symbol": "AAPL",
                "price": 210.12,
                "bid": 210.10,
                "ask": 210.15,
                "quote_timestamp": "2026-06-26T14:00:00Z",
                "data_freshness": "fixture_equivalent",
            }
        ],
        "signals": [
            {
                "market_id": "AAPL",
                "action": "BUY",
                "edge": 0.22,
                "conviction": 0.83,
                "market_implied_probability": 0.61,
                "market_price": 210.12,
                "thesis": "AAPL has fresh quote support plus earnings catalyst asymmetry.",
                "source_refs": ["quote:AAPL:2026-06-26T14:00:00Z", "earnings:AAPL:2026Q2"],
                "risk_notes": ["Earnings gap risk; paper-only until guard pass."],
                "invalidation_condition": "Invalidate on below-prior-close breakdown.",
                "recommended_review_action": "Stage a paper canary position.",
                "guard_result": {"status": "stage_only_blocked", "orders_submitted": 0},
            }
        ],
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }

    payload = build_torben_finance_radar_adapter(
        run,
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["selected_count"] == 1
    assert payload["actions"][0]["handle"] == "FIN-20260626-001"
    assert payload["actions"][0]["executor_state"]["candidate"]["symbol"] == "AAPL"
    assert "AAPL BUY" in payload["text"]
    assert "Stage a paper canary position" in payload["text"]
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_degraded_equity_source_stays_silent(tmp_path):
    run = {
        "task": "ratatosk_equity_scan_packet",
        "source": "ratatosk_equity_scan_v1",
        "status": "data_source_degraded",
        "scan_timestamp": "2026-06-26T14:00:00Z",
        "source_freshness": {"status": "auth_failed", "error_kinds": ["auth_failed"]},
        "errors": ["Robinhood authentication failed: connection refused"],
        "markets": [],
        "signals": [],
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }

    payload = build_torben_finance_radar_adapter(
        run,
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["silent_reason"] == "Ratatosk equity data source is degraded; no FIN card staged"
    assert payload["candidate_count"] == 0
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_run_ratatosk_command_defaults_to_live_disabled_env(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_run(command, *, cwd, env, capture_output, text, timeout, check):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["env"] = env
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        captured["check"] = check
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.delenv("RATATOSK_LIVE_TRADING", raising=False)
    monkeypatch.delenv("ROBINHOOD_LIVE", raising=False)
    monkeypatch.setattr(torben_finance_radar.subprocess, "run", fake_run)

    payload, refresh = torben_finance_radar._run_ratatosk_command(
        ["uv", "run", "python", "scripts/probe.py"],
        root=Path(tmp_path),
        timeout_seconds=12,
    )

    assert payload["status"] == "ok"
    assert refresh["status"] == "success"
    assert refresh["live_safety_env"] == {
        "RATATOSK_LIVE_TRADING": "0",
        "ROBINHOOD_LIVE": "0",
        "ROBINHOOD_EQUITY_LIVE": "0",
    }
    assert captured["cwd"] == Path(tmp_path)
    assert captured["timeout"] == 12
    assert captured["env"]["RATATOSK_LIVE_TRADING"] == "0"
    assert captured["env"]["ROBINHOOD_LIVE"] == "0"
    assert captured["env"]["ROBINHOOD_EQUITY_LIVE"] == "0"
    assert captured["env"]["UV_PROJECT_ENVIRONMENT"] == "venv"
    assert captured["env"]["RATATOSK_ROOT"] == str(tmp_path)


def test_run_ratatosk_command_preserves_explicit_live_env_overrides(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_run(command, *, cwd, env, capture_output, text, timeout, check):
        captured["env"] = env
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.setenv("RATATOSK_LIVE_TRADING", "paper-review-only")
    monkeypatch.setenv("ROBINHOOD_LIVE", "paper-review-only")
    monkeypatch.setattr(torben_finance_radar.subprocess, "run", fake_run)

    torben_finance_radar._run_ratatosk_command(
        ["uv", "run", "python", "scripts/probe.py"],
        root=Path(tmp_path),
        timeout_seconds=12,
    )

    assert captured["env"]["RATATOSK_LIVE_TRADING"] == "paper-review-only"
    assert captured["env"]["ROBINHOOD_LIVE"] == "paper-review-only"


def _research_signal_packet(*, proposed_action: str = "stage_long") -> dict:
    return {
        "schema_version": "equity_research_signal.v1",
        "episode_id": "eq-research-test",
        "signal_id": "EQ-20260626-AAPL-001",
        "candidate_id": "EQC-20260626-AAPL-001",
        "generated_at": "2026-06-26T14:00:00Z",
        "source": "ratatosk_equity_research_agent_v1",
        "mode": "stage_only",
        "status": "qa_passed",
        "primary_symbol": "AAPL" if proposed_action != "stage_hedge" else "QQQ",
        "related_symbols": ["QQQ", "XLK"],
        "proposed_action": proposed_action,
        "signal_family": "regime_hedge_research" if proposed_action == "stage_hedge" else "company_event",
        "execution_expression": {
            "instrument_type": "research_only" if proposed_action == "stage_hedge" else "equity",
            "side": "hold" if proposed_action == "stage_hedge" else "buy",
            "quantity_basis": "review_only",
            "max_notional_usd": None,
        },
        "event_refs": [
            {
                "event_id": "evt-fixture-company-hardware-pricing",
                "title": "Apple hardware pricing fixture",
                "source": "fixture",
                "timestamp": "2026-06-26T14:00:00Z",
                "url": "fixture://company-hardware-pricing",
            }
        ],
        "market_packet": {
            "quote_timestamp": "2026-06-26T14:00:00Z",
            "data_freshness_seconds": 60,
            "data_freshness": "fixture_equivalent",
            "price": 210.12,
        },
        "historical_analogs": [
            {
                "regime_id": "ai_concentration_2023_2025",
                "period": "2023-01 to 2025-12",
                "similarity": 0.78,
                "matching_features": ["trend_prior: hot_market matches hot_market"],
                "differences": [],
                "trade_lessons": ["Demand confirmation matters."],
                "risk_posture": "research-only",
            }
        ],
        "thesis": "AAPL pricing power is evidence-backed but stage-only because broader market risk remains high.",
        "edge": 0.11,
        "conviction": 0.74,
        "market_implied_probability": 0.55,
        "risk_notes": ["Demand elasticity and market selloff risk."],
        "invalidation_condition": "Hold if AAPL loses relative strength.",
        "recommended_review_action": "Stage paper canary only.",
        "guard_result": {
            "stage_allowed": True,
            "live_allowed": False,
            "status": "stage_only_blocked",
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
        "mutation_counters": {
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _research_agent_run(packet: dict | None = None, *, status: str = "success") -> dict:
    packet = packet if packet is not None else _research_signal_packet()
    candidates = [packet] if packet.get("status") == "qa_passed" else []
    return {
        "task": "ratatosk_equity_research_signal_cron",
        "source": "ratatosk_equity_research_agent_v1",
        "status": status,
        "episode_id": packet.get("episode_id", "eq-research-test"),
        "generated_at": "2026-06-26T14:00:00Z",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "research_signal_packet": packet,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _sample_acquisition_plan() -> dict:
    return {
        "status": "needs_paper_samples",
        "target_new_samples": 8,
        "non_overrepresented_sample_target": 8,
        "concentration_relief_samples_needed": 8,
        "avoid_symbols": ["AAPL"],
        "preferred_existing_symbols": ["AMZN", "GOOGL", "NVDA"],
        "live_order_authority": "none",
    }


def _calibration_repair_plan() -> dict:
    return {
        "policy_id": "paper_feedback_calibration_repair_plan_v1",
        "status": "needs_repair_samples",
        "mode": "paper_feedback_only",
        "target_new_samples": 3,
        "target_total_sample_count": 90,
        "target_total_calibrated_sample_count": 90,
        "baseline_sample_count": 87,
        "baseline_calibrated_sample_count": 87,
        "target_repair_sample_count": 3,
        "repair_samples_collected": 0,
        "repair_samples_remaining": 3,
        "repair_reason_ids": ["paper_calibration_gate_failed:brier_score"],
        "blocking_reasons": ["paper_calibration_gate_failed:brier_score"],
        "avoid_symbols": ["AMZN", "GOOGL"],
        "preferred_existing_symbols": ["MSFT", "COIN", "AAPL"],
        "preferred_symbol_details": [
            {
                "symbol": "MSFT",
                "repair_priority_rank": 1,
                "repair_priority_score": 4.8,
                "preference_sources": ["positive_paper_return"],
                "calibration_sample_count": 5,
                "performance_sample_count": 5,
                "brier_score": 0.09909,
                "realized_win_rate": 1.0,
                "average_return": 0.014,
                "sharpe_ratio": 4.65,
                "live_order_authority": "none",
            },
        ],
        "concentration_limited_symbols": ["AMZN", "GOOGL"],
        "high_brier_symbols": ["AMZN", "GOOGL"],
        "sample_acquisition_avoid_symbols": ["AMZN", "GOOGL"],
        "live_order_authority": "none",
    }


def _historical_policy_coverage() -> dict:
    return {
        "status": "covered",
        "coverage_basis": "historical_strategy_policy.candidate_constraints.eligible_symbols",
        "policy_id": "historical_strategy_policy_v1",
        "historical_strategy_search_status": "sufficient",
        "repair_plan_status": "needs_repair_samples",
        "target_new_samples": 3,
        "eligible_symbols": ["AAPL", "AMD", "AMZN", "ARM", "COIN", "GOOGL", "MSFT", "NVDA"],
        "repair_preferred_symbols": ["MSFT", "COIN", "AAPL"],
        "missing_repair_preferred_symbols": [],
        "missing_count": 0,
        "live_order_authority": "none",
    }


def _loop_tick_run() -> dict:
    return {
        "task": "equity_trading_loop_tick",
        "tick_id": "equity-loop-20260629T204307271641Z",
        "status": "completed",
        "research_mode": "batch",
        "research": {
            "status": "no_actionable_signal",
            "signal_id": "EQ-20260629-DEGRADED",
            "candidate_count": 0,
            "eligible_candidate_count": 0,
            "selected_candidate_count": 0,
            "symbols": [],
            "verifier_status": "blocked",
            "verifier_blocking_reasons": ["price_valid"],
            "scan_candidate_supply": {
                "status": "market_closed",
                "market_count": 20,
                "dynamic_scan_limit": 12,
                "proposal_count": 0,
                "validated_count": 0,
                "selected_candidate_count": 0,
                "rejected_count": 0,
                "rejection_reasons": {},
                "broker_orders_submitted": 0,
            },
            "candidate_selection_policy": {
                "source": "optimizer_artifact",
                "sample_acquisition_plan_source": "optimizer_artifact",
                "calibration_repair_plan_source": "optimizer_artifact",
                "selected_symbol_in_sample_acquisition_avoid_list": False,
                "selected_symbol_in_calibration_repair_avoid_list": False,
                "selected_symbol_in_calibration_repair_concentration_limited_list": False,
                "selected_symbol_preferred_by_calibration_repair": False,
                "prefer_calibration_repair_symbols": ["MSFT", "COIN", "AAPL"],
                "sample_acquisition_plan": _sample_acquisition_plan(),
                "calibration_repair_plan": _calibration_repair_plan(),
                "historical_policy_coverage": _historical_policy_coverage(),
                "live_order_authority": "none",
            },
        },
        "paper_canary": {
            "status": "skipped",
            "reason": "no_torben_worthy_candidate",
            "signal_id": "EQ-20260629-DEGRADED",
            "broker_orders_submitted": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "public_actions_taken": 0,
        },
        "paper_outcome": {
            "status": "observed",
            "signal_id": "EQ-20260629-NVDA-DAF4BF",
            "symbol": "NVDA",
            "entry_price": 193.91,
            "current_price": 194.89,
            "unrealized_pnl": 0.9799999999999898,
            "return_pct": 0.005053890980351657,
            "failures": [],
        },
        "sample_collector": {
            "status": "collected",
            "eligible_research_packet_count": 0,
            "canaries_created_count": 0,
            "canaries_reconciled_count": 12,
            "outcomes_observed": 12,
            "outcomes_blocked": 0,
            "paper_sample_count_after": 12,
            "sample_gap_after": 8,
            "confidence_policy_applied": True,
            "confidence_policy_source": "calibration_artifact",
            "policy_deferred_candidate_count": 0,
            "experiment_evaluation": {
                "present": True,
                "status": "waiting_for_target_samples",
                "history_appended_count": 0,
                "live_order_authority": "none",
                "loops": {
                    "risk-thresholds": {
                        "experiment_id": "equity-risk-thresholds-paper-v1",
                        "status": "waiting_for_target_samples",
                        "decision": "wait",
                        "samples_remaining": 3,
                        "calibrated_samples_remaining": 3,
                        "manual_approval_required": True,
                        "history_appended": False,
                    },
                    "execution-tactics": {
                        "experiment_id": "equity-execution-repair-priority-v1",
                        "status": "waiting_for_target_samples",
                        "decision": "wait",
                        "samples_remaining": 3,
                        "calibrated_samples_remaining": 3,
                        "manual_approval_required": False,
                        "history_appended": False,
                    },
                    "regime-detection": {
                        "experiment_id": "equity-regime-momentum-filter-v1",
                        "status": "waiting_for_target_samples",
                        "decision": "wait",
                        "samples_remaining": 3,
                        "calibrated_samples_remaining": 3,
                        "manual_approval_required": False,
                        "history_appended": False,
                    },
                },
            },
            "broker_orders_submitted": 0,
        },
        "paper_performance": {
            "status": "insufficient",
            "sample_count": 1,
            "hit_rate": 1.0,
            "average_return": 0.005053890980351657,
            "cumulative_return": 0.005053890980351694,
            "sharpe_ratio": None,
            "max_drawdown": 0.0,
            "newey_west_tstat_proxy": None,
            "oos_months": 0.0,
            "max_symbol_concentration": 1.0,
            "blocking_reasons": [
                "paper_performance_gate_failed:sample_count",
                "paper_performance_gate_failed:sharpe_ratio",
            ],
            "broker_orders_submitted": 0,
        },
        "signal_optimizer": {
            "status": "collecting_data",
            "promotion_decision": "blocked",
            "sample_gap": 19,
            "recommended_action_ids": [
                "collect_cached_equity_historicals",
                "wait_for_market_open_scan_supply",
                "collect_more_paper_samples",
                "keep_sharpe_gate_blocking",
                "keep_tstat_gate_blocking",
            ],
            "blocking_reasons": [
                "paper_performance_gate_failed:sample_count",
                "paper_performance_gate_failed:sharpe_ratio",
            ],
            "artifact_path": "/tmp/optimizer.json",
            "skill_path": "/tmp/SKILL.md",
            "scan_candidate_supply": {
                "status": "market_closed",
                "market_count": 20,
                "dynamic_scan_limit": 12,
                "proposal_count": 0,
                "validated_count": 0,
                "selected_candidate_count": 0,
                "rejected_count": 0,
                "rejection_reasons": {},
                "broker_orders_submitted": 0,
            },
            "sample_acquisition_plan": _sample_acquisition_plan(),
            "calibration_repair_plan": _calibration_repair_plan(),
            "historical_policy_coverage": _historical_policy_coverage(),
            "historical_verifier": {
                "status": "insufficient",
                "validation_mode": "cached_ohlcv_long_only_replay",
                "symbols": ["AAPL", "AMZN", "GOOGL", "NVDA"],
                "missing_symbols": ["AAPL", "AMZN", "GOOGL", "NVDA"],
                "sample_count": 0,
                "sample_gap": 20,
                "sharpe_ratio": None,
                "max_drawdown": None,
                "newey_west_tstat_proxy": None,
                "oos_months": None,
                "max_symbol_concentration": None,
                "live_order_authority": "none",
                "blocking_reasons": [
                    "historical_verifier_missing_bars",
                    "historical_verifier_gate_failed:oos_months",
                ],
                "broker_orders_submitted": 0,
            },
            "broker_orders_submitted": 0,
        },
        "stop_condition": {
            "present": True,
            "status": "wait_for_market_open_scan_supply",
            "primary_next_action": "wait_for_market_open_scan_supply",
            "release_conditions": ["scan_candidate_supply.market_open == true"],
            "max_new_samples": 3,
            "max_iterations": 3,
            "scan_candidate_supply": {
                "status": "market_closed",
                "market_count": 20,
                "dynamic_scan_limit": 12,
                "proposal_count": 0,
                "validated_count": 0,
                "selected_candidate_count": 0,
                "rejected_count": 0,
                "rejection_reasons": {},
                "broker_orders_submitted": 0,
            },
            "continue_reasons": ["active_experiment_sample_window_open"],
            "wait_when": [
                "scan_candidate_supply.status == market_closed",
                "signal_optimizer.recommended_action_ids includes wait_for_market_open_scan_supply",
            ],
            "read_only": True,
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
        },
        "primary_next_action": "wait_for_market_open_scan_supply",
        "deterministic_stop_condition": {
            "condition_id": "paper_optimization_until_window_and_repair_targets_clear",
            "continue_when": ["active_experiment_sample_window_open"],
            "stop_when": [
                "active_experiment_sample_window.new_sample_cap == 0",
                "calibration_repair_plan.repair_samples_remaining == 0",
            ],
            "wait_when": [
                "scan_candidate_supply.status == market_closed",
                "signal_optimizer.recommended_action_ids includes wait_for_market_open_scan_supply",
            ],
            "max_new_samples_this_window": 3,
            "max_iterations_this_window": 3,
        },
        "paper_optimization": {
            "continue_reasons": ["active_experiment_sample_window_open"],
            "scan_candidate_supply": {
                "status": "market_closed",
                "market_count": 20,
                "dynamic_scan_limit": 12,
                "proposal_count": 0,
                "validated_count": 0,
                "selected_candidate_count": 0,
                "rejected_count": 0,
                "rejection_reasons": {},
                "broker_orders_submitted": 0,
            },
            "max_new_samples": 3,
            "max_iterations": 3,
            "allowed_bounded_commands": [
                {
                    "command_id": "bounded_paper_sample_collector",
                    "command": "RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 uv run python scripts/equity_paper_sample_collector.py --max-candidates 3 --max-outcomes 3 --json",
                },
                {
                    "command_id": "bounded_trading_loop_tick",
                    "command": "RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 uv run python scripts/equity_trading_loop_tick.py --max-research-candidates 3 --max-sample-candidates 3 --max-sample-outcomes 3 --json",
                },
            ],
        },
        "experiment_evaluation": {
            "present": True,
            "status": "waiting_for_target_samples",
            "history_appended_count": 0,
            "live_order_authority": "none",
            "loops": {
                "risk-thresholds": {
                    "experiment_id": "equity-risk-thresholds-paper-v1",
                    "status": "waiting_for_target_samples",
                    "decision": "wait",
                    "samples_remaining": 3,
                    "calibrated_samples_remaining": 3,
                    "manual_approval_required": True,
                    "history_appended": False,
                },
                "execution-tactics": {
                    "experiment_id": "equity-execution-repair-priority-v1",
                    "status": "waiting_for_target_samples",
                    "decision": "wait",
                    "samples_remaining": 3,
                    "calibrated_samples_remaining": 3,
                    "manual_approval_required": False,
                    "history_appended": False,
                },
                "regime-detection": {
                    "experiment_id": "equity-regime-momentum-filter-v1",
                    "status": "waiting_for_target_samples",
                    "decision": "wait",
                    "samples_remaining": 3,
                    "calibrated_samples_remaining": 3,
                    "manual_approval_required": False,
                    "history_appended": False,
                },
            },
        },
        "risk_incident": {
            "status": "blocked",
            "blocking_reasons": ["circuit_breaker_active", "trading_halt_active"],
            "read_only": True,
        },
        "live_status": {
            "requested_signal_id": "EQ-20260629-MSFT-001",
            "resolved_signal_id": "EQ-20260629-MSFT-001",
            "latest_research_signal_id": "EQ-20260629-MSFT-001",
            "latest_research_ready": True,
            "status_scope": {"exact_signal_scoped": True, "warnings": []},
            "ready_to_submit": False,
            "go_live_blocked": True,
            "one_shot_live_submit_available": False,
            "blockers": ["approval_not_approved", "circuit_breaker_active", "trading_halt_active"],
        },
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def test_finance_radar_accepts_research_signal_packet_as_one_fin_card(tmp_path):
    payload = build_torben_finance_radar_adapter(
        _research_agent_run(),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["selected_count"] == 1
    assert payload["actions"][0]["handle"] == "FIN-20260626-001"
    candidate = payload["actions"][0]["executor_state"]["candidate"]
    assert candidate["symbol"] == "AAPL"
    assert candidate["signal_id"] == "EQ-20260626-AAPL-001"
    assert "fixture://company-hardware-pricing" in candidate["source_refs"]
    assert "regime:ai_concentration_2023_2025" in candidate["source_refs"]
    assert "AAPL stage_long" in payload["text"]
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_carries_quiet_trading_loop_heartbeat_context(tmp_path):
    payload = build_torben_finance_radar_adapter(
        _loop_tick_run(),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 29, 20, 45, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["candidate_count"] == 0
    assert payload["loop_heartbeat"]["present"] is True
    assert payload["loop_heartbeat"]["tick_id"] == "equity-loop-20260629T204307271641Z"
    assert payload["loop_heartbeat"]["research_mode"] == "batch"
    assert payload["loop_heartbeat"]["scan_candidate_supply"]["status"] == "market_closed"
    assert payload["loop_heartbeat"]["stop_condition"]["status"] == "wait_for_market_open_scan_supply"
    assert payload["stop_condition"]["present"] is True
    assert payload["stop_condition"]["primary_next_action"] == "wait_for_market_open_scan_supply"
    assert payload["stop_condition"]["release_conditions"] == ["scan_candidate_supply.market_open == true"]
    assert payload["primary_next_action"] == "wait_for_market_open_scan_supply"
    assert "scan_candidate_supply.status == market_closed" in payload["deterministic_stop_condition"]["wait_when"]
    assert payload["paper_optimization"]["scan_candidate_supply"]["status"] == "market_closed"
    assert payload["scan_candidate_supply"]["market_count"] == 20
    assert payload["scan_candidate_supply"]["proposal_count"] == 0
    assert payload["scan_candidate_supply"]["selected_candidate_count"] == 0
    assert payload["paper_outcome"]["status"] == "observed"
    assert payload["paper_outcome"]["symbol"] == "NVDA"
    assert payload["sample_collector"]["present"] is True
    assert payload["sample_collector"]["status"] == "collected"
    assert payload["sample_collector"]["outcomes_observed"] == 12
    assert payload["sample_collector"]["sample_gap_after"] == 8
    assert payload["paper_performance"]["present"] is True
    assert payload["paper_performance"]["status"] == "insufficient"
    assert payload["paper_performance"]["sample_count"] == 1
    assert payload["historical_verifier"]["present"] is True
    assert payload["historical_verifier"]["status"] == "insufficient"
    assert payload["historical_verifier"]["missing_symbols"] == ["AAPL", "AMZN", "GOOGL", "NVDA"]
    assert payload["historical_verifier"]["live_order_authority"] == "none"
    assert payload["signal_optimizer"]["present"] is True
    assert payload["signal_optimizer"]["status"] == "collecting_data"
    assert payload["signal_optimizer"]["promotion_decision"] == "blocked"
    assert payload["signal_optimizer"]["scan_candidate_supply"]["status"] == "market_closed"
    assert payload["signal_optimizer"]["sample_acquisition_plan"]["target_new_samples"] == 8
    assert payload["signal_optimizer"]["calibration_repair_plan"]["target_new_samples"] == 3
    assert payload["signal_optimizer"]["calibration_repair_plan"]["preferred_existing_symbols"] == [
        "MSFT",
        "COIN",
        "AAPL",
    ]
    assert payload["signal_optimizer"]["calibration_repair_plan"]["avoid_symbols"] == ["AMZN", "GOOGL"]
    assert payload["signal_optimizer"]["calibration_repair_plan"]["live_order_authority"] == "none"
    assert payload["signal_optimizer"]["historical_policy_coverage"]["status"] == "covered"
    assert payload["signal_optimizer"]["historical_policy_coverage"]["live_order_authority"] == "none"
    assert payload["experiment_evaluation"]["present"] is True
    assert payload["experiment_evaluation"]["status"] == "waiting_for_target_samples"
    assert payload["experiment_evaluation"]["waiting_loop_count"] == 3
    assert payload["experiment_evaluation"]["loops"]["risk-thresholds"]["samples_remaining"] == 3
    assert payload["experiment_evaluation"]["live_order_authority"] == "none"
    assert payload["active_experiment_sample_window"]["present"] is True
    assert payload["active_experiment_sample_window"]["status"] == "active"
    assert payload["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert payload["loop_heartbeat"]["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert payload["sample_collector"]["active_experiment_sample_window"]["waiting_loop_count"] == 3
    assert payload["loop_heartbeat"]["sample_acquisition_plan"]["avoid_symbols"] == ["AAPL"]
    assert payload["candidate_selection_policy"]["sample_acquisition_plan_source"] == "optimizer_artifact"
    assert payload["candidate_selection_policy"]["calibration_repair_plan_source"] == "optimizer_artifact"
    assert payload["candidate_selection_policy"]["prefer_calibration_repair_symbols"] == ["MSFT", "COIN", "AAPL"]
    assert payload["candidate_selection_policy"]["selected_symbol_preferred_by_calibration_repair"] is False
    assert payload["candidate_selection_policy"]["selected_symbol_in_calibration_repair_avoid_list"] is False
    assert payload["candidate_selection_policy"]["calibration_repair_plan"]["target_new_samples"] == 3
    assert payload["candidate_selection_policy"]["historical_policy_coverage"]["status"] == "covered"
    assert payload["candidate_selection_policy"]["live_order_authority"] == "none"
    assert payload["sample_acquisition_plan"]["preferred_existing_symbols"] == ["AMZN", "GOOGL", "NVDA"]
    assert payload["live_status"]["ready_to_submit"] is False
    assert payload["live_status"]["resolved_signal_id"] == "EQ-20260629-MSFT-001"
    assert payload["live_status"]["latest_research_signal_id"] == "EQ-20260629-MSFT-001"
    assert payload["live_status"]["latest_research_ready"] is True
    assert payload["live_status"]["status_scope"]["exact_signal_scoped"] is True
    assert payload["live_status"]["status_scope"]["warnings"] == []
    assert "circuit_breaker_active" in payload["live_status"]["blockers"]
    assert payload["risk_incident"]["blocking_reasons"] == ["circuit_breaker_active", "trading_halt_active"]
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_backfills_optimizer_sample_plan_from_candidate_policy(tmp_path):
    run = _loop_tick_run()
    run["signal_optimizer"].pop("sample_acquisition_plan")

    payload = build_torben_finance_radar_adapter(
        run,
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 29, 20, 45, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["signal_optimizer"]["sample_acquisition_plan"]["target_new_samples"] == 8
    assert payload["loop_heartbeat"]["sample_acquisition_plan"]["avoid_symbols"] == ["AAPL"]
    assert payload["orders_submitted"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_visible_card_includes_trading_loop_context(tmp_path):
    run = _research_agent_run()
    run["paper_outcome"] = _loop_tick_run()["paper_outcome"]
    run["research"] = _loop_tick_run()["research"]
    run["sample_collector"] = _loop_tick_run()["sample_collector"]
    run["paper_performance"] = _loop_tick_run()["paper_performance"]
    run["signal_optimizer"] = _loop_tick_run()["signal_optimizer"]
    run["stop_condition"] = _loop_tick_run()["stop_condition"]
    run["primary_next_action"] = _loop_tick_run()["primary_next_action"]
    run["deterministic_stop_condition"] = _loop_tick_run()["deterministic_stop_condition"]
    run["paper_optimization"] = _loop_tick_run()["paper_optimization"]
    run["live_status"] = _loop_tick_run()["live_status"]
    run["risk_incident"] = _loop_tick_run()["risk_incident"]

    payload = build_torben_finance_radar_adapter(
        run,
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["paper_outcome"]["status"] == "observed"
    assert "Paper outcome: NVDA observed" in payload["text"]
    assert payload["scan_candidate_supply"]["status"] == "market_closed"
    assert "Scan supply: market_closed" in payload["text"]
    assert "Loop stop condition: wait_for_market_open_scan_supply" in payload["text"]
    assert payload["sample_collector"]["status"] == "collected"
    assert "Sample collector: collected" in payload["text"]
    assert payload["paper_performance"]["status"] == "insufficient"
    assert "Paper performance: insufficient" in payload["text"]
    assert payload["historical_verifier"]["status"] == "insufficient"
    assert "Historical verifier: insufficient" in payload["text"]
    assert payload["signal_optimizer"]["promotion_decision"] == "blocked"
    assert "Signal optimizer: collecting_data" in payload["text"]
    assert "Sample acquisition plan: target new 8" in payload["text"]
    assert (
        "Candidate repair priority: preferred MSFT, COIN, AAPL; selected preferred no; "
        "avoid hit no; live authority none."
    ) in payload["text"]
    assert "Calibration repair plan: target new 3; preferred MSFT, COIN, AAPL; avoid AMZN, GOOGL." in payload["text"]
    assert "Historical policy coverage: covered; missing none." in payload["text"]
    assert payload["experiment_evaluation"]["status"] == "waiting_for_target_samples"
    assert "Experiment evaluator: waiting_for_target_samples" in payload["text"]
    assert payload["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert "Experiment sample window: active; new sample cap 3; waiting loops 3." in payload["text"]
    assert "Live readiness: blocked" in payload["text"]
    assert "exact signal EQ-20260629-MSFT-001" in payload["text"]
    trading_loop = payload["actions"][0]["executor_state"]["trading_loop"]
    assert trading_loop["scan_candidate_supply"]["proposal_count"] == 0
    assert trading_loop["stop_condition"]["primary_next_action"] == "wait_for_market_open_scan_supply"
    assert trading_loop["stop_condition"]["paper_optimization"]["max_new_samples"] == 3
    assert trading_loop["paper_outcome"]["symbol"] == "NVDA"
    assert trading_loop["sample_collector"]["outcomes_observed"] == 12
    assert trading_loop["paper_performance"]["sample_count"] == 1
    assert trading_loop["historical_verifier"]["missing_symbols"] == ["AAPL", "AMZN", "GOOGL", "NVDA"]
    assert trading_loop["signal_optimizer"]["sample_gap"] == 19
    assert trading_loop["signal_optimizer"]["sample_acquisition_plan"]["avoid_symbols"] == ["AAPL"]
    assert trading_loop["signal_optimizer"]["calibration_repair_plan"]["preferred_existing_symbols"] == [
        "MSFT",
        "COIN",
        "AAPL",
    ]
    assert trading_loop["signal_optimizer"]["historical_policy_coverage"]["status"] == "covered"
    assert trading_loop["candidate_selection_policy"]["prefer_calibration_repair_symbols"] == [
        "MSFT",
        "COIN",
        "AAPL",
    ]
    assert trading_loop["candidate_selection_policy"]["calibration_repair_plan"]["target_new_samples"] == 3
    assert trading_loop["candidate_selection_policy"]["live_order_authority"] == "none"
    assert trading_loop["experiment_evaluation"]["loops"]["risk-thresholds"]["decision"] == "wait"
    assert trading_loop["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert trading_loop["sample_acquisition_plan"]["target_new_samples"] == 8
    assert trading_loop["live_status"]["ready_to_submit"] is False
    assert trading_loop["live_status"]["resolved_signal_id"] == "EQ-20260629-MSFT-001"
    assert trading_loop["live_status"]["status_scope"]["exact_signal_scoped"] is True
    assert "trading_halt_active" in trading_loop["risk_incident"]["blocking_reasons"]


def test_finance_radar_stages_underfollowed_non_blue_chip_signal(tmp_path):
    packet = _research_signal_packet()
    packet["primary_symbol"] = "RXRX"
    packet["related_symbols"] = ["XBI", "IWM"]
    packet["signal_family"] = "underfollowed_company_catalyst"
    packet["opportunity_class"] = "small_mid_cap_catalyst"
    packet["why_underfollowed"] = "Sparse broad-market coverage despite a fresh product catalyst and live quote support."
    packet["thesis"] = "RXRX has an underfollowed product catalyst with source-backed asymmetry and defined invalidation."
    packet["source_refs"] = [
        "quote:RXRX:2026-06-26T14:00:00Z",
        "news:RXRX-product-catalyst-20260626",
    ]

    payload = build_torben_finance_radar_adapter(
        _research_agent_run(packet),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 16, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["selected_count"] == 1
    assert payload["opportunity_universe_version"] == "torben_broad_opportunity_universe_v1"
    assert payload["scan_window"] == "midday"
    assert payload["scan_windows_count"] >= 3
    assert "small_mid_cap_catalyst" in payload["candidate_class_counts"]
    assert payload["underfollowed_signal_count"] == 1
    assert "not limited to existing holdings or blue-chip names" in payload["text"]
    assert "Why it may be underfollowed" in payload["text"]
    candidate = payload["actions"][0]["executor_state"]["candidate"]
    assert candidate["symbol"] == "RXRX"
    assert candidate["opportunity_class"] == "small_mid_cap_catalyst"
    assert payload["orders_submitted"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_quiet_scan_records_no_llm_trigger(tmp_path):
    run = {
        "task": "ratatosk_equity_research_signal_cron",
        "source": "ratatosk_equity_research_agent_v1",
        "status": "success",
        "generated_at": "2026-06-26T16:00:00Z",
        "scan_window": "midday",
        "scan_windows": ["market_open", "midday", "late_afternoon"],
        "opportunity_universe_version": "fixture_broad_universe_v1",
        "opportunity_universe_scope": ["small_mid_cap_catalysts", "sector_dislocations"],
        "candidate_count": 0,
        "candidates": [],
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }

    payload = build_torben_finance_radar_adapter(
        run,
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 16, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["selected_count"] == 0
    assert payload["scan_window"] == "midday"
    assert payload["scan_windows_count"] == 3
    assert payload["opportunity_universe_version"] == "fixture_broad_universe_v1"
    assert payload["candidate_class_counts"] == {}
    assert payload["llm_triggered"] is False
    assert payload["quiet_scan_llm_triggered"] is False
    assert payload["no_llm_reason"] == "quiet scan produced no fresh decision-grade candidate"
    assert payload["text"] == ""
    assert payload["orders_submitted"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_script_preview_uses_fixture_without_broker_mutation(tmp_path, monkeypatch):
    packet = _research_signal_packet()
    packet["primary_symbol"] = "RXRX"
    packet["signal_family"] = "underfollowed_company_catalyst"
    packet["opportunity_class"] = "small_mid_cap_catalyst"
    packet["why_underfollowed"] = "Sparse coverage with a sourced product catalyst."
    fixture = tmp_path / "finance-fixture.json"
    fixture.write_text(json.dumps(_research_agent_run(packet)), encoding="utf-8")

    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_RADAR_PREVIEW", "1")
    monkeypatch.setenv("TORBEN_FINANCE_RADAR_FIXTURE", str(fixture))
    monkeypatch.setenv("TORBEN_FINANCE_SCAN_WINDOW", "midday")

    assert torben_finance_radar.main() == 0

    payload = json.loads((home / "state" / "torben-finance-radar-latest.json").read_text(encoding="utf-8"))
    assert payload["wakeAgent"] is True
    assert payload["scan_window"] == "midday"
    assert payload["opportunity_universe_version"] == "torben_broad_opportunity_universe_v1"
    assert payload["underfollowed_signal_count"] == 1
    assert payload["orders_submitted"] == 0
    assert payload["broker_orders_submitted"] == 0
    assert payload["actions"][0]["executor_state"]["mutation_status"] == "preview_only_not_ordered"


def test_finance_loop_heartbeat_script_writes_quiet_status_artifact(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "loop-tick.json"
    fixture.write_text(json.dumps(_loop_tick_run()), encoding="utf-8")

    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_LOOP_HEARTBEAT_FIXTURE", str(fixture))

    assert torben_finance_loop_heartbeat.main() == 0

    assert capsys.readouterr().out == ""
    payload = json.loads((home / "state" / "torben-finance-loop-heartbeat-latest.json").read_text(encoding="utf-8"))
    assert payload["task"] == "torben_finance_loop_heartbeat"
    assert payload["adapter_task"] == "torben_finance_radar"
    assert payload["wakeAgent"] is False
    assert payload["heartbeat_mode"] == "status_only"
    assert payload["stage_actions"] is False
    assert payload["mark_delivered"] is False
    assert payload["loop_heartbeat"]["present"] is True
    assert payload["loop_heartbeat"]["research_mode"] == "batch"
    assert payload["loop_heartbeat"]["stop_condition"]["status"] == "wait_for_market_open_scan_supply"
    assert payload["stop_condition"]["release_conditions"] == ["scan_candidate_supply.market_open == true"]
    assert payload["primary_next_action"] == "wait_for_market_open_scan_supply"
    assert payload["scan_candidate_supply"]["status"] == "market_closed"
    assert payload["scan_candidate_supply"]["proposal_count"] == 0
    assert payload["paper_outcome"]["symbol"] == "NVDA"
    assert payload["sample_collector"]["outcomes_observed"] == 12
    assert payload["paper_performance"]["status"] == "insufficient"
    assert payload["signal_optimizer"]["promotion_decision"] == "blocked"
    assert payload["signal_optimizer"]["sample_acquisition_plan"]["target_new_samples"] == 8
    assert payload["signal_optimizer"]["calibration_repair_plan"]["target_new_samples"] == 3
    assert payload["signal_optimizer"]["historical_policy_coverage"]["status"] == "covered"
    assert payload["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert payload["loop_heartbeat"]["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert payload["sample_collector"]["active_experiment_sample_window"]["waiting_loop_count"] == 3
    assert payload["loop_heartbeat"]["sample_acquisition_plan"]["avoid_symbols"] == ["AAPL"]
    assert payload["loop_heartbeat"]["candidate_selection_policy"]["prefer_calibration_repair_symbols"] == [
        "MSFT",
        "COIN",
        "AAPL",
    ]
    assert payload["loop_heartbeat"]["candidate_selection_policy"]["calibration_repair_plan"]["target_new_samples"] == 3
    assert payload["loop_heartbeat"]["candidate_selection_policy"]["live_order_authority"] == "none"
    assert payload["sample_acquisition_plan"]["live_order_authority"] == "none"
    assert payload["live_status"]["ready_to_submit"] is False
    assert payload["live_status"]["resolved_signal_id"] == "EQ-20260629-MSFT-001"
    assert payload["live_status"]["status_scope"]["exact_signal_scoped"] is True
    assert "circuit_breaker_active" in payload["risk_incident"]["blocking_reasons"]
    assert payload["orders_submitted"] == 0
    assert payload["broker_orders_submitted"] == 0
    assert (home / "state" / "torben-finance-loop-heartbeat-latest.txt").read_text(encoding="utf-8") == ""


def test_finance_loop_heartbeat_command_uses_bounded_repair_defaults(monkeypatch):
    monkeypatch.delenv("TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_RESEARCH_CANDIDATES", raising=False)
    monkeypatch.delenv("TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_SAMPLE_CANDIDATES", raising=False)
    monkeypatch.delenv("TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_SAMPLE_OUTCOMES", raising=False)

    command = torben_finance_loop_heartbeat._ratatosk_loop_tick_command()

    assert command[command.index("--max-research-candidates") + 1] == "3"
    assert command[command.index("--max-sample-candidates") + 1] == "3"
    assert command[command.index("--max-sample-outcomes") + 1] == "3"


def test_finance_loop_heartbeat_command_allows_bounded_repair_overrides(monkeypatch):
    monkeypatch.setenv("TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_RESEARCH_CANDIDATES", "2")
    monkeypatch.setenv("TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_SAMPLE_CANDIDATES", "1")
    monkeypatch.setenv("TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_SAMPLE_OUTCOMES", "1")

    command = torben_finance_loop_heartbeat._ratatosk_loop_tick_command()

    assert command[command.index("--max-research-candidates") + 1] == "2"
    assert command[command.index("--max-sample-candidates") + 1] == "1"
    assert command[command.index("--max-sample-outcomes") + 1] == "1"


def test_finance_radar_silent_for_degraded_research_packet(tmp_path):
    packet = _research_signal_packet()
    packet["status"] = "data_source_degraded"
    packet["proposed_action"] = "hold"
    packet["primary_symbol"] = "NONE"

    payload = build_torben_finance_radar_adapter(
        _research_agent_run(packet, status="data_source_degraded"),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["candidate_count"] == 0
    assert payload["silent_reason"] == "Ratatosk equity data source is degraded; no FIN card staged"
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_rejects_hedge_research_packet_without_analogs(tmp_path):
    packet = _research_signal_packet(proposed_action="stage_hedge")
    packet["historical_analogs"] = []

    payload = build_torben_finance_radar_adapter(
        _research_agent_run(packet),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["selected_count"] == 0
    assert "missing_historical_analogs" in payload["quality_gate_failed_criteria"]


def test_finance_radar_rejects_research_packet_with_candidate_mutation_counter(tmp_path):
    packet = _research_signal_packet()
    packet["mutation_counters"]["broker_orders_submitted"] = 1

    payload = build_torben_finance_radar_adapter(
        _research_agent_run(packet),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["selected_count"] == 0
    assert "candidate_broker_orders_submitted_nonzero" in payload["quality_gate_failed_criteria"]
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_finance_radar_rejects_stale_research_packet(tmp_path):
    packet = _research_signal_packet()
    packet["market_packet"]["data_freshness"] = "stale"

    payload = build_torben_finance_radar_adapter(
        _research_agent_run(packet),
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "finance-state.json",
        now=datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["selected_count"] == 0
    assert "missing_live_data_packet" in payload["quality_gate_failed_criteria"]
    assert payload["external_mutations"] == 0
    assert payload["broker_orders_submitted"] == 0
