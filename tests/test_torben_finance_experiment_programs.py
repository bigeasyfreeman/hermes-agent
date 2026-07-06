from __future__ import annotations

import json

from profiles.torben.scripts import torben_finance_experiment_programs


def _programs_payload(status: str = "programs_prepared") -> dict:
    loop_status = "active" if status == "programs_prepared" else status
    return {
        "task": "equity_experiment_programs",
        "schema_version": "equity_experiment_programs.v1",
        "generated_at": "2026-07-04T01:20:00Z",
        "status": status,
        "optimization_mode": "paper_feedback_only",
        "state_root": "/Users/ericfreeman/ratatosk/state",
        "experiment_loops": ["risk-thresholds", "execution-tactics", "regime-detection"],
        "evidence": {
            "sample_count": 87,
            "calibrated_sample_count": 87,
            "repair_plan_status": "needs_repair_samples",
            "repair_target_new_samples": 3,
            "repair_preferred_symbols": ["BA"],
            "historical_policy_coverage_status": "covered",
            "live_order_authority": "none",
        },
        "loops": {
            "risk-thresholds": {
                "experiment_id": "equity-risk-thresholds-paper-v1",
                "loop_name": "risk-thresholds",
                "status": loop_status,
                "manual_approval_required": True,
                "live_order_authority": "none",
                "sample_window": {
                    "baseline_sample_count": 87,
                    "baseline_calibrated_sample_count": 87,
                    "target_new_samples": 3,
                },
            },
            "execution-tactics": {
                "experiment_id": "equity-execution-repair-priority-v1",
                "loop_name": "execution-tactics",
                "status": loop_status,
                "manual_approval_required": False,
                "live_order_authority": "none",
                "sample_window": {
                    "baseline_sample_count": 87,
                    "baseline_calibrated_sample_count": 87,
                    "target_new_samples": 3,
                },
            },
        },
        "read_only_broker": True,
        "broker_review_attempted": False,
        "broker_place_attempted": False,
        "live_order_authority": "none",
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
        "torben_source_refresh": {
            "status": "success",
            "profile": "ratatosk",
            "root": "/Users/ericfreeman/ratatosk",
            "command": ["uv", "run", "python", "scripts/equity_experiment_programs.py", "--json"],
            "returncode": 0,
            "elapsed_seconds": 0.1,
            "stderr_tail": "",
            "live_safety_env": {
                "RATATOSK_LIVE_TRADING": "0",
                "ROBINHOOD_LIVE": "0",
                "ROBINHOOD_EQUITY_LIVE": "0",
            },
        },
    }


def test_finance_experiment_programs_command_accepts_bounds(monkeypatch):
    monkeypatch.setenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_STATE_ROOT", "/tmp/source-state")
    monkeypatch.setenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_OUTPUT_PATH", "/tmp/programs.json")
    monkeypatch.setenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_NO_PERSIST", "1")

    command = torben_finance_experiment_programs._ratatosk_experiment_programs_command()

    assert command == [
        "uv",
        "run",
        "python",
        "scripts/equity_experiment_programs.py",
        "--json",
        "--state-root",
        "/tmp/source-state",
        "--output-path",
        "/tmp/programs.json",
        "--no-persist",
    ]


def test_finance_experiment_programs_stays_quiet_after_safe_programs_prepared(
    tmp_path,
    monkeypatch,
    capsys,
):
    fixture = tmp_path / "experiment-programs.json"
    fixture.write_text(json.dumps(_programs_payload()), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_FIXTURE", str(fixture))

    assert torben_finance_experiment_programs.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-experiment-programs-latest.json").read_text())

    assert latest["task"] == "torben_finance_experiment_programs"
    assert latest["adapter_task"] == "equity_experiment_programs"
    assert latest["wakeAgent"] is False
    assert latest["status"] == "programs_prepared"
    assert latest["source_refresh_safe"] is True
    assert latest["experiment_programs_contract_safe"] is True
    assert latest["active_loop_count"] == 2
    assert latest["active_loop_ids"] == [
        "equity-risk-thresholds-paper-v1",
        "equity-execution-repair-priority-v1",
    ]
    assert latest["source_refresh"]["live_safety_env"] == {
        "RATATOSK_LIVE_TRADING": "0",
        "ROBINHOOD_LIVE": "0",
        "ROBINHOOD_EQUITY_LIVE": "0",
    }
    assert latest["broker_orders_submitted"] == 0
    assert latest["live_order_authority"] == "none"
    assert (home / "state" / "torben-finance-experiment-programs-state.json").exists()
    assert (home / "state" / "torben-finance-experiment-programs-latest.txt").read_text() == ""


def test_finance_experiment_programs_alerts_once_on_contract_failure(tmp_path, monkeypatch, capsys):
    payload = _programs_payload()
    payload["loops"]["risk-thresholds"]["live_order_authority"] = "review_only"
    fixture = tmp_path / "experiment-programs-unsafe.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_FIXTURE", str(fixture))

    assert torben_finance_experiment_programs.main() == 0
    first_stdout = capsys.readouterr().out
    first = json.loads((home / "state" / "torben-finance-experiment-programs-latest.json").read_text())

    assert first["wakeAgent"] is True
    assert first["source_refresh_safe"] is True
    assert first["experiment_programs_contract_safe"] is False
    assert first["broker_orders_submitted"] == 0
    assert "Torben / Finance Experiment Programs" in first_stdout
    assert "contract_safe=False" in first_stdout
    assert "No broker order was placed" in first_stdout

    assert torben_finance_experiment_programs.main() == 0
    assert capsys.readouterr().out == ""
    second = json.loads((home / "state" / "torben-finance-experiment-programs-latest.json").read_text())
    assert second["wakeAgent"] is False
    assert second["experiment_programs_fingerprint"] == first["experiment_programs_fingerprint"]


def test_finance_experiment_programs_alerts_when_source_refresh_loses_live_disabled_env(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _programs_payload()
    payload["torben_source_refresh"]["live_safety_env"]["ROBINHOOD_EQUITY_LIVE"] = "1"
    fixture = tmp_path / "experiment-programs-unsafe-refresh.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_FIXTURE", str(fixture))

    assert torben_finance_experiment_programs.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-experiment-programs-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["source_refresh_safe"] is False
    assert latest["experiment_programs_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert "Torben / Finance Experiment Programs" in stdout
