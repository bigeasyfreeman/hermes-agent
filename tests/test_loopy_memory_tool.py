from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.loopy_memory_tool import (
    parse_memory_entries,
    task_memory_review,
    weekly_memory_review,
)
from tools.registry import registry


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "profile"
    (home / "memories").mkdir(parents=True)
    return home


def _memory(home: Path) -> Path:
    return home / "memories" / "MEMORY.md"


def test_task_review_defaults_to_dry_run_and_requires_profile_memory_path(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _memory(home).write_text("Legacy fact\n", encoding="utf-8")

    payload = task_memory_review(
        hermes_home=home,
        source="test-task",
        entries=[{"note": "When Torben changes a durable workflow, update the governing backend prompt."}],
    )

    assert payload["success"] is True
    assert payload["applied"] is False
    assert "Loopy Memory Entries" in payload["proposed_diff"]
    assert _memory(home).read_text(encoding="utf-8") == "Legacy fact\n"

    with pytest.raises(ValueError):
        task_memory_review(
            hermes_home=home,
            memory_path=tmp_path / "other" / "MEMORY.md",
            source="test-task",
            entries=[{"note": "Should not write outside the profile memory file."}],
            apply=True,
        )


def test_task_review_applies_tagged_entry_and_rejects_secret_like_content(tmp_path: Path) -> None:
    home = _home(tmp_path)

    payload = task_memory_review(
        hermes_home=home,
        source="task-123",
        trust="canonical",
        today="2026-06-28",
        entries=[{"note": "Canonical rules require explicit human approval or official docs."}],
        apply=True,
    )

    assert payload["success"] is True
    assert payload["applied"] is True
    entries = parse_memory_entries(_memory(home).read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0].trust == "canonical"
    assert entries[0].date == "2026-06-28"
    assert entries[0].source == "task-123"
    assert entries[0].status == "active"

    blocked = task_memory_review(
        hermes_home=home,
        source="task-123",
        entries=[{"note": "Do not store OPENAI_API_KEY=sk-live-secret-value-here in memory."}],
        apply=True,
    )

    assert blocked["success"] is False
    assert blocked["code"] == "secret_policy_violation"


def test_task_review_marks_duplicate_lower_precedence_entry_stale(tmp_path: Path) -> None:
    home = _home(tmp_path)
    note = "Preserve OpenClaw as the user-facing surface and Hermes as executor."
    task_memory_review(
        hermes_home=home,
        source="older-task",
        trust="temporary",
        today="2026-06-20",
        entries=[{"note": note}],
        apply=True,
    )

    payload = task_memory_review(
        hermes_home=home,
        source="newer-task",
        trust="canonical",
        today="2026-06-28",
        entries=[{"note": note}],
        apply=True,
    )

    assert payload["added_count"] == 1
    assert payload["updated_existing_count"] == 1
    entries = parse_memory_entries(_memory(home).read_text(encoding="utf-8"))
    assert [entry.status for entry in entries] == ["stale", "active"]
    assert entries[0].merged_into == entries[1].entry_id


def test_weekly_review_backs_up_and_marks_old_or_external_fact_entries_needs_review(tmp_path: Path) -> None:
    home = _home(tmp_path)
    task_memory_review(
        hermes_home=home,
        source="old-task",
        trust="project",
        today="2026-05-01",
        entries=[{"note": "The latest broker OAuth status is ready."}],
        apply=True,
    )

    payload = weekly_memory_review(
        hermes_home=home,
        today="2026-06-28",
        stale_after_days=30,
        apply=True,
    )

    assert payload["success"] is True
    assert payload["backup_path"]
    assert Path(payload["backup_path"]).exists()
    assert payload["stats"]["marked_needs_review"] == 1
    entries = parse_memory_entries(_memory(home).read_text(encoding="utf-8"))
    assert entries[0].status == "needs-review"
    assert "older_than_30d" in entries[0].review_reason
    assert "external_fact_recheck_required" in entries[0].review_reason


def test_loopy_memory_tools_are_registered_and_dispatchable(tmp_path: Path) -> None:
    home = _home(tmp_path)
    for name in ("loopy_memory_task_review", "loopy_memory_weekly_review"):
        assert registry.get_entry(name) is not None

    raw = registry.dispatch(
        "loopy_memory_task_review",
        {
            "hermes_home": str(home),
            "source": "dispatch-test",
            "date": "2026-06-28",
            "entries": [{"note": "Use tagged memory entries for durable cross-session rules."}],
            "apply": True,
        },
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["added_count"] == 1
