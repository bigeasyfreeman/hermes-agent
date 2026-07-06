from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from hermes_cli.signal_coo.action_ledger import ActionLedger
from hermes_cli.signal_coo.monarch_savings import (
    MonarchReadOnlyClient,
    MonarchReadOnlyToolBlocked,
    analyze_monarch_savings_packet,
    build_torben_monarch_savings_payload,
    is_monarch_mutation_tool,
)


def test_monarch_savings_fixture_detects_weekly_savings_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    now = datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc)

    candidates = analyze_monarch_savings_packet(_weekly_fixture(), loop="weekly", now=now)
    candidate_types = {candidate["candidate_type"] for candidate in candidates}

    assert "downgrade_review" in candidate_types
    assert "price_increase" in candidate_types
    assert "duplicate_charge" in candidate_types
    assert "category_spike" in candidate_types
    assert all(candidate["monarch_write_allowed"] is False for candidate in candidates)

    payload = build_torben_monarch_savings_payload(
        _weekly_fixture(),
        loop="weekly",
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "state.json",
        now=now,
        stage_actions=True,
        force_wake=True,
    )

    assert payload["wakeAgent"] is True
    assert payload["status"] == "review_ready"
    assert payload["policy_decision_present"] is True
    assert payload["redaction_status"] == "pass"
    assert payload["monarch_write_calls"] == 0
    assert payload["external_mutations"] == 0
    assert payload["estimated_annual_savings"] > 0
    assert payload["actions"]
    assert all(action["scope"] == "fin" for action in payload["actions"])
    assert "tool_results" not in payload
    assert "transactions" not in payload
    assert "transaction_id" not in json.dumps(payload)


def test_monarch_savings_fixture_detects_daily_large_charge(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    now = datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc)

    candidates = analyze_monarch_savings_packet(_daily_fixture(), loop="daily", now=now)

    assert {candidate["candidate_type"] for candidate in candidates} == {"unexpected_large_charge"}
    assert candidates[0]["merchant"] == "One-Off Vendor"
    assert candidates[0]["estimated_monthly_savings"] == 425


def test_monarch_savings_payload_fails_closed_if_mutation_counter_is_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    packet = {**_weekly_fixture(), "monarch_write_calls": 1}

    payload = build_torben_monarch_savings_payload(
        packet,
        loop="weekly",
        ledger=ActionLedger(tmp_path / "actions.json"),
        state_path=tmp_path / "state.json",
        now=datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["status"] == "fail_closed"
    assert payload["actions"] == []
    assert payload["candidates"] == []
    assert payload["monarch_write_calls"] == 1


def test_monarch_read_only_client_dispatches_allowlisted_reads():
    calls: list[tuple[str, dict]] = []

    def dispatch(name: str, args: dict) -> str:
        calls.append((name, args))
        return json.dumps({"result": {"transactions": [{"merchant": "Example", "amount": 12}]}})

    client = MonarchReadOnlyClient(dispatcher=dispatch)

    result = client.call_read_tool("GetTransactions", {"limit": 1})

    assert result == {"transactions": [{"merchant": "Example", "amount": 12}]}
    assert calls == [("mcp_monarch_money_mcp_GetTransactions", {"limit": 1})]
    assert client.read_tool_calls[0]["tool"] == "GetTransactions"


def test_monarch_read_only_client_blocks_mutation_tools_before_dispatch():
    def dispatch(_name: str, _args: dict) -> str:  # pragma: no cover - must never be called
        raise AssertionError("mutation tool reached dispatcher")

    client = MonarchReadOnlyClient(dispatcher=dispatch)

    with pytest.raises(MonarchReadOnlyToolBlocked):
        client.call_read_tool("UpdateTransaction", {"id": "txn_123", "amount": 1})

    assert is_monarch_mutation_tool("UpdateTransaction") is True
    assert client.blocked_tool_calls == [
        {
            "tool": "UpdateTransaction",
            "status": "blocked",
            "reason": "monarch_read_only_allowlist",
            "argument_keys": ["amount", "id"],
        }
    ]


def _weekly_fixture() -> dict:
    return {
        "source": "fixture",
        "loop": "weekly",
        "source_window": {
            "transactions_start_date": "2026-01-01",
            "transactions_end_date": "2026-06-27",
        },
        "read_tool_calls": [
            {"tool": "GetRecurring", "status": "ok"},
            {"tool": "GetTransactions", "status": "ok"},
            {"tool": "GetSpendingByCategory", "status": "ok"},
            {"tool": "GetBudget", "status": "ok"},
        ],
        "blocked_tool_calls": [],
        "recurring": [
            {
                "merchant": "Acme Cloud License",
                "category": "Software",
                "amount": 120,
                "cadence": "monthly",
            }
        ],
        "transactions": [
            {"merchant": "Deploy SaaS", "category": "Software", "amount": 55, "date": "2026-06-25"},
            {"merchant": "Deploy SaaS", "category": "Software", "amount": 30, "date": "2026-05-25"},
            {"merchant": "Deploy SaaS", "category": "Software", "amount": 31, "date": "2026-04-25"},
            {"merchant": "Deploy SaaS", "category": "Software", "amount": 29, "date": "2026-03-25"},
            {"merchant": "BillingCo", "category": "Ops", "amount": 88.00, "date": "2026-06-24"},
            {"merchant": "BillingCo", "category": "Ops", "amount": 87.99, "date": "2026-06-23"},
        ],
        "category_spend_current": [{"category": "Dining", "amount": 500}],
        "category_spend_baseline": [{"category": "Dining", "amount": 250}],
    }


def _daily_fixture() -> dict:
    return {
        "source": "fixture",
        "loop": "daily",
        "source_window": {
            "transactions_start_date": "2026-06-20",
            "transactions_end_date": "2026-06-27",
        },
        "read_tool_calls": [{"tool": "GetTransactions", "status": "ok"}],
        "blocked_tool_calls": [],
        "transactions": [
            {"merchant": "One-Off Vendor", "category": "Misc", "amount": 425, "date": "2026-06-26"}
        ],
    }
