from __future__ import annotations

import json

from profiles.torben.scripts import torben_finance_repair_window_simulator


def _simulation_payload(status: str = "pass") -> dict:
    checks = {
        "active_repair_plan": True,
        "isolated_state_root": True,
        "source_state_sample_artifacts_unchanged": True,
        "tick_completed": True,
        "research_batch_succeeded": True,
        "research_selected_requested_samples": True,
        "sample_collector_collected": True,
        "sample_budget_open": True,
        "created_requested_canaries": True,
        "observed_requested_outcomes": True,
        "created_symbols_from_repair_plan": True,
        "live_order_authority_none": True,
        "zero_mutation_counters": True,
        "broker_review_not_attempted": True,
        "broker_place_not_attempted": True,
    }
    if status == "fail":
        checks["source_state_sample_artifacts_unchanged"] = False
    return {
        "task": "equity_repair_window_simulation",
        "schema_version": "equity_repair_window_simulation.v1",
        "generated_at": "2026-07-03T17:40:04Z",
        "status": status,
        "reason": "simulation_passed" if status == "pass" else "simulation_checks_failed",
        "repair_plan_source": "runtime_optimizer_before_simulation",
        "repair_plan": {
            "status": "needs_repair_samples",
            "target_new_samples": 3,
            "repair_samples_remaining": 3,
            "preferred_existing_symbols": ["BA"],
            "live_order_authority": "none",
        },
        "source_state_root": "/Users/ericfreeman/ratatosk/state",
        "simulation_state_root": "/tmp/ratatosk-repair-window-sim-test",
        "requested_samples": 3,
        "preferred_symbols": ["BA"],
        "candidate_symbols": ["BA", "BA", "BA"],
        "checks": checks,
        "errors": [] if status == "pass" else ["source_state_sample_artifacts_unchanged"],
        "read_only_broker": True,
        "broker_review_attempted": False,
        "broker_place_attempted": False,
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
        "torben_source_refresh": {
            "status": "success",
            "profile": "ratatosk",
            "root": "/Users/ericfreeman/ratatosk",
            "command": ["uv", "run", "python", "scripts/equity_repair_window_simulator.py", "--json"],
            "returncode": 0,
            "elapsed_seconds": 0.1,
            "stderr_tail": "",
            "live_safety_env": {
                "RATATOSK_LIVE_TRADING": "0",
                "ROBINHOOD_LIVE": "0",
            },
        },
    }


def test_finance_repair_window_simulator_command_accepts_bounds(monkeypatch):
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_STATE_ROOT", "/tmp/source-state")
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_SIMULATION_ROOT", "/tmp/simulation-state")
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_OUTPUT_PATH", "/tmp/repair-window.json")
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_MAX_SAMPLES", "2")
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_NO_PERSIST", "1")

    command = torben_finance_repair_window_simulator._ratatosk_repair_window_simulator_command()

    assert command == [
        "uv",
        "run",
        "python",
        "scripts/equity_repair_window_simulator.py",
        "--json",
        "--state-root",
        "/tmp/source-state",
        "--simulation-root",
        "/tmp/simulation-state",
        "--output-path",
        "/tmp/repair-window.json",
        "--max-samples",
        "2",
        "--no-persist",
    ]


def test_finance_repair_window_simulator_stays_quiet_after_safe_pass(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "repair-window-simulator.json"
    fixture.write_text(json.dumps(_simulation_payload()), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_FIXTURE", str(fixture))

    assert torben_finance_repair_window_simulator.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-repair-window-simulator-latest.json").read_text())

    assert latest["task"] == "torben_finance_repair_window_simulator"
    assert latest["adapter_task"] == "equity_repair_window_simulation"
    assert latest["wakeAgent"] is False
    assert latest["status"] == "pass"
    assert latest["source_refresh_safe"] is True
    assert latest["simulation_contract_safe"] is True
    assert latest["requested_samples"] == 3
    assert latest["candidate_symbols"] == ["BA", "BA", "BA"]
    assert latest["broker_orders_submitted"] == 0
    assert latest["live_order_authority"] == "none"
    assert (home / "state" / "torben-finance-repair-window-simulator-state.json").exists()
    assert (home / "state" / "torben-finance-repair-window-simulator-latest.txt").read_text() == ""


def test_finance_repair_window_simulator_alerts_once_on_contract_failure(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "repair-window-simulator-failed.json"
    fixture.write_text(json.dumps(_simulation_payload("fail")), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_FIXTURE", str(fixture))

    assert torben_finance_repair_window_simulator.main() == 0
    first_stdout = capsys.readouterr().out
    assert "Torben / Finance Repair Window Simulator" in first_stdout
    assert "Status: fail." in first_stdout
    assert "source_state_sample_artifacts_unchanged" in first_stdout
    assert "No broker order was placed" in first_stdout
    first = json.loads((home / "state" / "torben-finance-repair-window-simulator-latest.json").read_text())
    assert first["wakeAgent"] is True
    assert first["status"] == "fail"
    assert first["source_refresh_safe"] is True
    assert first["simulation_contract_safe"] is False
    assert first["broker_orders_submitted"] == 0

    assert torben_finance_repair_window_simulator.main() == 0
    assert capsys.readouterr().out == ""
    second = json.loads((home / "state" / "torben-finance-repair-window-simulator-latest.json").read_text())
    assert second["wakeAgent"] is False
    assert second["repair_window_simulation_fingerprint"] == first["repair_window_simulation_fingerprint"]


def test_finance_repair_window_simulator_alerts_when_source_refresh_loses_live_disabled_env(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _simulation_payload()
    payload["torben_source_refresh"]["live_safety_env"]["ROBINHOOD_LIVE"] = "1"
    fixture = tmp_path / "repair-window-simulator-unsafe-refresh.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_FIXTURE", str(fixture))

    assert torben_finance_repair_window_simulator.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-repair-window-simulator-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["status"] == "pass"
    assert latest["source_refresh_safe"] is False
    assert latest["simulation_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert "Torben / Finance Repair Window Simulator" in stdout
