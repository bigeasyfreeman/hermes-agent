from __future__ import annotations

import json

from profiles.torben.scripts import torben_finance_next_wake_runner


def _runner_payload(status: str = "executed") -> dict:
    return {
        "task": "equity_next_wake_runner",
        "generated_at": "2026-07-03T09:11:39Z",
        "status": status,
        "errors": [] if status == "executed" else ["wake_recheck_command_failed"],
        "due": True,
        "ready_now": False,
        "next_recheck_after_utc": "2026-07-03T09:41:39Z",
        "bounded_collection_not_before_utc": "2026-07-06T13:30:00Z",
        "budget_reopens_after_utc": "2026-07-04T00:00:00Z",
        "market_scan_recheck_after_utc": "2026-07-06T13:30:00Z",
        "required_operator_action": "continue_wait",
        "wake_reason_ids": [
            "daily_paper_sample_budget_exhausted",
            "market_closed_scan_supply",
            "release_signal_absent",
        ],
        "execute_requested": True,
        "execution_attempted": True,
        "safe_command_ids": [
            "bounded_paper_sample_collection",
            "recheck_evidence_wait_packet",
            "recheck_research_candidate_supply",
            "recheck_stop_condition",
            "recheck_trading_loop_tick_scan_only",
        ],
        "command_results": [
            {
                "command_id": "bounded_paper_sample_collection",
                "returncode": 0,
            },
            {
                "command_id": "recheck_evidence_wait_packet",
                "returncode": 0,
            },
            {
                "command_id": "recheck_stop_condition",
                "returncode": 0 if status == "executed" else 2,
            },
        ],
        "commands_live_disabled": True,
        "broker_submit_allowed": False,
        "human_live_review_allowed": False,
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
            "command": ["uv", "run", "python", "scripts/equity_next_wake_runner.py", "--json", "--execute"],
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


def test_finance_next_wake_runner_command_executes_by_default(monkeypatch):
    monkeypatch.delenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_EXECUTE", raising=False)

    command = torben_finance_next_wake_runner._ratatosk_next_wake_runner_command()

    assert command == [
        "uv",
        "run",
        "python",
        "scripts/equity_next_wake_runner.py",
        "--json",
        "--execute",
    ]


def test_finance_next_wake_runner_command_allows_report_only(monkeypatch):
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_EXECUTE", "0")

    command = torben_finance_next_wake_runner._ratatosk_next_wake_runner_command()

    assert command == [
        "uv",
        "run",
        "python",
        "scripts/equity_next_wake_runner.py",
        "--json",
    ]


def test_finance_next_wake_runner_command_accepts_explicit_execute(monkeypatch):
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_EXECUTE", "0")

    command = torben_finance_next_wake_runner._ratatosk_next_wake_runner_command(execute=True)

    assert command == [
        "uv",
        "run",
        "python",
        "scripts/equity_next_wake_runner.py",
        "--json",
        "--execute",
    ]


def test_finance_next_wake_runner_offhours_holds_bounded_collection(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _runner_payload("ready")
    payload["ready_now"] = True
    payload["execute_requested"] = False
    payload["execution_attempted"] = False
    payload["command_results"] = []
    payload["torben_source_refresh"]["command"] = [
        "uv",
        "run",
        "python",
        "scripts/equity_next_wake_runner.py",
        "--json",
    ]
    fixture = tmp_path / "next-wake-runner-ready.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE", str(fixture))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_BLOCK_BOUNDED", "1")

    assert torben_finance_next_wake_runner.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())

    assert latest["status"] == "held_bounded_collection_offhours"
    assert latest["wakeAgent"] is False
    assert latest["offhours_recheck_mode"] is True
    assert latest["offhours_bounded_collection_blocked"] is True
    assert latest["execution_block_reason"] == "bounded_paper_sample_collection_disabled_for_offhours_recheck"
    assert latest["execute_requested"] is False
    assert latest["execution_attempted"] is False
    assert latest["source_refresh_safe"] is True
    assert latest["runner_contract_safe"] is True
    assert latest["public_actions_taken"] == 0
    assert latest["external_mutations"] == 0
    assert latest["broker_orders_submitted"] == 0
    assert latest["live_order_authority"] == "none"


def test_finance_next_wake_runner_offhours_does_not_hold_before_due(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _runner_payload("not_due")
    payload["due"] = False
    payload["ready_now"] = False
    payload["execute_requested"] = False
    payload["execution_attempted"] = False
    payload["command_results"] = []
    fixture = tmp_path / "next-wake-runner-not-due.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE", str(fixture))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_BLOCK_BOUNDED", "1")

    assert torben_finance_next_wake_runner.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())

    assert latest["status"] == "not_due"
    assert latest["wakeAgent"] is False
    assert "offhours_bounded_collection_blocked" not in latest
    assert latest["execute_requested"] is False
    assert latest["execution_attempted"] is False
    assert latest["source_refresh_safe"] is True
    assert latest["runner_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0


def test_finance_next_wake_runner_offhours_executes_due_non_bounded_rechecks(
    tmp_path,
    monkeypatch,
    capsys,
):
    calls: list[list[str]] = []
    report_only = _runner_payload("due_recheck_required")
    report_only["ready_now"] = False
    report_only["execute_requested"] = False
    report_only["execution_attempted"] = False
    report_only["safe_command_ids"] = [
        "recheck_evidence_wait_packet",
        "recheck_research_candidate_supply",
        "recheck_stop_condition",
    ]
    report_only["command_results"] = []
    executed = _runner_payload("executed")

    def fake_run_ratatosk_command(command, *, root, timeout_seconds):  # noqa: ARG001
        calls.append(list(command))
        payload = executed if "--execute" in command else report_only
        source_refresh = {
            "status": "success",
            "profile": "ratatosk",
            "root": str(root),
            "command": list(command),
            "returncode": 0,
            "elapsed_seconds": 0.1,
            "stderr_tail": "",
            "live_safety_env": {
                "RATATOSK_LIVE_TRADING": "0",
                "ROBINHOOD_LIVE": "0",
                "ROBINHOOD_EQUITY_LIVE": "0",
            },
        }
        return dict(payload), source_refresh

    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_BLOCK_BOUNDED", "1")
    monkeypatch.setattr(torben_finance_next_wake_runner, "_run_ratatosk_command", fake_run_ratatosk_command)

    assert torben_finance_next_wake_runner.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())

    assert len(calls) == 2
    assert "--execute" not in calls[0]
    assert "--execute" in calls[1]
    assert latest["status"] == "executed"
    assert latest["wakeAgent"] is False
    assert latest["source_refresh"]["command"] == calls[1]
    assert latest["source_refresh_safe"] is True
    assert latest["runner_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0


def test_finance_next_wake_runner_stays_quiet_after_success(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "next-wake-runner.json"
    fixture.write_text(json.dumps(_runner_payload()), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE", str(fixture))

    assert torben_finance_next_wake_runner.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())

    assert latest["task"] == "torben_finance_next_wake_runner"
    assert latest["adapter_task"] == "equity_next_wake_runner"
    assert latest["wakeAgent"] is False
    assert latest["status"] == "executed"
    assert latest["source_refresh_safe"] is True
    assert latest["runner_contract_safe"] is True
    assert latest["market_scan_recheck_after_utc"] == "2026-07-06T13:30:00Z"
    assert latest["bounded_collection_not_before_utc"] == "2026-07-06T13:30:00Z"
    assert latest["broker_orders_submitted"] == 0
    assert latest["live_order_authority"] == "none"
    assert (home / "state" / "torben-finance-next-wake-runner-state.json").exists()
    assert (home / "state" / "torben-finance-next-wake-runner-latest.txt").read_text() == ""


def test_finance_next_wake_runner_alerts_once_on_failure(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "next-wake-runner-failed.json"
    fixture.write_text(json.dumps(_runner_payload("command_failed")), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE", str(fixture))

    assert torben_finance_next_wake_runner.main() == 0
    first_stdout = capsys.readouterr().out
    assert "Torben / Finance Next Wake Runner" in first_stdout
    assert "failed_commands=1" in first_stdout
    assert "Market scan recheck: 2026-07-06T13:30:00Z." in first_stdout
    assert (
        "Safety: commands_live_disabled=True; broker_submit_allowed=False; "
        "human_live_review_allowed=False; authority=none."
    ) in first_stdout
    assert "No broker order was placed" in first_stdout
    first = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())
    assert first["wakeAgent"] is True
    assert first["status"] == "command_failed"
    assert first["source_refresh_safe"] is True
    assert first["runner_contract_safe"] is True
    assert first["broker_orders_submitted"] == 0

    assert torben_finance_next_wake_runner.main() == 0
    assert capsys.readouterr().out == ""
    second = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())
    assert second["wakeAgent"] is False
    assert second["next_wake_runner_fingerprint"] == first["next_wake_runner_fingerprint"]


def test_finance_next_wake_runner_alerts_when_runner_contract_loses_live_disabled_proof(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _runner_payload("not_due")
    payload["due"] = False
    payload["execution_attempted"] = False
    payload["commands_live_disabled"] = False
    payload["broker_submit_allowed"] = True
    payload["live_order_authority"] = "review_only"
    fixture = tmp_path / "next-wake-runner-unsafe.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE", str(fixture))

    assert torben_finance_next_wake_runner.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["status"] == "not_due"
    assert latest["source_refresh_safe"] is True
    assert latest["runner_contract_safe"] is False
    assert latest["broker_orders_submitted"] == 0
    assert (
        "Safety: commands_live_disabled=False; broker_submit_allowed=True; "
        "human_live_review_allowed=False; authority=review_only."
    ) in stdout


def test_finance_next_wake_runner_alerts_when_source_refresh_loses_live_disabled_env(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _runner_payload("not_due")
    payload["due"] = False
    payload["execution_attempted"] = False
    payload["torben_source_refresh"]["live_safety_env"]["ROBINHOOD_LIVE"] = "1"
    fixture = tmp_path / "next-wake-runner-unsafe-refresh.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE", str(fixture))

    assert torben_finance_next_wake_runner.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["status"] == "not_due"
    assert latest["source_refresh_safe"] is False
    assert latest["runner_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert "Torben / Finance Next Wake Runner" in stdout


def test_finance_next_wake_runner_alerts_when_equity_live_guard_missing(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _runner_payload("not_due")
    payload["due"] = False
    payload["execution_attempted"] = False
    del payload["torben_source_refresh"]["live_safety_env"]["ROBINHOOD_EQUITY_LIVE"]
    fixture = tmp_path / "next-wake-runner-missing-equity-guard.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE", str(fixture))

    assert torben_finance_next_wake_runner.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-next-wake-runner-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["source_refresh_safe"] is False
    assert latest["runner_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert "Torben / Finance Next Wake Runner" in stdout
