from __future__ import annotations

import json

from profiles.torben.scripts import torben_finance_sample_collector


def _sample_collector_payload() -> dict:
    return {
        "task": "equity_paper_sample_collector",
        "generated_at": "2026-06-30T00:31:00Z",
        "status": "collected",
        "eligible_research_packet_count": 12,
        "existing_canary_count": 6,
        "selected_outcome_count": 11,
        "outcomes_observed": 11,
        "outcomes_blocked": 0,
        "canaries_created": [
            {"signal_id": "EQ-20260629-GOOGL-2912CC", "status": "passed"},
            {"signal_id": "EQ-20260629-NVDA-BF6754", "status": "passed"},
        ],
        "canaries_reconciled": [
            {"signal_id": "EQ-20260627-AAPL-FEF912", "status": "passed"},
        ],
        "outcomes": [
            {"signal_id": "EQ-20260629-GOOGL-2912CC", "status": "observed"},
            {"signal_id": "EQ-20260629-NVDA-BF6754", "status": "observed"},
        ],
        "paper_sample_count_before": 1,
        "paper_sample_count_after": 12,
        "sample_gap_before": 19,
        "sample_gap_after": 8,
        "calibrated_sample_count_after": 12,
        "calibration_sample_gap_after": 8,
        "live_order_authority": "none",
        "paper_performance_after": {
            "status": "insufficient",
            "sample_count": 12,
            "sample_gap": 8,
            "blocking_reasons": [
                "paper_performance_gate_failed:sample_count",
                "paper_performance_gate_failed:sharpe_ratio",
            ],
        },
        "signal_optimizer": {
            "status": "collecting_data",
            "promotion_decision": "blocked",
            "sample_count": 12,
            "sample_gap": 8,
            "calibrated_sample_count": 12,
            "calibrated_sample_gap": 8,
            "sample_acquisition_plan": {
                "status": "needs_paper_samples",
                "target_new_samples": 8,
                "non_overrepresented_sample_target": 8,
                "concentration_relief_samples_needed": 8,
                "avoid_symbols": ["AAPL"],
                "live_order_authority": "none",
            },
            "calibration_repair_plan": {
                "policy_id": "paper_feedback_calibration_repair_plan_v1",
                "status": "needs_repair_samples",
                "target_new_samples": 3,
                "target_total_sample_count": 90,
                "target_total_calibrated_sample_count": 90,
                "avoid_symbols": ["AMZN", "GOOGL"],
                "preferred_existing_symbols": ["MSFT", "COIN", "AAPL"],
                "preferred_symbol_details": [
                    {
                        "symbol": "MSFT",
                        "repair_priority_rank": 1,
                        "repair_priority_score": 4.8,
                        "preference_sources": ["positive_paper_return"],
                        "live_order_authority": "none",
                    }
                ],
                "live_order_authority": "none",
            },
            "historical_policy_coverage": {
                "status": "covered",
                "target_new_samples": 3,
                "repair_preferred_symbols": ["MSFT", "COIN", "AAPL"],
                "missing_repair_preferred_symbols": [],
                "missing_count": 0,
                "live_order_authority": "none",
            },
            "recommended_action_ids": [
                "collect_more_paper_samples",
                "diversify_paper_candidates",
            ],
        },
        "experiment_evaluation": {
            "present": True,
            "status": "waiting_for_target_samples",
            "history_appended_count": 0,
            "live_order_authority": "none",
            "loops": {
                "risk-thresholds": {
                    "decision": "wait",
                    "samples_remaining": 3,
                    "calibrated_samples_remaining": 3,
                    "history_appended": False,
                }
            },
        },
        "active_experiment_sample_window": {
            "status": "active",
            "source": "experiment_evaluation_artifact",
            "waiting_loop_count": 1,
            "new_sample_cap": 3,
            "live_order_authority": "none",
            "waiting_loops": [
                {
                    "loop_name": "risk-thresholds",
                    "experiment_id": "equity-risk-thresholds-paper-v1",
                    "samples_remaining": 3,
                    "calibrated_samples_remaining": 3,
                    "new_samples_remaining": 3,
                    "manual_approval_required": True,
                    "live_order_authority": "none",
                }
            ],
        },
        "read_only_broker": True,
        "broker_review_attempted": False,
        "broker_place_attempted": False,
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


def test_finance_sample_collector_command_uses_bounded_defaults(monkeypatch):
    monkeypatch.delenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_MAX_CANDIDATES", raising=False)
    monkeypatch.delenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_MAX_OUTCOMES", raising=False)

    command = torben_finance_sample_collector._ratatosk_sample_collector_command()

    assert command[0:5] == [
        "uv",
        "run",
        "python",
        "scripts/equity_paper_sample_collector.py",
        "--json",
    ]
    assert command[command.index("--max-candidates") + 1] == "3"
    assert command[command.index("--max-outcomes") + 1] == "3"


def test_finance_sample_collector_command_allows_bounded_overrides(monkeypatch):
    monkeypatch.setenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_MAX_CANDIDATES", "5")
    monkeypatch.setenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_MAX_OUTCOMES", "7")

    command = torben_finance_sample_collector._ratatosk_sample_collector_command()

    assert command[command.index("--max-candidates") + 1] == "5"
    assert command[command.index("--max-outcomes") + 1] == "7"


def test_finance_sample_collector_wakes_once_per_changed_fingerprint(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "sample-collector.json"
    fixture.write_text(json.dumps(_sample_collector_payload()), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_FIXTURE", str(fixture))

    assert torben_finance_sample_collector.main() == 0
    first_stdout = capsys.readouterr().out
    assert "Torben / Finance Sample Collector" in first_stdout
    assert "Sample plan: target_new=8; non_overrepresented=8; avoid=AAPL." in first_stdout
    assert (
        "Calibration repair plan: target_new=3; preferred=MSFT,COIN,AAPL; avoid=AMZN,GOOGL."
        in first_stdout
    )
    assert "Historical policy coverage: covered; missing=none." in first_stdout
    assert "Experiment evaluator: waiting_for_target_samples; history_appended=0." in first_stdout
    assert "Experiment sample window: active; new_sample_cap=3; waiting_loops=1." in first_stdout
    assert "Safety: source_refresh_safe=True; sample_collector_contract_safe=True; authority=none." in first_stdout
    assert "No broker order was placed" in first_stdout
    first = json.loads((home / "state" / "torben-finance-sample-collector-latest.json").read_text(encoding="utf-8"))
    assert first["task"] == "torben_finance_sample_collector"
    assert first["adapter_task"] == "equity_paper_sample_collector"
    assert first["wakeAgent"] is True
    assert first["source_refresh_safe"] is True
    assert first["sample_collector_contract_safe"] is True
    assert first["source_refresh"]["live_safety_env"] == {
        "RATATOSK_LIVE_TRADING": "0",
        "ROBINHOOD_LIVE": "0",
        "ROBINHOOD_EQUITY_LIVE": "0",
    }
    assert first["outcomes_observed"] == 11
    assert first["sample_before"] == 1
    assert first["sample_after"] == 12
    assert first["sample_gap_before"] == 19
    assert first["sample_gap_after"] == 8
    assert first["calibrated_sample_count_after"] == 12
    assert first["calibration_sample_gap_after"] == 8
    assert first["optimizer"]["promotion_decision"] == "blocked"
    assert first["optimizer"]["sample_gap"] == 8
    assert first["optimizer"]["calibrated_sample_gap"] == 8
    assert first["optimizer"]["sample_acquisition_plan"]["non_overrepresented_sample_target"] == 8
    assert first["experiment_evaluation"]["status"] == "waiting_for_target_samples"
    assert first["experiment_evaluation"]["loops"]["risk-thresholds"]["samples_remaining"] == 3
    assert first["active_experiment_sample_window"]["status"] == "active"
    assert first["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert first["active_experiment_sample_window"]["waiting_loops"][0]["loop_name"] == "risk-thresholds"
    assert first["signal_optimizer"]["calibrated_sample_gap"] == 8
    assert first["signal_optimizer"]["sample_acquisition_plan"]["avoid_symbols"] == ["AAPL"]
    assert first["signal_optimizer"]["calibration_repair_plan"]["target_new_samples"] == 3
    assert first["signal_optimizer"]["calibration_repair_plan"]["preferred_existing_symbols"] == [
        "MSFT",
        "COIN",
        "AAPL",
    ]
    assert first["signal_optimizer"]["calibration_repair_plan"]["live_order_authority"] == "none"
    assert first["signal_optimizer"]["historical_policy_coverage"]["status"] == "covered"
    assert first["signal_optimizer"]["historical_policy_coverage"]["live_order_authority"] == "none"
    assert first["live_order_authority"] == "none"
    assert first["read_only_broker"] is True
    assert first["broker_review_attempted"] is False
    assert first["broker_place_attempted"] is False
    assert first["mutation_counters"]["broker_orders_submitted"] == 0
    assert first["broker_orders_submitted"] == 0
    assert (home / "state" / "torben-finance-sample-collector-state.json").exists()

    assert torben_finance_sample_collector.main() == 0
    assert capsys.readouterr().out == ""
    second = json.loads((home / "state" / "torben-finance-sample-collector-latest.json").read_text(encoding="utf-8"))
    assert second["wakeAgent"] is False
    assert second["source_refresh_safe"] is True
    assert second["sample_collector_contract_safe"] is True
    assert second["sample_collection_fingerprint"] == first["sample_collection_fingerprint"]
    assert (home / "state" / "torben-finance-sample-collector-latest.txt").read_text(encoding="utf-8") == ""


def test_finance_sample_collector_stays_silent_when_idle(tmp_path, monkeypatch, capsys):
    payload = _sample_collector_payload() | {
        "status": "idle",
        "outcomes_observed": 0,
        "outcomes": [],
        "canaries_created": [],
        "canaries_reconciled": [],
    }
    fixture = tmp_path / "sample-collector-idle.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_FIXTURE", str(fixture))

    assert torben_finance_sample_collector.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-sample-collector-latest.json").read_text(encoding="utf-8"))
    assert latest["wakeAgent"] is False
    assert latest["sample_after"] == 12
    assert latest["sample_gap_after"] == 8
    assert latest["optimizer"]["promotion_decision"] == "blocked"
    assert latest["optimizer"]["calibrated_sample_gap"] == 8
    assert latest["optimizer"]["sample_acquisition_plan"]["target_new_samples"] == 8
    assert latest["active_experiment_sample_window"]["new_sample_cap"] == 3
    assert latest["source_refresh_safe"] is True
    assert latest["sample_collector_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0


def test_finance_sample_collector_alerts_when_source_refresh_loses_equity_live_disable(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _sample_collector_payload() | {
        "status": "idle",
        "torben_source_refresh": {
            "status": "success",
            "profile": "fixture",
            "root": "fixture",
            "command": ["fixture"],
            "returncode": 0,
            "elapsed_seconds": 0,
            "stderr_tail": "",
            "live_safety_env": {
                "RATATOSK_LIVE_TRADING": "0",
                "ROBINHOOD_LIVE": "0",
                "ROBINHOOD_EQUITY_LIVE": "1",
            },
        },
    }
    fixture = tmp_path / "sample-collector-source-unsafe.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_FIXTURE", str(fixture))

    assert torben_finance_sample_collector.main() == 0
    stdout = capsys.readouterr().out
    assert "Torben / Finance Sample Collector" in stdout
    assert "Safety: source_refresh_safe=False; sample_collector_contract_safe=True; authority=none." in stdout
    latest = json.loads((home / "state" / "torben-finance-sample-collector-latest.json").read_text(encoding="utf-8"))
    assert latest["wakeAgent"] is True
    assert latest["source_refresh_safe"] is False
    assert latest["sample_collector_contract_safe"] is True
    assert latest["source_refresh"]["live_safety_env"]["ROBINHOOD_EQUITY_LIVE"] == "1"
    assert latest["broker_orders_submitted"] == 0


def test_finance_sample_collector_alerts_when_collector_contract_loses_no_authority(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _sample_collector_payload() | {
        "status": "idle",
        "live_order_authority": "review_only",
    }
    fixture = tmp_path / "sample-collector-contract-unsafe.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_FIXTURE", str(fixture))

    assert torben_finance_sample_collector.main() == 0
    stdout = capsys.readouterr().out
    assert "Torben / Finance Sample Collector" in stdout
    assert (
        "Safety: source_refresh_safe=True; sample_collector_contract_safe=False; authority=review_only."
        in stdout
    )
    latest = json.loads((home / "state" / "torben-finance-sample-collector-latest.json").read_text(encoding="utf-8"))
    assert latest["wakeAgent"] is True
    assert latest["source_refresh_safe"] is True
    assert latest["sample_collector_contract_safe"] is False
    assert latest["live_order_authority"] == "review_only"
    assert latest["broker_orders_submitted"] == 0
