from __future__ import annotations

from datetime import datetime, timezone

from profiles.torben.scripts.torben_weekly_behavior_audit import build_weekly_behavior_audit


def test_weekly_behavior_audit_promotes_only_validated_recurring_pattern():
    payload = build_weekly_behavior_audit(
        [
            {
                "id": "finance-radar-review-pattern",
                "surface": "finance",
                "pattern": "Repeated manual conversion of finance radar cards into thesis-review checklists.",
                "candidate_name": "finance-thesis-review-packager",
                "recurrence_count": 4,
                "non_obvious": True,
                "codifiable": True,
                "validation_plan": [
                    "Fixture with three FIN cards emits one review checklist and zero broker mutations.",
                    "Fixture with stale source evidence is rejected.",
                ],
                "source_refs": ["state:torben-finance-radar-latest.json", "runbook:finance-stage-only"],
            },
            {
                "id": "one-off-debug",
                "surface": "qa",
                "pattern": "One unusual local debug command.",
                "recurrence_count": 1,
                "non_obvious": True,
                "codifiable": True,
                "validation_plan": ["Would need more examples."],
            },
        ],
        now=datetime(2026, 6, 26, 21, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["recurring_patterns_count"] == 1
    assert payload["rejected_patterns_count"] == 1
    assert payload["proposed_skill_count"] == 1
    assert payload["proposed_runbook_update_count"] == 0
    assert payload["review_status"] == "draft_for_review"
    assert payload["live_installs"] == 0
    assert payload["external_mutations"] == 0
    candidate = payload["candidates"][0]
    assert candidate["candidate_type"] == "skill"
    assert candidate["recurring"] is True
    assert candidate["non_obvious"] is True
    assert candidate["codifiable"] is True
    assert candidate["validation_plan"]
    assert candidate["live_installed"] is False
    assert "No skill was installed" in payload["text"]


def test_weekly_behavior_audit_rejects_one_off_noise_without_padding():
    payload = build_weekly_behavior_audit(
        [
            {
                "id": "single-email-cleanup",
                "surface": "ea",
                "pattern": "One-off cleanup of a stale vendor email.",
                "recurrence_count": 1,
                "non_obvious": False,
                "codifiable": True,
                "validation_plan": [],
            }
        ],
        now=datetime(2026, 6, 26, 21, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is False
    assert payload["review_status"] == "nothing_worth_extracting"
    assert payload["candidates"] == []
    assert payload["rejected_patterns_count"] == 1
    assert payload["proposed_skill_count"] == 0
    assert payload["proposed_runbook_update_count"] == 0
    assert "Nothing worth extracting." in payload["text"]
    assert "No skill was installed" in payload["text"]


def test_weekly_behavior_audit_routes_project_specific_pattern_to_runbook_update():
    payload = build_weekly_behavior_audit(
        [
            {
                "id": "page-qa-selector-memory",
                "surface": "qa",
                "pattern": "Repeated page-specific selector and seed-data discoveries during QA.",
                "recurrence_count": 3,
                "non_obvious": True,
                "codifiable": True,
                "project_specific": True,
                "validation_plan": [
                    "Fixture with project selectors produces a repo-runbook update candidate, not a global skill."
                ],
                "review_path": "docs/testing-runbook.md",
            }
        ],
        now=datetime(2026, 6, 26, 21, 0, tzinfo=timezone.utc),
    )

    assert payload["wakeAgent"] is True
    assert payload["proposed_skill_count"] == 0
    assert payload["proposed_runbook_update_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["candidate_type"] == "runbook_update"
    assert candidate["review_path"] == "docs/testing-runbook.md"
    assert candidate["live_installed"] is False
