from __future__ import annotations

import json
import os
from pathlib import Path

from profiles.torben.scripts import torben_finance_risk_monitor


def _risk_monitor_payload() -> dict:
    return {
        "task": "equity_trading_risk_monitor",
        "generated_at": "2026-06-30T00:11:27Z",
        "status": "blocked",
        "blocking_reasons": [
            "circuit_breaker_active",
            "live_status_blocked",
            "paper_experiment_evaluation_waiting",
            "paper_performance_insufficient",
            "signal_optimizer_blocked",
            "trading_halt_active",
        ],
        "warning_reasons": ["signal_optimizer_sample_gap:19"],
        "heartbeat": {
            "tick_id": "equity-loop-20260629T233221210772Z",
            "generated_at": "2026-06-30T00:00:00Z",
            "stale": True,
            "stale_blocking": False,
            "expected_market_closed_idle": True,
            "market_open_now": False,
            "market_closed_wait_context": True,
            "staleness_classification": "expected_market_closed_idle",
        },
        "live_status": {"ready_to_submit": False},
        "signal_optimizer": {
            "status": "collecting_data",
            "promotion_decision": "blocked",
            "calibration_repair_plan": {
                "policy_id": "paper_feedback_calibration_repair_plan_v1",
                "status": "needs_repair_samples",
                "target_new_samples": 3,
                "avoid_symbols": ["AMZN", "GOOGL"],
                "preferred_existing_symbols": ["MSFT", "COIN", "AAPL"],
                "preferred_symbol_details": [
                    {
                        "symbol": "MSFT",
                        "repair_priority_rank": 1,
                        "repair_priority_score": 4.8,
                        "live_order_authority": "none",
                    }
                ],
                "live_order_authority": "none",
            },
            "historical_policy_coverage": {
                "status": "covered",
                "repair_preferred_symbols": ["MSFT", "COIN", "AAPL"],
                "missing_repair_preferred_symbols": [],
                "missing_count": 0,
                "live_order_authority": "none",
            },
            "verifier_rejection_policy": {
                "policy_id": "paper_feedback_verifier_rejection_policy_v1",
                "status": "tighten_checker",
                "mode": "paper_feedback_only",
                "source": "verifier_debt_audit_artifact",
                "evaluation_basis": "rolling_market_open_scan_supply",
                "rejection_rate": 0.0,
                "min_rejection_rate": 0.4,
                "proposal_count": 74,
                "minimum_candidate_score": 0.8,
                "paper_candidate_rank_multiplier": 0.6,
                "candidate_constraints": {
                    "tighten_checker_until_rejection_rate_recovers": True,
                    "minimum_candidate_score": 0.8,
                    "paper_candidate_rank_multiplier": 0.6,
                },
                "live_order_authority": "none",
            },
        },
        "verifier_debt_audit": {
            "present": True,
            "status": "active_verification_debt",
            "verifier_debt_score": 0.42,
            "blocking_reasons": [
                "paper_sharpe_ratio_failed",
                "paper_experiment_window_waiting",
            ],
            "warning_reasons": [],
            "recommended_action_ids": [
                "continue_active_paper_experiment_window",
                "repair_performance_verifier_gates",
                "tighten_checker_rejection_policy",
            ],
            "rejection_rate_audit": {
                "status": "fail",
                "evaluation_basis": "rolling_market_open_scan_supply",
                "proposal_count": 74,
                "rejected_candidate_count": 0,
                "selected_candidate_count": 71,
                "not_selected_candidate_count": 3,
                "rejection_rate": 0.0,
                "min_rejection_rate": 0.4,
                "min_proposal_count": 10,
                "blocking_reason": "verifier_rejection_rate_too_low",
            },
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
        },
        "role_separation_audit": {
            "present": True,
            "status": "active_role_separation_debt",
            "role_separation_debt_score": 0.4,
            "blocking_reasons": [
                "risk_monitor_not_isolated_from_maker_checker_worktree",
                "risk_monitor_not_isolated_from_broker_connector_worktree",
            ],
            "warning_reasons": [],
            "recommended_action_ids": [
                "isolate_risk_monitor_worktree",
                "separate_risk_monitor_from_broker_connector",
            ],
            "risk_monitor_worktree": "/Users/ericfreeman/ratatosk",
            "remediation_plan": {
                "plan_id": "loop_engineering_role_separation_worktree_plan_v1",
                "status": "required",
                "mode": "read_only_remediation_contract",
                "target_risk_monitor_worktree": "/Users/ericfreeman/ratatosk-risk-monitor",
                "current_risk_monitor_worktree": "/Users/ericfreeman/ratatosk",
                "currently_shared_role_ids": [
                    "broker_connector",
                    "signal_generation",
                    "signal_optimizer",
                    "signal_verifier",
                    "verifier_debt_audit",
                ],
                "validation_command": "cd /Users/ericfreeman/ratatosk && RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 uv run python scripts/equity_loop_role_separation_audit.py --json",
                "risk_monitor_command": "cd /Users/ericfreeman/ratatosk-risk-monitor && RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 uv run python scripts/equity_trading_risk_monitor.py --json",
                "manual_live_approval_required_afterwards": True,
                "stop_condition": {
                    "risk_monitor_git_metadata_available": True,
                    "risk_monitor_live_order_authority": "none",
                    "broker_write_authority": False,
                },
                "live_order_authority": "none",
                "broker_write_authority": False,
                "mutation_counters": {
                    "public_actions_taken": 0,
                    "external_mutations": 0,
                    "orders_submitted": 0,
                    "broker_orders_submitted": 0,
                },
            },
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
        },
        "stop_condition": {
            "present": True,
            "status": "continue_paper_optimization",
            "primary_next_action": "run_bounded_paper_sample_collection",
            "max_new_samples": 3,
            "max_iterations": 3,
            "continue_reasons": [
                "active_experiment_sample_window_open",
                "calibration_repair_samples_remaining",
            ],
            "allowed_command_ids": [
                "bounded_paper_sample_collector",
                "bounded_stage_only_tick",
            ],
            "live_review_status": "blocked",
            "live_review_blocking_reasons": [
                "verifier_debt_active",
                "role_separation_debt_active",
            ],
            "recommended_action_ids": [
                "run_bounded_paper_optimization_window",
                "resolve_structural_role_separation_debt",
            ],
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
        },
        "paper_evidence_runway": {
            "present": True,
            "status": "continue_paper_optimization",
            "primary_next_action": "run_bounded_paper_sample_collection",
            "safe_operator_action": "run_bounded_paper_optimization_window",
            "live_order_authority": "none",
            "paper_optimization": {
                "max_new_samples": 3,
                "max_iterations": 3,
                "allowed_bounded_command_ids": [
                    "bounded_paper_sample_collector",
                    "bounded_stage_only_tick",
                ],
                "commands_live_disabled": True,
            },
            "calibration_repair_plan": {
                "status": "needs_repair_samples",
                "target_new_samples": 3,
                "repair_samples_remaining": 3,
                "live_order_authority": "none",
            },
            "recommended_action_ids": [
                "run_bounded_paper_optimization_window",
                "resolve_structural_role_separation_debt",
            ],
            "evidence_blockers": [
                "paper_performance_gate_failed:sharpe_ratio",
            ],
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
        },
        "evidence_wait_packet": {
            "task": "equity_evidence_wait_packet",
            "generated_at": "2026-07-03T12:14:13Z",
            "status": "pass",
            "errors": [],
            "release_evaluation": {
                "status": "hold_wait",
                "release_signal_count": 0,
                "required_operator_action": "continue_wait",
                "live_order_authority": "none",
            },
            "wait_contract": {
                "status": "wait_for_paper_evidence",
                "primary_next_action": "wait_for_oos_or_market_data",
                "max_new_samples": 0,
                "max_iterations": 0,
                "recommended_action_ids": ["wait_for_oos_or_market_data"],
                "next_recheck_after_utc": "2026-07-04T00:00:00Z",
                "bounded_collection_not_before_utc": "2026-07-06T13:30:00Z",
                "live_order_authority": "none",
            },
            "next_wake_contract": {
                "status": "scheduled_recheck",
                "generated_at": "2026-07-03T12:14:13Z",
                "next_recheck_after_utc": "2026-07-04T00:00:00Z",
                "budget_reopens_after_utc": "2026-07-04T00:00:00Z",
                "market_scan_recheck_after_utc": "2026-07-06T13:30:00Z",
                "bounded_collection_not_before_utc": "2026-07-06T13:30:00Z",
                "wake_reason_ids": [
                    "daily_paper_sample_budget_exhausted",
                    "market_closed_scan_supply",
                    "release_signal_absent",
                ],
                "required_operator_action": "continue_wait",
                "commands": {
                    "recheck_evidence_wait_packet": (
                        "RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 uv run python "
                        "scripts/equity_evidence_wait_packet.py --json"
                    ),
                    "recheck_research_candidate_supply": (
                        "RATATOSK_LIVE_TRADING=0 ROBINHOOD_LIVE=0 ROBINHOOD_EQUITY_LIVE=0 uv run python "
                        "scripts/equity_research_signal_cron.py --batch --max-candidates 5 --json"
                    ),
                },
                "commands_live_disabled": True,
                "broker_submit_allowed": False,
                "human_live_review_allowed": False,
                "live_order_authority": "none",
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
            "read_only": True,
            "live_order_authority": "none",
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
        },
        "loop_readiness_ledger": {
            "task": "equity_loop_readiness_ledger",
            "status": "blocked",
            "ledger_status": "pass",
            "implementation_status": "stage_only_production_ready_live_blocked",
            "errors": [],
            "current_state": {
                "safe_operator_action": "wait_for_oos_or_market_data",
                "go_live": {
                    "status": "blocked",
                    "ready_to_submit": False,
                    "go_live_blocked": True,
                    "blocker_count": 49,
                },
                "halt_and_circuit_breaker": {
                    "status": "blocked",
                    "trading_halt_active": True,
                    "circuit_breaker_active": True,
                    "live_order_authority": "none",
                },
                "live_promotion_controls": {
                    "operator_approval": {
                        "status": "missing_or_invalid",
                        "required_scope": "one_shot_live_canary",
                        "live_order_authority": "none",
                    },
                    "live_flags": {
                        "status": "disabled_until_final_gate",
                        "enabled_now": False,
                        "one_shot_live_submit_available": False,
                        "live_order_authority": "none",
                    },
                },
                "optimizer_evidence": {
                    "status": "blocked",
                    "optimizer_status": "collecting_data",
                    "calibration_repair_plan": {
                        "status": "awaiting_paper_evidence",
                        "target_new_samples": 0,
                        "repair_samples_remaining": 0,
                        "live_order_authority": "none",
                    },
                    "paper_feedback_only": True,
                    "sample_budget_open": False,
                    "live_order_authority": "none",
                },
                "paper_verifier_gates": {
                    "status": "blocked",
                    "performance_status": "insufficient",
                    "calibration_status": "insufficient",
                    "sample_count": 145,
                    "calibrated_sample_count": 145,
                    "blocked_gate_ids": [
                        "brier_score",
                        "newey_west_tstat_proxy",
                        "oos_months",
                        "sharpe_ratio",
                    ],
                    "gate_statuses": {
                        "sample_count": "pass",
                        "sharpe_ratio": "blocked",
                        "max_drawdown": "pass",
                        "newey_west_tstat_proxy": "blocked",
                        "oos_months": "blocked",
                        "max_symbol_concentration": "pass",
                        "brier_score": "blocked",
                    },
                    "live_order_authority": "none",
                },
            },
            "blocking_gaps": [
                {"id": "paper_performance", "status": "blocking_live_go"},
                {"id": "paper_calibration", "status": "blocking_live_go"},
                {"id": "paper_evidence_runway", "status": "intentional_wait"},
                {"id": "operator_approval", "status": "blocking_live_go"},
                {"id": "halt_and_circuit_breaker", "status": "blocking_live_go"},
                {"id": "live_flags", "status": "blocking_live_go"},
            ],
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
        },
        "research_candidate_supply": {
            "present": True,
            "status": "waiting_for_market_open",
            "primary_next_action": "wait_for_market_open_scan_supply",
            "latest_research": {
                "generated_at": "2026-06-30T00:10:30Z",
                "status": "no_actionable_signal",
                "signal_id": "EQ-20260629-DEGRADED",
                "candidate_count": 0,
                "source_freshness": {"status": "live_market_packet"},
            },
            "latest_tick": {
                "generated_at": "2026-06-30T00:11:00Z",
                "status": "completed",
                "primary_next_action": "wait_for_oos_or_market_data",
                "research_status": "no_actionable_signal",
                "research_candidate_count": 0,
            },
            "scan_candidate_supply": {
                "status": "market_closed",
                "market_open": False,
                "market_count": 20,
                "proposal_count": 0,
                "validated_candidate_count": 0,
                "selected_candidate_count": 0,
                "rejected_candidate_count": 0,
                "rejection_reasons": {},
            },
            "candidate_selection_policy": {
                "policy_id": "paper_feedback_candidate_selection_policy_v1",
                "status": "conservative",
                "live_order_authority": "none",
                "require_historical_strategy_eligible_symbol": True,
                "prefer_positive_paper_return_symbols": ["MSFT", "COIN"],
                "dampen_underperforming_symbols_until_performance_passes": ["AMZN"],
                "dampen_high_brier_symbols_until_brier_passes": ["GOOGL"],
            },
            "diagnostics": [
                "latest_research_status:no_actionable_signal",
                "latest_research_candidate_count_zero",
                "scan_candidate_supply_status:market_closed",
                "scan_candidate_supply_market_closed",
            ],
            "release_conditions": [
                "scan_candidate_supply.market_open == true",
                "latest_research.status == success",
                "latest_research.candidate_count == 1",
            ],
            "commands_live_disabled": True,
            "live_order_authority": "none",
            "read_only": True,
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
        },
        "experiment_evaluation": {
            "present": True,
            "status": "waiting_for_target_samples",
            "history_appended_count": 0,
            "live_order_authority": "none",
            "loops": {
                "risk-thresholds": {
                    "experiment_id": "equity-risk-thresholds-paper-v1",
                    "decision": "wait",
                    "samples_remaining": 3,
                    "calibrated_samples_remaining": 3,
                    "manual_approval_required": True,
                    "history_appended": False,
                },
                "execution-tactics": {
                    "experiment_id": "equity-execution-repair-priority-v1",
                    "decision": "wait",
                    "samples_remaining": 4,
                    "calibrated_samples_remaining": 4,
                    "manual_approval_required": False,
                    "history_appended": False,
                },
            },
        },
        "upstream_mutations": {"nonzero": []},
        "next_actions": ["Keep live submit disabled."],
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _quiet_paper_wait_payload() -> dict:
    payload = json.loads(json.dumps(_risk_monitor_payload()))
    payload["blocking_reasons"] = [
        "circuit_breaker_active",
        "live_status_blocked",
        "paper_calibration_insufficient",
        "paper_experiment_evaluation_waiting",
        "paper_performance_insufficient",
        "signal_optimizer_blocked",
        "trading_halt_active",
    ]
    payload["warning_reasons"] = []
    payload["heartbeat"]["stale"] = False
    payload["heartbeat"]["stale_blocking"] = False
    payload["role_separation_audit"]["status"] = "clear_for_human_review"
    payload["role_separation_audit"]["role_separation_debt_score"] = 0.0
    payload["role_separation_audit"]["blocking_reasons"] = []
    payload["role_separation_audit"]["recommended_action_ids"] = ["preserve_role_separation_for_live_review"]
    payload["role_separation_audit"]["risk_monitor_worktree"] = "/Users/ericfreeman/ratatosk-risk-monitor"
    payload["role_separation_audit"]["remediation_plan"]["status"] = "satisfied"
    payload["role_separation_audit"]["remediation_plan"]["current_risk_monitor_worktree"] = (
        "/Users/ericfreeman/ratatosk-risk-monitor"
    )
    payload["role_separation_audit"]["remediation_plan"]["currently_shared_role_ids"] = []
    payload["stop_condition"] = {
        "present": True,
        "status": "wait_for_paper_evidence",
        "primary_next_action": "wait_for_oos_or_market_data",
        "max_new_samples": 0,
        "max_iterations": 0,
        "continue_reasons": [
            "paper_calibration_insufficient",
            "paper_performance_insufficient",
        ],
        "allowed_command_ids": [],
        "live_review_status": "blocked",
        "live_review_blocking_reasons": [
            "live_status_not_ready",
            "signal_optimizer_not_ready_for_human_review",
        ],
        "recommended_action_ids": ["wait_for_oos_or_market_data"],
        "release_conditions": ["new paper outcome, OOS window progress, or explicit optimizer repair demand"],
        "live_order_authority": "none",
        "mutation_counters": {
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    }
    payload["paper_evidence_runway"] = {
        "present": True,
        "status": "wait_for_paper_evidence",
        "primary_next_action": "wait_for_oos_or_market_data",
        "safe_operator_action": "wait_for_oos_or_market_data",
        "live_order_authority": "none",
        "paper_optimization": {
            "max_new_samples": 0,
            "max_iterations": 0,
            "allowed_bounded_command_ids": [],
            "commands_live_disabled": True,
        },
        "calibration_repair_plan": {
            "status": "awaiting_paper_evidence",
            "target_new_samples": 0,
            "repair_samples_remaining": 0,
            "live_order_authority": "none",
        },
        "recommended_action_ids": ["wait_for_oos_or_market_data"],
        "evidence_blockers": [
            "paper_calibration_gate_failed:brier_score",
            "paper_performance_gate_failed:sharpe_ratio",
        ],
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
    payload["loop_readiness_ledger"]["current_state"]["safe_operator_action"] = "wait_for_oos_or_market_data"
    payload["loop_readiness_ledger"]["blocking_gaps"] = [
        {"id": "paper_performance", "status": "blocking_live_go"},
        {"id": "paper_calibration", "status": "blocking_live_go"},
        {"id": "paper_evidence_runway", "status": "intentional_wait"},
        {"id": "operator_approval", "status": "blocking_live_go"},
        {"id": "halt_and_circuit_breaker", "status": "blocking_live_go"},
        {"id": "live_flags", "status": "blocking_live_go"},
    ]
    return payload


def test_risk_monitor_uses_isolated_worktree_with_canonical_state(tmp_path, monkeypatch):
    canonical_root = tmp_path / "ratatosk"
    risk_worktree = tmp_path / "ratatosk-risk-monitor"
    state_root = canonical_root / "state"
    state_root.mkdir(parents=True)
    risk_worktree.mkdir()
    captured: dict[str, object] = {}

    def fake_run_ratatosk_command(command: list[str], *, root: Path, timeout_seconds: int):
        captured["command"] = command
        captured["root"] = root
        captured["timeout_seconds"] = timeout_seconds
        captured["role_env"] = {
            key: os.environ.get(key)
            for key in [
                "RATATOSK_SIGNAL_MAKER_WORKTREE",
                "RATATOSK_SIGNAL_OPTIMIZER_WORKTREE",
                "RATATOSK_SIGNAL_VERIFIER_WORKTREE",
                "RATATOSK_VERIFIER_DEBT_WORKTREE",
                "RATATOSK_BROKER_CONNECTOR_WORKTREE",
                "RATATOSK_RISK_MONITOR_WORKTREE",
                "RATATOSK_STATE_ROOT",
            ]
        }
        payload = {
            "task": "equity_trading_risk_monitor",
            "status": "blocked",
            "blocking_reasons": ["trading_halt_active"],
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        }
        refresh = {
            "status": "success",
            "profile": "ratatosk",
            "root": str(root),
            "command": command,
            "returncode": 0,
            "elapsed_seconds": 0.0,
            "stderr_tail": "",
        }
        return payload, refresh

    monkeypatch.setenv("TORBEN_FINANCE_RISK_MONITOR_RATATOSK_ROOT", str(canonical_root))
    monkeypatch.setenv("RATATOSK_RISK_MONITOR_WORKTREE", str(risk_worktree))
    monkeypatch.setenv("TORBEN_FINANCE_RISK_MONITOR_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr(torben_finance_risk_monitor, "_run_ratatosk_command", fake_run_ratatosk_command)

    payload, refresh = torben_finance_risk_monitor._run_ratatosk_risk_monitor()

    assert payload["status"] == "blocked"
    assert captured["root"] == risk_worktree
    assert captured["timeout_seconds"] == 12
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:3] == ["uv", "run", "python"]
    assert "--state-root" in command
    assert command[command.index("--state-root") + 1] == str(state_root)
    assert refresh["root"] == str(risk_worktree)
    assert refresh["canonical_root"] == str(canonical_root)
    assert refresh["state_root"] == str(state_root)
    assert captured["role_env"] == {
        "RATATOSK_SIGNAL_MAKER_WORKTREE": str(canonical_root),
        "RATATOSK_SIGNAL_OPTIMIZER_WORKTREE": str(canonical_root),
        "RATATOSK_SIGNAL_VERIFIER_WORKTREE": str(canonical_root),
        "RATATOSK_VERIFIER_DEBT_WORKTREE": str(canonical_root),
        "RATATOSK_BROKER_CONNECTOR_WORKTREE": str(canonical_root),
        "RATATOSK_RISK_MONITOR_WORKTREE": str(risk_worktree),
        "RATATOSK_STATE_ROOT": str(state_root),
    }


def test_risk_monitor_defaults_to_sibling_isolated_git_worktree(tmp_path, monkeypatch):
    canonical_root = tmp_path / "ratatosk"
    risk_worktree = tmp_path / "ratatosk-risk-monitor"
    state_root = canonical_root / "state"
    state_root.mkdir(parents=True)
    risk_worktree.mkdir()
    (risk_worktree / ".git").write_text("gitdir: ../ratatosk/.git/worktrees/ratatosk-risk-monitor\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_ratatosk_command(command: list[str], *, root: Path, timeout_seconds: int):
        captured["command"] = command
        captured["root"] = root
        captured["role_env"] = {
            key: os.environ.get(key)
            for key in [
                "RATATOSK_SIGNAL_MAKER_WORKTREE",
                "RATATOSK_SIGNAL_OPTIMIZER_WORKTREE",
                "RATATOSK_SIGNAL_VERIFIER_WORKTREE",
                "RATATOSK_VERIFIER_DEBT_WORKTREE",
                "RATATOSK_BROKER_CONNECTOR_WORKTREE",
                "RATATOSK_RISK_MONITOR_WORKTREE",
                "RATATOSK_STATE_ROOT",
            ]
        }
        payload = {
            "task": "equity_trading_risk_monitor",
            "status": "blocked",
            "blocking_reasons": ["trading_halt_active"],
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        }
        refresh = {
            "status": "success",
            "profile": "ratatosk",
            "root": str(root),
            "command": command,
            "returncode": 0,
            "elapsed_seconds": 0.0,
            "stderr_tail": "",
        }
        return payload, refresh

    monkeypatch.setenv("TORBEN_FINANCE_RISK_MONITOR_RATATOSK_ROOT", str(canonical_root))
    monkeypatch.delenv("TORBEN_FINANCE_RISK_MONITOR_WORKTREE", raising=False)
    monkeypatch.delenv("RATATOSK_RISK_MONITOR_WORKTREE", raising=False)
    monkeypatch.setattr(torben_finance_risk_monitor, "_run_ratatosk_command", fake_run_ratatosk_command)

    payload, refresh = torben_finance_risk_monitor._run_ratatosk_risk_monitor()

    assert payload["status"] == "blocked"
    assert captured["root"] == risk_worktree
    command = captured["command"]
    assert isinstance(command, list)
    assert "--state-root" in command
    assert command[command.index("--state-root") + 1] == str(state_root)
    assert refresh["root"] == str(risk_worktree)
    assert refresh["canonical_root"] == str(canonical_root)
    assert refresh["state_root"] == str(state_root)
    assert captured["role_env"] == {
        "RATATOSK_SIGNAL_MAKER_WORKTREE": str(canonical_root),
        "RATATOSK_SIGNAL_OPTIMIZER_WORKTREE": str(canonical_root),
        "RATATOSK_SIGNAL_VERIFIER_WORKTREE": str(canonical_root),
        "RATATOSK_VERIFIER_DEBT_WORKTREE": str(canonical_root),
        "RATATOSK_BROKER_CONNECTOR_WORKTREE": str(canonical_root),
        "RATATOSK_RISK_MONITOR_WORKTREE": str(risk_worktree),
        "RATATOSK_STATE_ROOT": str(state_root),
    }


def test_finance_risk_monitor_wakes_once_per_changed_fingerprint(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "risk-monitor.json"
    fixture.write_text(json.dumps(_risk_monitor_payload()), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_RISK_MONITOR_FIXTURE", str(fixture))

    assert torben_finance_risk_monitor.main() == 0
    first_stdout = capsys.readouterr().out
    assert "Torben / Finance Risk Monitor" in first_stdout
    assert (
        "Heartbeat: equity-loop-20260629T233221210772Z; stale=True; "
        "blocking=False; class=expected_market_closed_idle."
    ) in first_stdout
    assert "Experiment sample window: active; new_sample_cap=3; waiting_loops=2." in first_stdout
    assert (
        "Calibration repair plan: target_new=3; preferred=MSFT,COIN,AAPL; avoid=AMZN,GOOGL."
        in first_stdout
    )
    assert "Historical policy coverage: covered; missing=none." in first_stdout
    assert "Verifier rejection policy: tighten_checker; min_score=0.8; rank_multiplier=0.6; authority=none." in first_stdout
    assert (
        "Verifier debt audit: active_verification_debt; score=0.42; "
        "actions=continue_active_paper_experiment_window,repair_performance_verifier_gates,tighten_checker_rejection_policy."
    ) in first_stdout
    assert "Verifier rejection rate: fail; rate=0.0; proposals=74; rejected=0; min=0.4." in first_stdout
    assert (
        "Role separation audit: active_role_separation_debt; score=0.4; "
        "actions=isolate_risk_monitor_worktree,separate_risk_monitor_from_broker_connector."
    ) in first_stdout
    assert (
        "Role separation plan: required; target=/Users/ericfreeman/ratatosk-risk-monitor; "
        "shared=broker_connector,signal_generation,signal_optimizer,signal_verifier,verifier_debt_audit; authority=none."
    ) in first_stdout
    assert (
        "Stop condition: continue_paper_optimization; max_new=3; "
        "action=run_bounded_paper_optimization_window,resolve_structural_role_separation_debt."
    ) in first_stdout
    assert (
        "Paper evidence runway: continue_paper_optimization; "
        "action=run_bounded_paper_optimization_window; max_new=3; "
        "commands_live_disabled=True; authority=none."
    ) in first_stdout
    assert (
        "Evidence wait packet: pass; release=hold_wait; "
        "next=2026-07-04T00:00:00Z; market_scan=2026-07-06T13:30:00Z; "
        "bounded_not_before=2026-07-06T13:30:00Z; "
        "reasons=daily_paper_sample_budget_exhausted,market_closed_scan_supply,release_signal_absent; "
        "commands_live_disabled=True; authority=none."
    ) in first_stdout
    assert (
        "Loop readiness ledger: stage_only_production_ready_live_blocked; "
        "live=blocked; action=wait_for_oos_or_market_data; halt=blocked; "
        "approval=missing_or_invalid; flags=disabled_until_final_gate; optimizer=blocked; "
        "paper=blocked; "
        "gaps=paper_performance,paper_calibration,paper_evidence_runway,operator_approval,halt_and_circuit_breaker,live_flags; "
        "authority=none."
    ) in first_stdout
    assert (
        "Research supply: waiting_for_market_open; latest=no_actionable_signal; "
        "candidates=0; scan=market_closed; action=wait_for_market_open_scan_supply."
    ) in first_stdout
    first = json.loads((home / "state" / "torben-finance-risk-monitor-latest.json").read_text(encoding="utf-8"))
    assert first["task"] == "torben_finance_risk_monitor"
    assert first["adapter_task"] == "equity_trading_risk_monitor"
    assert first["wakeAgent"] is True
    assert first["broker_orders_submitted"] == 0
    assert "circuit_breaker_active" in first["blocking_reasons"]
    assert first["active_experiment_sample_window"]["status"] == "active"
    assert first["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert first["active_experiment_sample_window"]["waiting_loop_count"] == 2
    assert first["signal_optimizer"]["calibration_repair_plan"]["target_new_samples"] == 3
    assert first["signal_optimizer"]["calibration_repair_plan"]["preferred_existing_symbols"] == [
        "MSFT",
        "COIN",
        "AAPL",
    ]
    assert first["signal_optimizer"]["calibration_repair_plan"]["live_order_authority"] == "none"
    assert first["signal_optimizer"]["historical_policy_coverage"]["status"] == "covered"
    assert first["signal_optimizer"]["historical_policy_coverage"]["live_order_authority"] == "none"
    assert first["signal_optimizer"]["verifier_rejection_policy"]["status"] == "tighten_checker"
    assert first["signal_optimizer"]["verifier_rejection_policy"]["minimum_candidate_score"] == 0.8
    assert first["signal_optimizer"]["verifier_rejection_policy"]["live_order_authority"] == "none"
    assert first["verifier_debt_audit"]["status"] == "active_verification_debt"
    assert first["verifier_debt_audit"]["live_order_authority"] == "none"
    assert first["verifier_debt_audit"]["rejection_rate_audit"]["rejection_rate"] == 0.0
    assert first["role_separation_audit"]["status"] == "active_role_separation_debt"
    assert first["role_separation_audit"]["live_order_authority"] == "none"
    assert first["role_separation_audit"]["remediation_plan"]["status"] == "required"
    assert first["role_separation_audit"]["remediation_plan"]["live_order_authority"] == "none"
    assert first["role_separation_audit"]["remediation_plan"]["target_risk_monitor_worktree"] == (
        "/Users/ericfreeman/ratatosk-risk-monitor"
    )
    assert first["stop_condition"]["status"] == "continue_paper_optimization"
    assert first["stop_condition"]["live_order_authority"] == "none"
    assert first["paper_evidence_runway"]["status"] == "continue_paper_optimization"
    assert first["paper_evidence_runway"]["safe_operator_action"] == "run_bounded_paper_optimization_window"
    assert first["paper_evidence_runway"]["paper_optimization"]["commands_live_disabled"] is True
    assert first["paper_evidence_runway"]["calibration_repair_plan"]["live_order_authority"] == "none"
    assert first["paper_evidence_runway"]["broker_orders_submitted"] == 0
    assert first["evidence_wait_packet"]["status"] == "pass"
    assert first["evidence_wait_packet"]["release_evaluation"]["status"] == "hold_wait"
    assert first["evidence_wait_packet"]["next_wake_contract"]["next_recheck_after_utc"] == (
        "2026-07-04T00:00:00Z"
    )
    assert first["evidence_wait_packet"]["next_wake_contract"]["market_scan_recheck_after_utc"] == (
        "2026-07-06T13:30:00Z"
    )
    assert first["evidence_wait_packet"]["next_wake_contract"]["bounded_collection_not_before_utc"] == (
        "2026-07-06T13:30:00Z"
    )
    assert first["evidence_wait_packet"]["next_wake_contract"]["commands_live_disabled"] is True
    assert first["evidence_wait_packet"]["next_wake_contract"]["broker_submit_allowed"] is False
    assert first["evidence_wait_packet"]["next_wake_contract"]["human_live_review_allowed"] is False
    assert first["evidence_wait_packet"]["next_wake_contract"]["live_order_authority"] == "none"
    assert first["loop_readiness_ledger"]["ledger_status"] == "pass"
    assert first["loop_readiness_ledger"]["implementation_status"] == "stage_only_production_ready_live_blocked"
    assert first["loop_readiness_ledger"]["current_state"]["safe_operator_action"] == "wait_for_oos_or_market_data"
    assert first["loop_readiness_ledger"]["current_state"]["halt_and_circuit_breaker"]["status"] == "blocked"
    assert (
        first["loop_readiness_ledger"]["current_state"]["live_promotion_controls"]["operator_approval"]["status"]
        == "missing_or_invalid"
    )
    assert (
        first["loop_readiness_ledger"]["current_state"]["live_promotion_controls"]["live_flags"]["status"]
        == "disabled_until_final_gate"
    )
    assert first["loop_readiness_ledger"]["current_state"]["optimizer_evidence"]["status"] == "blocked"
    assert first["loop_readiness_ledger"]["current_state"]["optimizer_evidence"]["sample_budget_open"] is False
    assert first["loop_readiness_ledger"]["current_state"]["paper_verifier_gates"]["status"] == "blocked"
    assert (
        "sharpe_ratio"
        in first["loop_readiness_ledger"]["current_state"]["paper_verifier_gates"]["blocked_gate_ids"]
    )
    assert first["loop_readiness_ledger"]["broker_orders_submitted"] == 0
    assert first["research_candidate_supply"]["status"] == "waiting_for_market_open"
    assert first["research_candidate_supply"]["latest_research"]["candidate_count"] == 0
    assert first["research_candidate_supply"]["scan_candidate_supply"]["status"] == "market_closed"
    assert first["research_candidate_supply"]["commands_live_disabled"] is True
    assert (home / "state" / "torben-finance-risk-monitor-state.json").exists()

    assert torben_finance_risk_monitor.main() == 0
    assert capsys.readouterr().out == ""
    second = json.loads((home / "state" / "torben-finance-risk-monitor-latest.json").read_text(encoding="utf-8"))
    assert second["wakeAgent"] is False
    assert second["risk_fingerprint"] == first["risk_fingerprint"]
    assert (home / "state" / "torben-finance-risk-monitor-latest.txt").read_text(encoding="utf-8") == ""


def test_finance_risk_monitor_keeps_expected_paper_wait_quiet(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "risk-monitor.json"
    fixture.write_text(json.dumps(_quiet_paper_wait_payload()), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_RISK_MONITOR_FIXTURE", str(fixture))

    assert torben_finance_risk_monitor.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-risk-monitor-latest.json").read_text(encoding="utf-8"))

    assert latest["wakeAgent"] is False
    assert latest["quiet_paper_evidence_wait"] is True
    assert latest["stop_condition"]["status"] == "wait_for_paper_evidence"
    assert latest["paper_evidence_runway"]["safe_operator_action"] == "wait_for_oos_or_market_data"
    assert latest["evidence_wait_packet"]["next_wake_contract"]["commands_live_disabled"] is True
    assert latest["evidence_wait_packet"]["next_wake_contract"]["broker_submit_allowed"] is False
    assert latest["role_separation_audit"]["blocking_reasons"] == []
    assert latest["broker_orders_submitted"] == 0
    assert (home / "state" / "torben-finance-risk-monitor-latest.txt").read_text(encoding="utf-8") == ""


def test_finance_risk_monitor_wakes_when_evidence_wait_packet_loses_live_disabled_proof(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _quiet_paper_wait_payload()
    next_wake = payload["evidence_wait_packet"]["next_wake_contract"]
    next_wake["commands_live_disabled"] = False
    next_wake["broker_submit_allowed"] = True
    next_wake["live_order_authority"] = "review_only"
    fixture = tmp_path / "risk-monitor.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_RISK_MONITOR_FIXTURE", str(fixture))

    assert torben_finance_risk_monitor.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-risk-monitor-latest.json").read_text(encoding="utf-8"))

    assert latest["wakeAgent"] is True
    assert latest["quiet_paper_evidence_wait"] is False
    assert latest["evidence_wait_packet"]["next_wake_contract"]["commands_live_disabled"] is False
    assert latest["evidence_wait_packet"]["next_wake_contract"]["broker_submit_allowed"] is True
    assert latest["evidence_wait_packet"]["next_wake_contract"]["live_order_authority"] == "review_only"
    assert "Evidence wait packet: pass; release=hold_wait;" in stdout
    assert "commands_live_disabled=False; authority=review_only." in stdout
    assert latest["broker_orders_submitted"] == 0
