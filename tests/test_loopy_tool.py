from __future__ import annotations

import json

from tools.loopy_tool import draft_loop, search_catalog, validate_loop_design
from tools.registry import registry


def test_loopy_catalog_search_ranks_relevant_loop():
    results = search_catalog(
        _catalog_fixture(),
        query="production logs errors root cause pull request",
        max_results=2,
    )

    assert results[0]["slug"] == "production-error-sweep"
    assert results[0]["title"] == "The production error sweep"
    assert results[0]["url"].endswith("/production-error-sweep/")


def test_loopy_validate_loop_flags_unbounded_prompt():
    payload = validate_loop_design("Improve this forever until happy. Publish the result.")

    assert payload["status"] == "needs_repair"
    assert payload["blocker_count"] >= 1
    codes = {finding["code"] for finding in payload["findings"]}
    assert "unbounded_stop" in codes
    assert "missing_verification" in codes


def test_loopy_draft_loop_returns_valid_prompt_and_blueprint():
    payload = draft_loop(
        name="Release-note reconciliation",
        outcome="keep release notes aligned with shipped code",
        success="release notes cite the shipped changes and tests pass",
        trigger="after a merge",
        scope="the merged diff, release notes, and test output",
        allowed_actions="update one stale release-note section",
        verification="run the release-note lint and relevant tests",
        stop="release notes are current or no stale section remains",
        approval_boundary="publishing or tagging a release",
        schedule="0 10 * * 1",
        enabled_toolsets=["coding", "loopy"],
    )

    assert payload["success"] is True
    assert payload["validation"]["status"] == "ready"
    assert payload["blueprint_ready"] is True
    assert "metadata:" in payload["blueprint"]["skill_md"]
    assert "schedule: \"0 10 * * 1\"" in payload["blueprint"]["skill_md"]
    assert "loopy" in payload["blueprint"]["skill_md"]
    assert "does not run it" in payload["notes"][0]


def test_loopy_tools_are_registered_and_dispatchable():
    for name in ("loopy_catalog_search", "loopy_validate_loop", "loopy_draft_loop"):
        assert registry.get_entry(name) is not None

    raw = registry.dispatch(
        "loopy_validate_loop",
        {
            "loop": (
                "Read the current state, make one bounded update, verify with tests, "
                "record a receipt, and stop when tests pass or no progress remains. "
                "Ask before publishing."
            )
        },
    )
    payload = json.loads(raw)

    assert payload["status"] == "ready"


def _catalog_fixture() -> dict:
    return {
        "updated": "2026-06-26",
        "loopCount": 2,
        "catalogUrl": "https://signals.forwardfuture.com/loop-library/catalog.json",
        "loops": [
            {
                "number": "001",
                "slug": "overnight-docs-sweep",
                "title": "The docs sweep",
                "url": "https://signals.forwardfuture.com/loop-library/loops/overnight-docs-sweep/",
                "category": {"slug": "engineering", "label": "Engineering"},
                "description": "Compare documentation with the current codebase and fix drift.",
                "useWhen": "Use whenever implementation changes may have left docs behind.",
                "prompt": "Review docs, update stale material, verify, and open a pull request.",
                "verification": {"title": "Docs match implementation.", "detail": "Finish with a pull request."},
                "keywords": ["documentation", "drift", "pull request"],
                "modified": "2026-06-18",
            },
            {
                "number": "004",
                "slug": "production-error-sweep",
                "title": "The production error sweep",
                "url": "https://signals.forwardfuture.com/loop-library/loops/production-error-sweep/",
                "category": {"slug": "engineering", "label": "Engineering"},
                "description": "Trace actionable production errors to root causes.",
                "useWhen": "Use as a scheduled reliability pass over production logs.",
                "prompt": "Review production logs, fix actionable errors, verify, and open a pull request.",
                "verification": {
                    "title": "Actionable production errors are fixed.",
                    "detail": "Finish with a pull request or stop when logs are clean.",
                },
                "keywords": ["production logs", "root cause", "error triage", "pull request"],
                "modified": "2026-06-18",
            },
        ],
    }
