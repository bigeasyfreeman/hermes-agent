from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hermes_cli.signal_coo.action_ledger import ActionLedger
from hermes_cli.signal_coo.automation_policy import (
    ea_automation_decisions,
    finance_automation_decisions,
    gtm_automation_decision,
    load_torben_automation_policy,
    validate_automation_policy,
    write_automation_policy_artifact,
)
from hermes_cli.signal_coo.gtm_radar_adapter import build_torben_gtm_radar_adapter


def test_torben_automation_policy_allows_recommendations_and_blocks_mutations(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    policy = load_torben_automation_policy(profile_home=tmp_path)
    validation = validate_automation_policy(policy)
    gtm = gtm_automation_decision(action="draft_content", policy=policy)
    gtm_public = gtm_automation_decision(action="public_post", public_mutation=True, policy=policy)
    ea = ea_automation_decisions(policy=policy)
    finance = finance_automation_decisions(policy=policy)

    assert validation["status"] == "pass"
    assert gtm["decision"] == "allowed"
    assert gtm["auto_invoke_allowed"] is True
    assert gtm_public["decision"] == "approval_required"
    assert ea["recommendations"]["decision"] == "allowed"
    assert ea["relationship_learning"]["decision"] == "allowed"
    assert ea["email_send"]["decision"] == "approval_required"
    assert finance["research"]["decision"] == "allowed"
    assert finance["paper_canary"]["decision"] == "allowed"
    assert finance["monarch_research"]["decision"] == "allowed"
    assert finance["monarch_research"]["mutation_allowed"] is False
    assert finance["monarch_mutation"]["decision"] == "approval_required"
    assert finance["monarch_mutation"]["mutation_allowed"] is False
    assert finance["live_order"]["decision"] == "blocked"


def test_torben_automation_policy_verifier_writes_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    artifact = write_automation_policy_artifact(profile_home=tmp_path)

    assert artifact["status"] == "pass"
    assert artifact["decisions"]["gtm_recommendation"]["decision"] == "allowed"
    assert artifact["decisions"]["finance"]["monarch_research"]["decision"] == "allowed"
    assert artifact["decisions"]["finance"]["monarch_mutation"]["decision"] == "approval_required"
    assert artifact["decisions"]["finance"]["live_order"]["decision"] == "blocked"
    assert (tmp_path / "state" / "torben-automation-policy-latest.json").exists()


def test_gtm_radar_cooldown_suppresses_back_to_back_distinct_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = ActionLedger(tmp_path / "actions.json")
    state_path = tmp_path / "gtm-state.json"
    now = datetime(2026, 6, 27, 9, 25, tzinfo=timezone.utc)

    first = build_torben_gtm_radar_adapter(
        _radar_payload("gtm-1", "ActPlane"),
        ledger=ledger,
        state_path=state_path,
        now=now,
    )
    second = build_torben_gtm_radar_adapter(
        _radar_payload("gtm-2", "Color Matters"),
        ledger=ledger,
        state_path=state_path,
        now=now + timedelta(minutes=8),
    )

    assert first["wakeAgent"] is True
    assert first["automation_policy"]["decision"] == "allowed"
    assert "Automation policy:" in first["text"]
    assert second["wakeAgent"] is False
    assert second["reason"] == "gtm_radar_delivery_cooldown_active"
    assert second["suppressed_cooldown_count"] == 1
    assert second["automation_policy"]["decision"] == "allowed"


def _radar_payload(identifier: str, title: str) -> dict:
    return {
        "generated_at": "2026-06-27T09:00:00Z",
        "scanned_count": 10,
        "llm_judge": {"invoked": True, "model": "grok-test", "x_search_used": True, "status": "accepted"},
        "cron_audit": {"llm_invoked": True, "model": "grok-test", "x_search_used": True},
        "findings": [
            {
                "id": identifier,
                "fingerprint": f"{identifier}-fingerprint",
                "title": title,
                "summary": "Useful source for GTM narrative. It has an actionable angle.",
                "why_it_matters": "This can become a staged draft or source note.",
                "content_route": "longform_article",
                "pillar": "ai_engineering_leverage",
                "url": f"https://example.test/{identifier}",
                "llm_judged": True,
                "llm_score": 90,
            }
        ],
    }
