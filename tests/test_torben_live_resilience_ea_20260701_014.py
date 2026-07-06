from __future__ import annotations

import importlib.util
import json
import socket
import urllib.error
from pathlib import Path

from hermes_cli.signal_coo import google_evidence
from profiles.torben.scripts import torben_finance_loop_heartbeat, torben_finance_risk_monitor


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return b'{"ok": true}'


def _load_calendar_watchdog():
    script_path = Path(__file__).resolve().parents[1] / "profiles/torben/scripts/torben_calendar_alignment_audit.py"
    spec = importlib.util.spec_from_file_location("torben_calendar_alignment_audit_resilience_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_google_evidence_retries_transient_urlerror_socket_gaierror(monkeypatch):
    calls = []
    sleeps = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise urllib.error.URLError(socket.gaierror(-2, "nodename nor servname provided"))
        return _FakeResponse()

    monkeypatch.setattr(google_evidence.urllib.request, "urlopen", fake_urlopen)

    payload = google_evidence._google_get(
        "https://www.googleapis.com/calendar/v3/test",
        "token",
        attempts=2,
        backoff_seconds=0.01,
        sleep=sleeps.append,
    )

    assert payload == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [0.01]


def test_calendar_alignment_fail_soft_skips_sync_writes_on_google_read_failure(monkeypatch, tmp_path, capsys):
    watchdog = _load_calendar_watchdog()
    home = tmp_path / "torben"
    (home / "config").mkdir(parents=True)
    (home / "state").mkdir(parents=True)
    sync_calls = []

    def failing_collect_google_ea_evidence(**kwargs):
        raise urllib.error.URLError(socket.gaierror(-2, "temporary failure in name resolution"))

    def forbidden_sync_calendar_alignment_blocks(**kwargs):
        sync_calls.append(kwargs)
        raise AssertionError("calendar sync writes must be skipped when Google reads fail")

    monkeypatch.setattr(watchdog, "get_hermes_home", lambda: home)
    monkeypatch.setattr(watchdog, "collect_google_ea_evidence", failing_collect_google_ea_evidence)
    monkeypatch.setattr(watchdog, "sync_calendar_alignment_blocks", forbidden_sync_calendar_alignment_blocks)

    assert watchdog.main() == 0

    assert sync_calls == []
    output = capsys.readouterr().out
    assert "skipped sync because Google reads failed" in output
    audit = json.loads((home / "state/torben-calendar-alignment-audit-latest.json").read_text())
    sync = (audit["ea"])["calendar_alignment_sync"]
    health = audit["source_diagnostics"]["google"]["source_health"]
    assert health["status"] == "failed"
    assert health["calendar_sync_skipped"] is True
    assert sync["status"] == "skipped_google_read_failure"
    assert sync["google_write_api_calls"] == 0
    assert sync["external_mutations"] == 0
    assert (home / "state/torben-calendar-alignment-source-health-latest.json").exists()


def _assert_zero_finance_failure_metadata(payload: dict) -> None:
    assert payload["source_refresh"]["live_safety_env"] == {
        "RATATOSK_LIVE_TRADING": "0",
        "ROBINHOOD_LIVE": "0",
        "ROBINHOOD_EQUITY_LIVE": "0",
    }
    assert payload["torben_source_refresh"]["live_safety_env"] == {
        "RATATOSK_LIVE_TRADING": "0",
        "ROBINHOOD_LIVE": "0",
        "ROBINHOOD_EQUITY_LIVE": "0",
    }
    assert payload["live_order_authority"] == "none"
    assert payload["public_actions_taken"] == 0
    assert payload["external_mutations"] == 0
    assert payload["orders_submitted"] == 0
    assert payload["broker_orders_submitted"] == 0
    assert payload["mutation_counters"] == {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def test_finance_loop_heartbeat_failure_artifact_preserves_live_disabled_metadata(tmp_path):
    previous = {
        "stop_condition": {
            "status": "wait_for_market_open_scan_supply",
            "primary_next_action": "wait_for_market_open_scan_supply",
            "release_conditions": ["scan_candidate_supply.market_open == true"],
            "live_order_authority": "none",
        }
    }
    (tmp_path / "torben-finance-loop-heartbeat-latest.json").write_text(json.dumps(previous))

    payload = torben_finance_loop_heartbeat._failure_payload(RuntimeError("boom"), state_dir=tmp_path)

    _assert_zero_finance_failure_metadata(payload)
    assert payload["stop_condition"]["status"] == "wait_for_market_open_scan_supply"
    assert payload["stop_condition"]["primary_next_action"] == "wait_for_market_open_scan_supply"
    assert payload["stop_condition"]["stale_after_source_refresh_failure"] is True


def test_finance_risk_monitor_failure_artifact_preserves_live_disabled_metadata(tmp_path):
    previous = {
        "stop_condition": {
            "status": "blocked",
            "primary_next_action": "expand_calibration_repair_candidate_universe",
            "release_conditions": ["verifier_debt_audit.status == pass"],
            "live_order_authority": "none",
        }
    }
    (tmp_path / "torben-finance-risk-monitor-latest.json").write_text(json.dumps(previous))

    payload = torben_finance_risk_monitor._failure_payload(RuntimeError("risk boom"), state_dir=tmp_path)

    _assert_zero_finance_failure_metadata(payload)
    assert payload["stop_condition"]["status"] == "blocked"
    assert payload["stop_condition"]["primary_next_action"] == "expand_calibration_repair_candidate_universe"
    assert payload["stop_condition"]["stale_after_source_refresh_failure"] is True
