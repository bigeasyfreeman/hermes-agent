from __future__ import annotations

import json

from profiles.torben.scripts import torben_finance_go_live_packet


def _packet_payload(status: str = "blocked") -> dict:
    ready = status == "ready_to_submit"
    return {
        "task": "equity_go_live_operator_packet",
        "schema_version": "equity_go_live_operator_packet_v1",
        "generated_at": "2026-07-03T18:40:04Z",
        "status": status,
        "ready_to_submit": ready,
        "go_live_blocked": not ready,
        "read_only": True,
        "requested_signal_id": None,
        "resolved_signal_id": "EQ-20260703-TEST",
        "broker_review_attempted": False,
        "broker_place_attempted": False,
        "approval_created": False,
        "approval_modified": False,
        "halt_or_circuit_cleared": False,
        "live_flags_enabled": False,
        "operator_mandate": {
            "human_approval_required": True,
            "self_approval_allowed": False,
            "required_approval_scope": "one_shot_live_canary",
            "requires_exact_signal_id": True,
            "requires_explicit_agentic_account_number": True,
            "requires_all_risk_acknowledgements": True,
            "requires_scoped_live_flags_for_one_invocation_only": True,
            "requires_fresh_dry_run_after_approval": True,
        },
        "command_gates": {
            "one_shot_live_submit": {
                "available": ready,
                "reason": None if ready else "go_live_operator_packet_blocked",
                "requires_ready_to_submit": True,
                "blocked_by": [] if ready else ["missing_approval_artifact"],
            }
        },
        "commands": {
            "one_shot_live_submit": (
                "RATATOSK_LIVE_TRADING=true ROBINHOOD_LIVE=true "
                "ROBINHOOD_EQUITY_LIVE=true uv run python "
                "scripts/equity_live_canary_from_signal.py --signal-id EQ-20260703-TEST"
                if ready
                else None
            ),
        },
        "approval": {
            "approval_scope": "one_shot_live_canary" if ready else None,
            "approved": ready,
            "approved_by_present": ready,
            "approved_at_present": ready,
            "account_number_present": ready,
            "risk_acknowledgement_complete": ready,
        },
        "evidence_gates": {
            "operator_approval": {
                "passed": ready,
                "blockers": [] if ready else ["missing_approval_artifact"],
            }
        },
        "blockers": [] if ready else ["missing_approval_artifact"],
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
            "command": [
                "uv",
                "run",
                "python",
                "scripts/equity_go_live_packet.py",
                "--latest-research-candidate",
                "--skip-mcp-live-probe",
                "--json",
            ],
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


def test_finance_go_live_packet_command_defaults_to_latest_research_live_probe_skipped(monkeypatch):
    monkeypatch.delenv("TORBEN_FINANCE_GO_LIVE_PACKET_SIGNAL_ID", raising=False)
    monkeypatch.delenv("TORBEN_FINANCE_GO_LIVE_PACKET_MCP_LIVE_PROBE", raising=False)

    command = torben_finance_go_live_packet._ratatosk_go_live_packet_command()

    assert command == [
        "uv",
        "run",
        "python",
        "scripts/equity_go_live_packet.py",
        "--latest-research-candidate",
        "--skip-mcp-live-probe",
        "--json",
    ]


def test_finance_go_live_packet_command_accepts_signal_scope_and_state(monkeypatch):
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_SIGNAL_ID", "EQ-123")
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_STATE_ROOT", "/tmp/ratatosk-state")
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_OUTPUT", "/tmp/go-live.json")
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_NO_WRITE", "1")
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_MCP_LIVE_PROBE", "1")

    command = torben_finance_go_live_packet._ratatosk_go_live_packet_command()

    assert command == [
        "uv",
        "run",
        "python",
        "scripts/equity_go_live_packet.py",
        "--signal-id",
        "EQ-123",
        "--state-root",
        "/tmp/ratatosk-state",
        "--output",
        "/tmp/go-live.json",
        "--no-write",
        "--json",
    ]


def test_finance_go_live_packet_stays_quiet_after_blocked_safe_packet(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "go-live-packet.json"
    fixture.write_text(json.dumps(_packet_payload()), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_FIXTURE", str(fixture))

    assert torben_finance_go_live_packet.main() == 0
    assert capsys.readouterr().out == ""
    latest = json.loads((home / "state" / "torben-finance-go-live-packet-latest.json").read_text())

    assert latest["task"] == "torben_finance_go_live_packet"
    assert latest["adapter_task"] == "equity_go_live_operator_packet"
    assert latest["wakeAgent"] is False
    assert latest["status"] == "blocked"
    assert latest["ready_to_submit"] is False
    assert latest["go_live_blocked"] is True
    assert latest["source_refresh_safe"] is True
    assert latest["go_live_packet_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert latest["live_order_authority"] == "none"
    assert (home / "state" / "torben-finance-go-live-packet-state.json").exists()
    assert (home / "state" / "torben-finance-go-live-packet-latest.txt").read_text() == ""


def test_finance_go_live_packet_wakes_when_packet_becomes_ready(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "go-live-packet-ready.json"
    fixture.write_text(json.dumps(_packet_payload("ready_to_submit")), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_FIXTURE", str(fixture))

    assert torben_finance_go_live_packet.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-go-live-packet-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["status"] == "ready_to_submit"
    assert latest["ready_to_submit"] is True
    assert latest["go_live_blocked"] is False
    assert latest["go_live_packet_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert "Torben / Finance Go-Live Packet" in stdout
    assert "one_shot_live_submit_available=True" in stdout
    assert "No approval was created or modified" in stdout


def test_finance_go_live_packet_alerts_when_source_refresh_loses_live_disabled_env(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _packet_payload()
    payload["torben_source_refresh"]["live_safety_env"]["ROBINHOOD_LIVE"] = "1"
    fixture = tmp_path / "go-live-packet-unsafe-refresh.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_FIXTURE", str(fixture))

    assert torben_finance_go_live_packet.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-go-live-packet-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["status"] == "blocked"
    assert latest["source_refresh_safe"] is False
    assert latest["go_live_packet_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert "Torben / Finance Go-Live Packet" in stdout


def test_finance_go_live_packet_alerts_when_source_refresh_missing_equity_live_flag(
    tmp_path,
    monkeypatch,
    capsys,
):
    payload = _packet_payload()
    payload["torben_source_refresh"]["live_safety_env"].pop("ROBINHOOD_EQUITY_LIVE")
    fixture = tmp_path / "go-live-packet-missing-equity-live.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    home = tmp_path / "torben-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TORBEN_FINANCE_GO_LIVE_PACKET_FIXTURE", str(fixture))

    assert torben_finance_go_live_packet.main() == 0
    stdout = capsys.readouterr().out
    latest = json.loads((home / "state" / "torben-finance-go-live-packet-latest.json").read_text())

    assert latest["wakeAgent"] is True
    assert latest["status"] == "blocked"
    assert latest["source_refresh_safe"] is False
    assert latest["go_live_packet_contract_safe"] is True
    assert latest["broker_orders_submitted"] == 0
    assert "Torben / Finance Go-Live Packet" in stdout
