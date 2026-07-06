"""Loopy memory-maintenance tools for profile-scoped Hermes memory files."""

from __future__ import annotations

import argparse
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator

from tools.registry import registry, tool_error, tool_result

SECTION_HEADER = "## Loopy Memory Entries"
DEFAULT_STATUS = "active"
VALID_TRUST = {"canonical", "project", "temporary"}
VALID_STATUS = {"active", "stale", "needs-review"}
TRUST_RANK = {"temporary": 1, "project": 2, "canonical": 3}
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b[A-Za-z0-9_]*TOKEN[A-Za-z0-9_]*\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*SECRET[A-Za-z0-9_]*\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*PASSWORD[A-Za-z0-9_]*\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*API[_-]?KEY[A-Za-z0-9_]*\s*[:=]\s*\S+", re.IGNORECASE),
)
EXTERNAL_FACT_HINTS = (
    "current ",
    "currently ",
    "latest ",
    "today",
    "yesterday",
    "tomorrow",
    "version ",
    "price ",
    "stock ",
    "cve-",
    "oauth status",
    "cron state",
    "auth state",
    "live state",
)


@dataclass(frozen=True)
class MemoryEntry:
    entry_id: str
    trust: str
    date: str
    source: str
    status: str
    note: str
    review_reason: str = ""
    merged_into: str = ""
    contradictions: int = 0

    def normalized_note(self) -> str:
        return normalize_note(self.note)


def resolve_profile_memory_path(
    memory_path: str | Path | None = None,
    *,
    hermes_home: str | Path | None = None,
) -> Path:
    """Return the only editable memory file for the active Hermes profile."""

    home = Path(hermes_home or os.getenv("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    expected = (home / "memories" / "MEMORY.md").resolve()
    if memory_path is None:
        return expected

    supplied = Path(memory_path).expanduser().resolve()
    if supplied != expected:
        raise ValueError(
            "memory_path must be the active profile memory file "
            f"({expected}); refusing to target {supplied}"
        )
    return supplied


def task_memory_review(
    *,
    entries: list[dict[str, Any]],
    source: str,
    trust: str = "project",
    memory_path: str | Path | None = None,
    hermes_home: str | Path | None = None,
    today: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Append reusable tagged memory entries after a task."""

    memory = resolve_profile_memory_path(memory_path, hermes_home=hermes_home)
    entry_date = _parse_date(today or date.today().isoformat()).isoformat()
    default_trust = _validate_trust(trust)
    source_text = _clean_scalar(source)
    if not source_text:
        return _failure("source is required")
    if not entries:
        return _failure("at least one entry is required")

    current_text = memory.read_text(encoding="utf-8") if memory.exists() else ""
    parsed = parse_memory_entries(current_text)
    next_entries = list(parsed)
    added: list[MemoryEntry] = []
    skipped: list[dict[str, Any]] = []
    updated_existing: list[dict[str, Any]] = []

    for raw in entries:
        note = _clean_note(raw.get("note") or raw.get("text") or raw.get("lesson"))
        if not note:
            skipped.append({"reason": "empty_note"})
            continue
        secret = _secret_match(note)
        if secret:
            return _failure(
                "entry appears to contain a secret or credential-shaped value",
                code="secret_policy_violation",
                detail=secret,
            )
        item_trust = _validate_trust(raw.get("trust") or default_trust)
        item_status = _validate_status(raw.get("status") or DEFAULT_STATUS)
        item_source = _clean_scalar(raw.get("source") or source_text)
        item_date = _parse_date(raw.get("date") or entry_date).isoformat()
        candidate = MemoryEntry(
            entry_id=_entry_id(item_date, item_source, note),
            trust=item_trust,
            date=item_date,
            source=item_source,
            status=item_status,
            note=note,
        )
        duplicate_indexes = [
            index for index, existing in enumerate(next_entries)
            if existing.normalized_note() == candidate.normalized_note()
        ]
        if duplicate_indexes:
            best_index = duplicate_indexes[0]
            best = next_entries[best_index]
            if _entry_precedence(best) >= _entry_precedence(candidate):
                skipped.append(
                    {
                        "reason": "duplicate_existing_entry_kept",
                        "existing_id": best.entry_id,
                        "incoming_trust": candidate.trust,
                    }
                )
                continue
            next_entries[best_index] = replace(
                best,
                status="stale",
                review_reason=_join_reasons(best.review_reason, "superseded_by_newer_or_higher_trust_entry"),
                merged_into=candidate.entry_id,
            )
            updated_existing.append({"entry_id": best.entry_id, "status": "stale", "merged_into": candidate.entry_id})
        next_entries.append(candidate)
        added.append(candidate)

    new_text = render_memory_text(current_text, next_entries) if added or updated_existing else current_text
    diff = _unified_diff(current_text, new_text, str(memory))
    if apply and new_text != current_text:
        _write_memory(memory, new_text)

    return {
        "success": True,
        "applied": bool(apply and new_text != current_text),
        "memory_path": str(memory),
        "added_count": len(added),
        "skipped_count": len(skipped),
        "updated_existing_count": len(updated_existing),
        "added": [_entry_to_dict(entry) for entry in added],
        "skipped": skipped,
        "updated_existing": updated_existing,
        "required_tags": ["trust", "date", "source", "status"],
        "proposed_diff": diff,
        "safety_boundary": "Only the active profile memories/MEMORY.md may be edited; secrets and cross-profile writes are refused.",
    }


def weekly_memory_review(
    *,
    memory_path: str | Path | None = None,
    hermes_home: str | Path | None = None,
    today: str | None = None,
    stale_after_days: int = 30,
    apply: bool = False,
) -> dict[str, Any]:
    """Back up and mark stale/needs-review Loopy memory entries."""

    memory = resolve_profile_memory_path(memory_path, hermes_home=hermes_home)
    review_date = _parse_date(today or date.today().isoformat())
    current_text = memory.read_text(encoding="utf-8") if memory.exists() else ""
    parsed = parse_memory_entries(current_text)
    reviewed, stats = review_entries(parsed, review_date=review_date, stale_after_days=stale_after_days)
    new_text = render_memory_text(current_text, reviewed) if parsed or SECTION_HEADER in current_text else current_text
    diff = _unified_diff(current_text, new_text, str(memory))
    backup_path = None
    applied = False
    if apply:
        backup_path = _backup_memory(memory, current_text)
        if new_text != current_text:
            _write_memory(memory, new_text)
            applied = True

    legacy_count = _legacy_untagged_count(current_text)
    return {
        "success": True,
        "applied": applied,
        "memory_path": str(memory),
        "backup_path": str(backup_path) if backup_path else None,
        "entry_count": len(parsed),
        "legacy_untagged_entry_count": legacy_count,
        "stats": stats,
        "proposed_diff": diff,
        "review_policy": {
            "stale_after_days": stale_after_days,
            "delete_policy": "never hard-delete; mark stale or needs-review first",
            "external_fact_policy": "entries resting on time-sensitive external facts are marked needs-review",
        },
    }


def parse_memory_entries(text: str) -> list[MemoryEntry]:
    lines = text.splitlines()
    entries: list[MemoryEntry] = []
    in_section = False
    current: dict[str, str] | None = None

    for line in lines:
        if line.strip() == SECTION_HEADER:
            in_section = True
            current = None
            continue
        if not in_section:
            continue
        if line.startswith("## ") and line.strip() != SECTION_HEADER:
            break
        if line.startswith("- id: "):
            if current:
                entry = _entry_from_block(current)
                if entry:
                    entries.append(entry)
            current = {"id": line.removeprefix("- id: ").strip()}
            continue
        if current is None or not line.startswith("  "):
            continue
        key, sep, value = line.strip().partition(":")
        if sep:
            current[key.strip()] = value.strip()

    if current:
        entry = _entry_from_block(current)
        if entry:
            entries.append(entry)
    return entries


def review_entries(
    entries: list[MemoryEntry],
    *,
    review_date: date,
    stale_after_days: int = 30,
) -> tuple[list[MemoryEntry], dict[str, int]]:
    reviewed = list(entries)
    stats = {
        "marked_needs_review": 0,
        "marked_stale": 0,
        "duplicates_seen": 0,
        "unchanged": 0,
    }

    best_by_note: dict[str, int] = {}
    for index, entry in enumerate(reviewed):
        key = entry.normalized_note()
        if key in best_by_note:
            stats["duplicates_seen"] += 1
            prior_index = best_by_note[key]
            prior = reviewed[prior_index]
            if _entry_precedence(entry) > _entry_precedence(prior):
                reviewed[prior_index] = _mark_stale(prior, f"duplicate_of:{entry.entry_id}", merged_into=entry.entry_id)
                best_by_note[key] = index
                stats["marked_stale"] += 1
            else:
                reviewed[index] = _mark_stale(entry, f"duplicate_of:{prior.entry_id}", merged_into=prior.entry_id)
                stats["marked_stale"] += 1

    for index, entry in enumerate(reviewed):
        updated = entry
        reasons: list[str] = []
        if entry.status == "active":
            age_days = (review_date - _parse_date(entry.date)).days
            if age_days > stale_after_days:
                reasons.append(f"older_than_{stale_after_days}d")
            if entry.contradictions >= 2:
                reasons.append("contradicted_twice")
            if _rests_on_external_fact(entry.note):
                reasons.append("external_fact_recheck_required")
        if reasons:
            updated = replace(
                entry,
                status="needs-review",
                review_reason=_join_reasons(entry.review_reason, *reasons),
            )
            if updated != entry:
                stats["marked_needs_review"] += 1
        elif updated == entry:
            stats["unchanged"] += 1
        reviewed[index] = updated
    return reviewed, stats


def render_memory_text(original_text: str, entries: list[MemoryEntry]) -> str:
    prefix = original_text
    suffix = ""
    if SECTION_HEADER in original_text:
        before, _, after = original_text.partition(SECTION_HEADER)
        prefix = before.rstrip() + "\n\n"
        remainder_lines = after.splitlines()
        next_header_at = None
        for idx, line in enumerate(remainder_lines):
            if idx > 0 and line.startswith("## "):
                next_header_at = idx
                break
        if next_header_at is not None:
            suffix = "\n".join(remainder_lines[next_header_at:]).strip()
    else:
        prefix = original_text.rstrip() + ("\n\n" if original_text.strip() else "")

    block = SECTION_HEADER + "\n\n" + "\n".join(_render_entry(entry) for entry in entries).rstrip() + "\n"
    if not entries:
        block = SECTION_HEADER + "\n\n"
    if suffix:
        return prefix + block + "\n" + suffix.rstrip() + "\n"
    return prefix + block


def loopy_memory_task_review_handler(args: dict[str, Any], **_kwargs: Any) -> str:
    entries = args.get("entries")
    if not isinstance(entries, list):
        return tool_error("entries must be a list of note objects")
    try:
        payload = task_memory_review(
            entries=entries,
            source=_clean_scalar(args.get("source")),
            trust=_clean_scalar(args.get("trust") or "project"),
            memory_path=args.get("memory_path"),
            hermes_home=args.get("hermes_home"),
            today=_clean_scalar(args.get("date")),
            apply=bool(args.get("apply", False)),
        )
    except ValueError as exc:
        return tool_error(str(exc))
    if not payload.get("success"):
        return tool_error(payload.get("error") or "memory task review failed")
    return tool_result(payload)


def loopy_memory_weekly_review_handler(args: dict[str, Any], **_kwargs: Any) -> str:
    try:
        payload = weekly_memory_review(
            memory_path=args.get("memory_path"),
            hermes_home=args.get("hermes_home"),
            today=_clean_scalar(args.get("date")),
            stale_after_days=int(args.get("stale_after_days") or 30),
            apply=bool(args.get("apply", False)),
        )
    except ValueError as exc:
        return tool_error(str(exc))
    if not payload.get("success"):
        return tool_error(payload.get("error") or "memory weekly review failed")
    return tool_result(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Hermes Loopy memory maintenance.")
    sub = parser.add_subparsers(dest="command", required=True)

    task = sub.add_parser("task-review", help="Append reusable tagged memory after a task.")
    task.add_argument("--entry", action="append", default=[], help="Reusable memory note. May be supplied multiple times.")
    task.add_argument("--source", required=True)
    task.add_argument("--trust", default="project", choices=sorted(VALID_TRUST))
    task.add_argument("--date")
    task.add_argument("--memory-path")
    task.add_argument("--apply", action="store_true")
    task.add_argument("--json", action="store_true")

    weekly = sub.add_parser("weekly-review", help="Back up and review tagged memory entries.")
    weekly.add_argument("--date")
    weekly.add_argument("--memory-path")
    weekly.add_argument("--stale-after-days", type=int, default=30)
    weekly.add_argument("--apply", action="store_true")
    weekly.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "task-review":
        payload = task_memory_review(
            entries=[{"note": entry} for entry in args.entry],
            source=args.source,
            trust=args.trust,
            today=args.date,
            memory_path=args.memory_path,
            apply=args.apply,
        )
    else:
        payload = weekly_memory_review(
            today=args.date,
            memory_path=args.memory_path,
            stale_after_days=args.stale_after_days,
            apply=args.apply,
        )
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload.get("proposed_diff") or json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("success") else 2


def _entry_from_block(block: dict[str, str]) -> MemoryEntry | None:
    try:
        return MemoryEntry(
            entry_id=block["id"],
            trust=_validate_trust(block.get("trust", "")),
            date=_parse_date(block.get("date", "")).isoformat(),
            source=_clean_scalar(block.get("source", "")),
            status=_validate_status(block.get("status", "")),
            note=_clean_note(block.get("note", "")),
            review_reason=_clean_scalar(block.get("review_reason", "")),
            merged_into=_clean_scalar(block.get("merged_into", "")),
            contradictions=int(block.get("contradictions", "0") or 0),
        )
    except (KeyError, ValueError):
        return None


def _render_entry(entry: MemoryEntry) -> str:
    lines = [
        f"- id: {entry.entry_id}",
        f"  trust: {entry.trust}",
        f"  date: {entry.date}",
        f"  source: {_escape_field(entry.source)}",
        f"  status: {entry.status}",
    ]
    if entry.review_reason:
        lines.append(f"  review_reason: {_escape_field(entry.review_reason)}")
    if entry.merged_into:
        lines.append(f"  merged_into: {_escape_field(entry.merged_into)}")
    if entry.contradictions:
        lines.append(f"  contradictions: {entry.contradictions}")
    lines.append(f"  note: {_escape_field(entry.note)}")
    return "\n".join(lines)


def _entry_to_dict(entry: MemoryEntry) -> dict[str, Any]:
    return {
        "id": entry.entry_id,
        "trust": entry.trust,
        "date": entry.date,
        "source": entry.source,
        "status": entry.status,
        "note": entry.note,
        "review_reason": entry.review_reason,
        "merged_into": entry.merged_into,
    }


def _entry_id(entry_date: str, source: str, note: str) -> str:
    digest = hashlib.sha256(f"{entry_date}\0{source}\0{normalize_note(note)}".encode("utf-8")).hexdigest()[:10]
    return f"mem-{entry_date.replace('-', '')}-{digest}"


def _entry_precedence(entry: MemoryEntry) -> tuple[int, str, int]:
    return (TRUST_RANK[entry.trust], entry.date, 0 if entry.status == "stale" else 1)


def _mark_stale(entry: MemoryEntry, reason: str, *, merged_into: str = "") -> MemoryEntry:
    return replace(
        entry,
        status="stale",
        review_reason=_join_reasons(entry.review_reason, reason),
        merged_into=merged_into or entry.merged_into,
    )


def _write_memory(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)


def _backup_memory(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"MEMORY-{stamp}.md"
    if path.exists():
        shutil.copy2(path, backup)
    else:
        backup.write_text(text, encoding="utf-8")
    return backup


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def normalize_note(note: str) -> str:
    return re.sub(r"\s+", " ", note.strip().lower())


def _clean_note(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_scalar(value: Any) -> str:
    return _clean_note(value).replace("|", "/")


def _escape_field(value: str) -> str:
    return _clean_scalar(value)


def _validate_trust(value: Any) -> str:
    trust = _clean_scalar(value).lower()
    if trust not in VALID_TRUST:
        raise ValueError(f"invalid trust: {value}")
    return trust


def _validate_status(value: Any) -> str:
    status = _clean_scalar(value).lower()
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status: {value}")
    return status


def _parse_date(value: Any) -> date:
    return date.fromisoformat(_clean_scalar(value)[:10])


def _secret_match(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)[:80]
    return ""


def _rests_on_external_fact(note: str) -> bool:
    lowered = note.lower()
    return any(hint in lowered for hint in EXTERNAL_FACT_HINTS)


def _join_reasons(*values: str) -> str:
    reasons: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in reasons:
                reasons.append(cleaned)
    return ",".join(reasons)


def _legacy_untagged_count(text: str) -> int:
    before = text.partition(SECTION_HEADER)[0]
    return sum(1 for chunk in before.split("§") if chunk.strip())


def _unified_diff(before: str, after: str, path: str) -> str:
    if before == after:
        return ""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )


def _failure(error: str, *, code: str = "invalid_request", detail: str = "") -> dict[str, Any]:
    return {"success": False, "error": error, "code": code, "detail": detail}


registry.register(
    name="loopy_memory_task_review",
    toolset="loopy",
    schema={
        "name": "loopy_memory_task_review",
        "description": (
            "Draft or append Vox-style tagged memory entries to the active profile memories/MEMORY.md "
            "after a task. Refuses cross-profile paths and credential-shaped content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "note": {"type": "string"},
                            "trust": {"type": "string", "enum": sorted(VALID_TRUST)},
                            "date": {"type": "string"},
                            "source": {"type": "string"},
                            "status": {"type": "string", "enum": sorted(VALID_STATUS)},
                        },
                        "required": ["note"],
                    },
                },
                "source": {"type": "string"},
                "trust": {"type": "string", "enum": sorted(VALID_TRUST)},
                "date": {"type": "string"},
                "memory_path": {"type": "string"},
                "hermes_home": {"type": "string"},
                "apply": {"type": "boolean", "description": "Default false. False returns a proposed diff only."},
            },
            "required": ["entries", "source"],
        },
    },
    handler=loopy_memory_task_review_handler,
    description="Review a completed task and update profile memory",
    emoji="loop",
    max_result_size_chars=24_000,
)

registry.register(
    name="loopy_memory_weekly_review",
    toolset="loopy",
    schema={
        "name": "loopy_memory_weekly_review",
        "description": (
            "Run the weekly Loopy memory decay pass for the active profile MEMORY.md: back up first, "
            "merge duplicates by marking losers stale, and mark old/external-fact entries needs-review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "memory_path": {"type": "string"},
                "hermes_home": {"type": "string"},
                "stale_after_days": {"type": "integer", "description": "Default 30."},
                "apply": {"type": "boolean", "description": "Default false. False returns a proposed diff only."},
            },
        },
    },
    handler=loopy_memory_weekly_review_handler,
    description="Run weekly profile memory decay review",
    emoji="loop",
    max_result_size_chars=24_000,
)


if __name__ == "__main__":
    raise SystemExit(main())
