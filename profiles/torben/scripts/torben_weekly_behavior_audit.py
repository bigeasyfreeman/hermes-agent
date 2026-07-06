#!/usr/bin/env python3
"""Build Torben's weekly cross-surface behavior audit artifact."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

AUDIT_VERSION = "weekly_behavior_audit.v1"
DEFAULT_STATE_GLOB = "torben-*-latest.json"


def _iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _load_fixture(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    return [record for record in _list(records) if isinstance(record, dict)]


def _collect_state_records(state_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(state_dir.glob(DEFAULT_STATE_GLOB)):
        if path.name == "torben-weekly-behavior-audit-latest.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records.append(
            {
                "id": path.stem,
                "surface": _surface_from_path(path),
                "source_path": str(path),
                "pattern": _compact(payload.get("task") or payload.get("status") or path.stem, path.stem),
                "recurrence_count": int(bool(payload)),
                "non_obvious": False,
                "codifiable": False,
                "validation_plan": [],
                "metadata_only": True,
            }
        )
    return records


def _surface_from_path(path: Path) -> str:
    name = path.name
    if "finance" in name:
        return "finance"
    if "gtm" in name:
        return "gtm"
    if "email" in name or "gmail" in name or "calendar" in name or "meeting" in name:
        return "ea"
    if "runbook" in name or "qa" in name:
        return "qa"
    return "unknown"


def build_weekly_behavior_audit(records: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    generated_at = _iso(now)
    source_manifest = _source_manifest(records)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for record in records:
        decision = _classify_record(record)
        if decision["accepted"]:
            candidates.append(_candidate_from_record(record, decision))
        else:
            rejected.append(_rejection_from_record(record, decision))

    proposed_skill_count = sum(1 for item in candidates if item["candidate_type"] == "skill")
    proposed_runbook_update_count = sum(1 for item in candidates if item["candidate_type"] == "runbook_update")
    payload = {
        "task": "torben_weekly_behavior_audit",
        "schema_version": AUDIT_VERSION,
        "generated_at": generated_at,
        "wakeAgent": bool(candidates),
        "source_manifest": source_manifest,
        "redaction_posture": "metadata_and_compact_patterns_only",
        "recurring_patterns_count": len(candidates),
        "rejected_patterns_count": len(rejected),
        "proposed_skill_count": proposed_skill_count,
        "proposed_runbook_update_count": proposed_runbook_update_count,
        "review_status": "draft_for_review" if candidates else "nothing_worth_extracting",
        "candidates": candidates,
        "rejected_patterns": rejected,
        "live_installs": 0,
        "external_mutations": 0,
        "public_actions_taken": 0,
        "text": "",
    }
    payload["text"] = render_weekly_behavior_audit_text(payload)
    return payload


def _source_manifest(records: list[dict[str, Any]]) -> dict[str, Any]:
    surfaces: dict[str, int] = {}
    source_paths: list[str] = []
    for record in records:
        surface = _compact(record.get("surface"), "unknown")
        surfaces[surface] = surfaces.get(surface, 0) + 1
        source_path = _compact(record.get("source_path"), "")
        if source_path:
            source_paths.append(source_path)
    return {
        "source_count": len(records),
        "surfaces": dict(sorted(surfaces.items())),
        "source_paths": source_paths[:25],
    }


def _classify_record(record: dict[str, Any]) -> dict[str, Any]:
    recurrence_count = _int(record.get("recurrence_count"))
    recurring = bool(record.get("recurring")) or recurrence_count >= 2
    non_obvious = bool(record.get("non_obvious"))
    codifiable = bool(record.get("codifiable"))
    validation_plan = [str(item) for item in _list(record.get("validation_plan")) if str(item).strip()]
    project_specific = bool(record.get("project_specific"))
    contains_raw_private_data = bool(record.get("raw_private_payload") or record.get("contains_raw_private_data"))

    reasons: list[str] = []
    if not recurring:
        reasons.append("not_recurring")
    if not non_obvious:
        reasons.append("not_non_obvious")
    if not codifiable:
        reasons.append("not_codifiable")
    if not validation_plan:
        reasons.append("missing_validation_plan")
    if contains_raw_private_data:
        reasons.append("raw_private_data_not_allowed")

    accepted = not reasons
    candidate_type = "runbook_update" if project_specific else "skill"
    return {
        "accepted": accepted,
        "reasons": reasons,
        "recurring": recurring,
        "non_obvious": non_obvious,
        "codifiable": codifiable,
        "validation_plan": validation_plan,
        "candidate_type": candidate_type,
    }


def _candidate_from_record(record: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    name = _compact(record.get("candidate_name") or record.get("pattern"), "behavior-pattern")
    return {
        "candidate_id": _candidate_id(record),
        "candidate_type": decision["candidate_type"],
        "name": name,
        "surface": _compact(record.get("surface"), "unknown"),
        "pattern": _compact(record.get("pattern"), name),
        "recurring": True,
        "non_obvious": True,
        "codifiable": True,
        "validation_plan": decision["validation_plan"],
        "review_status": "draft_for_review",
        "live_installed": False,
        "review_path": _compact(record.get("review_path"), "drafts/skill-candidates/"),
        "source_refs": [str(item) for item in _list(record.get("source_refs")) if str(item).strip()][:10],
    }


def _rejection_from_record(record: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": _compact(record.get("id"), _candidate_id(record)),
        "surface": _compact(record.get("surface"), "unknown"),
        "pattern": _compact(record.get("pattern"), "unspecified"),
        "reasons": decision["reasons"],
    }


def _candidate_id(record: dict[str, Any]) -> str:
    material = "|".join(
        [
            _compact(record.get("id"), "record"),
            _compact(record.get("surface"), "surface"),
            _compact(record.get("pattern"), "pattern"),
        ]
    )
    return "WBA-" + "".join(ch for ch in material.upper() if ch.isalnum())[:40]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def render_weekly_behavior_audit_text(payload: dict[str, Any]) -> str:
    date = str(payload.get("generated_at") or "")[:10]
    if not payload.get("candidates"):
        return (
            f"Torben / Weekly Behavior Audit / {date}\n\n"
            "Nothing worth extracting.\n"
            f"Sources checked: {payload['source_manifest']['source_count']}.\n"
            f"Rejected patterns: {payload['rejected_patterns_count']}.\n"
            "No skill was installed and no external mutation occurred.\n"
        )
    lines = [
        f"Torben / Weekly Behavior Audit / {date}",
        "",
        f"Found {len(payload['candidates'])} review-gated skill/runbook candidate(s).",
        "No skill was installed and no external mutation occurred.",
        "",
    ]
    for idx, candidate in enumerate(payload["candidates"], start=1):
        lines.extend(
            [
                f"{idx}. {candidate['name']} ({candidate['candidate_type']})",
                f"Pattern: {candidate['pattern']}",
                f"Validation: {candidate['validation_plan'][0]}",
                f"Review status: {candidate['review_status']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_weekly_behavior_audit_artifacts(
    payload: dict[str, Any],
    *,
    json_path: str | Path,
    text_path: str | Path,
) -> None:
    json_output = Path(json_path)
    text_output = Path(text_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    text_output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(json_output, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _atomic_write(text_output, str(payload.get("text") or ""))


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    fixture = str(os.getenv("TORBEN_WEEKLY_BEHAVIOR_AUDIT_FIXTURE") or "").strip() or None
    records = _load_fixture(fixture) if fixture else _collect_state_records(state_dir)
    payload = build_weekly_behavior_audit(records)
    write_weekly_behavior_audit_artifacts(
        payload,
        json_path=state_dir / "torben-weekly-behavior-audit-latest.json",
        text_path=state_dir / "torben-weekly-behavior-audit-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("torben-weekly-behavior-audit", main))
