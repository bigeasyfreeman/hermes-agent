"""Approval-gated public X replies for Torben GTM handles."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .action_ledger import HANDLE_RE, ActionLedger, ActionRecord, format_time, utc_now


DEFAULT_MAGNUS_ROOT = Path("/Users/ericfreeman/magnus")
UV_BINARY_CANDIDATES = (
    "/opt/homebrew/bin/uv",
    "/usr/local/bin/uv",
    "/Users/ericfreeman/.local/bin/uv",
)
PUBLIC_REPLY_APPROVAL_RE = re.compile(
    r"\b(approve|approved|send|post|reply publicly|publish|go ahead)\b",
    re.IGNORECASE,
)

Runner = Callable[[list[str], Path], Any]


def _resolve_uv_binary() -> str:
    """Resolve uv for stripped service environments.

    Gateway and cron launches can run with a narrow PATH, while Homebrew uv is
    installed in /opt/homebrew/bin on the live macOS host. Returning "uv" as the
    final fallback preserves the old behavior and error shape when uv is truly
    absent.
    """
    candidates = [
        os.environ.get("HERMES_UV_BINARY"),
        os.environ.get("UV_BINARY"),
        shutil.which("uv"),
        *UV_BINARY_CANDIDATES,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return "uv"


@dataclass
class GTMPublicReplyApplyResult:
    handled: bool
    status: str
    text: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "status": self.status,
            "reason": self.reason,
            "text": self.text,
            "results": self.results,
            "public_actions_taken": sum(int(item.get("public_actions_taken") or 0) for item in self.results),
            "external_mutations": sum(int(item.get("external_mutations") or 0) for item in self.results),
        }


def is_public_reply_approval(reply_text: str) -> bool:
    return bool(PUBLIC_REPLY_APPROVAL_RE.search(str(reply_text or "")))


def send_approved_gtm_public_replies(
    *,
    ledger: ActionLedger,
    reply_text: str,
    approved_by: str = "signal-reply",
    dry_run: bool = True,
    yes: bool = False,
    magnus_root: str | Path = DEFAULT_MAGNUS_ROOT,
    now: datetime | None = None,
    runner: Runner | None = None,
) -> GTMPublicReplyApplyResult:
    """Send public X replies for explicitly approved GTM social-reply handles.

    The guard is intentionally narrow: only GTM `social_reply_draft` records
    with exact stored copy and target URL are eligible. A fresh explicit
    approval message may promote a staged draft into the live send attempt.
    """

    reply_text = str(reply_text or "").strip()
    if not reply_text or not is_public_reply_approval(reply_text):
        return GTMPublicReplyApplyResult(handled=False, status="not_approval")

    handles = _unique_handles(reply_text)
    if not handles:
        return GTMPublicReplyApplyResult(handled=False, status="no_handles")

    now_dt = (now or utc_now()).astimezone(timezone.utc)
    records_by_handle = {record.handle: record for record in ledger.load()}
    results = []
    handled = False
    for handle in handles:
        record = records_by_handle.get(handle)
        if record is None:
            results.append(_blocked_result(handle, "not_found", "No GTM action with that handle exists."))
            continue
        if not _is_gtm_social_reply_draft(record):
            results.append(_blocked_result(handle, "not_public_reply_draft", "Handle is not a GTM social reply draft."))
            continue
        handled = True
        results.append(
            _send_one_public_reply(
                ledger=ledger,
                handle=handle,
                approved_by=approved_by,
                dry_run=dry_run,
                yes=yes,
                magnus_root=Path(magnus_root),
                now=now_dt,
                runner=runner,
            )
        )

    if not handled:
        return GTMPublicReplyApplyResult(
            handled=False,
            status="no_public_reply_targets",
            results=results,
            reason="No referenced handles were eligible GTM public reply drafts.",
            text=_render_public_reply_result(results, dry_run=dry_run),
        )

    sent_count = sum(1 for item in results if item.get("status") == "sent")
    dry_run_count = sum(1 for item in results if item.get("status") == "dry_run")
    failed_count = sum(1 for item in results if item.get("status") in {"failed", "blocked"})
    if sent_count and not failed_count:
        status = "sent"
    elif sent_count:
        status = "partial"
    elif dry_run_count and not failed_count:
        status = "dry_run"
    else:
        status = "blocked"
    return GTMPublicReplyApplyResult(
        handled=True,
        status=status,
        results=results,
        text=_render_public_reply_result(results, dry_run=dry_run),
    )


def _send_one_public_reply(
    *,
    ledger: ActionLedger,
    handle: str,
    approved_by: str,
    dry_run: bool,
    yes: bool,
    magnus_root: Path,
    now: datetime,
    runner: Runner | None,
) -> dict[str, Any]:
    record = ledger.get(handle)
    if record is None:
        return _blocked_result(handle, "not_found", "No GTM action with that handle exists.")
    state = dict(record.executor_state or {})
    post_url = str(state.get("post_url") or state.get("source_url") or "").strip()
    draft_reply = str(state.get("draft_reply") or state.get("draft_reply_text") or "").strip()
    if not post_url or not draft_reply:
        return _blocked_result(handle, "missing_target_or_copy", "GTM reply draft is missing post_url or draft_reply.")
    if len(draft_reply) > 4000:
        return _blocked_result(handle, "copy_too_long", "Refusing to post an X reply over 4000 characters.")
    if record.status not in {"staged", "approval_required", "approved", "approval_blocked", "executing"}:
        return _blocked_result(handle, "closed", f"Handle is not open for public reply: {record.status}.")

    tweet_id = extract_tweet_id(post_url)
    approval_path = ""
    nonce_store = ledger.path.parent / "gtm-public-replies" / "used-nonces.json"
    command = [
        _resolve_uv_binary(),
        "run",
        "python",
        "scripts/x_post_reply.py",
        tweet_id,
        draft_reply,
        "--token-path",
        str(magnus_root / "config" / ".x-oauth2-tokens.json"),
        "--approval-nonce-store",
        str(nonce_store),
        "--allow-long",
        "--attempt-unsummoned",
    ]
    if yes and not dry_run:
        approval_path = str(
            _write_approval_artifact(
                ledger=ledger,
                handle=handle,
                tweet_id=tweet_id,
                exact_copy=draft_reply,
                approved_by=approved_by,
                now=now,
            )
        )
        command.extend(["--approval-artifact", approval_path, "--yes"])

    try:
        completed = (
            runner(command, magnus_root)
            if runner
            else subprocess.run(
                command,
                cwd=magnus_root,
                text=True,
                capture_output=True,
                timeout=120,
            )
        )
    except Exception as exc:
        result = {
            "handle": handle,
            "target_tweet_id": tweet_id,
            "target_url": post_url,
            "draft_reply": draft_reply,
            "dry_run": dry_run,
            "status": "failed",
            "returncode": 1,
            "stdout_payload": {"success": False, "error": str(exc)},
            "stderr": str(exc),
            "approval_artifact_path": approval_path,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "error": str(exc),
        }
        if yes and not dry_run:
            _mark_public_reply_failed(
                ledger=ledger,
                handle=handle,
                result=result,
                approved_by=approved_by,
                now=now,
            )
        return result
    stdout = str(getattr(completed, "stdout", "") or "")
    stderr = str(getattr(completed, "stderr", "") or "")
    returncode = int(getattr(completed, "returncode", 1) or 0)
    payload = _parse_json(stdout)
    public_actions_taken = int(payload.get("public_actions_taken") or 0)
    sent = returncode == 0 and public_actions_taken == 1 and bool(payload.get("posted_tweet_id"))
    blocked_reason = str(payload.get("blocked_before_post") or payload.get("error") or stderr or "post_failed").strip()

    result = {
        "handle": handle,
        "target_tweet_id": tweet_id,
        "target_url": post_url,
        "draft_reply": draft_reply,
        "dry_run": dry_run,
        "returncode": returncode,
        "stdout_payload": payload,
        "stderr": stderr,
        "approval_artifact_path": approval_path,
        "public_actions_taken": public_actions_taken if sent else 0,
        "external_mutations": public_actions_taken if sent else 0,
    }
    if dry_run or not yes:
        result.update({"status": "dry_run", "posted_tweet_id": "", "posted_url": ""})
        return result
    if sent:
        result.update(
            {
                "status": "sent",
                "posted_tweet_id": str(payload.get("posted_tweet_id") or ""),
                "posted_url": str(payload.get("posted_url") or ""),
            }
        )
        _mark_public_reply_sent(
            ledger=ledger,
            handle=handle,
            result=result,
            approved_by=approved_by,
            now=now,
        )
        return result

    result.update({"status": "failed", "error": blocked_reason})
    _mark_public_reply_failed(
        ledger=ledger,
        handle=handle,
        result=result,
        approved_by=approved_by,
        now=now,
    )
    return result


def extract_tweet_id(id_or_url: str) -> str:
    value = str(id_or_url or "").strip()
    if re.fullmatch(r"\d{1,30}", value):
        return value
    match = re.search(r"/status(?:es)?/(\d{1,30})", value)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract X post ID from: {id_or_url}")


def _unique_handles(reply_text: str) -> list[str]:
    handles = []
    seen = set()
    for match in HANDLE_RE.finditer(str(reply_text or "").upper()):
        handle = match.group("handle")
        if handle not in seen:
            handles.append(handle)
            seen.add(handle)
    return handles


def _is_gtm_social_reply_draft(record: ActionRecord) -> bool:
    state = record.executor_state or {}
    return (
        record.scope == "gtm"
        and state.get("mutation_type") == "social_reply_draft"
        and state.get("source") == "torben_gtm_engagement_radar"
    )


def _write_approval_artifact(
    *,
    ledger: ActionLedger,
    handle: str,
    tweet_id: str,
    exact_copy: str,
    approved_by: str,
    now: datetime,
) -> Path:
    request = {
        "platform": "x",
        "action": "reply",
        "target": tweet_id,
        "exact_copy": exact_copy,
    }
    body = "\0".join([request["platform"], request["action"], request["target"], request["exact_copy"]])
    artifact = {
        **request,
        "approved_by": approved_by,
        "approved_at": format_time(now),
        "expires_at": format_time(now + timedelta(hours=6)),
        "nonce": uuid4().hex,
        "action_hash": sha256(body.encode("utf-8")).hexdigest(),
        "torben_handle": handle,
        "guard": "torben_gtm_approved_handle_v1",
    }
    approvals_dir = ledger.path.parent / "gtm-public-replies" / "approvals"
    approvals_dir.mkdir(parents=True, exist_ok=True)
    path = approvals_dir / f"{handle.lower()}-{now:%Y%m%dT%H%M%SZ}-approval.json"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def _mark_public_reply_sent(
    *,
    ledger: ActionLedger,
    handle: str,
    result: dict[str, Any],
    approved_by: str,
    now: datetime,
) -> None:
    records = ledger.load()
    for record in records:
        if record.handle != handle:
            continue
        record.status = "executed"
        record.allowed_next_actions = ["delete_public_reply"]
        record.executor_state.update(
            {
                "mutation_status": "public_reply_sent",
                "public_action_status": "sent",
                "approved_by": approved_by,
                "approved_at": format_time(now),
                "published_at": format_time(now),
                "posted_tweet_id": result.get("posted_tweet_id"),
                "posted_url": result.get("posted_url"),
                "last_public_reply_result": result,
                "public_actions_taken": 1,
                "external_mutations": 1,
                "publishing_blocked_until": None,
                "irreversibility_note": "Public X reply sent. Delete is a separate best-effort public mutation and may not remove cached impressions.",
                "x_write_guard": "torben_gtm_approved_handle_v1",
            }
        )
        record.resolution_history.append(
            {
                "at": format_time(now),
                "status": "public_reply_sent",
                "reason": f"Approved GTM public reply sent by {approved_by}.",
                "posted_tweet_id": result.get("posted_tweet_id"),
                "posted_url": result.get("posted_url"),
            }
        )
    ledger.save(records)


def _mark_public_reply_failed(
    *,
    ledger: ActionLedger,
    handle: str,
    result: dict[str, Any],
    approved_by: str,
    now: datetime,
) -> None:
    records = ledger.load()
    for record in records:
        if record.handle != handle:
            continue
        record.status = "approval_blocked"
        record.executor_state.update(
            {
                "mutation_status": "approved_but_not_sent",
                "public_action_status": "failed",
                "approved_by": approved_by,
                "approved_at": format_time(now),
                "last_public_reply_result": result,
                "last_public_reply_error": result.get("error"),
                "public_actions_taken": 0,
                "external_mutations": 0,
                "x_write_guard": "torben_gtm_approved_handle_v1",
            }
        )
        record.resolution_history.append(
            {
                "at": format_time(now),
                "status": "approval_blocked",
                "reason": f"Approved GTM public reply was not sent: {result.get('error') or 'post failed'}",
            }
        )
    ledger.save(records)


def _blocked_result(handle: str, code: str, reason: str) -> dict[str, Any]:
    return {
        "handle": handle,
        "status": "blocked",
        "error_code": code,
        "error": reason,
        "public_actions_taken": 0,
        "external_mutations": 0,
    }


def _parse_json(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": stdout.strip() or "empty stdout"}
    return payload if isinstance(payload, dict) else {"success": False, "error": "non-object stdout"}


def _render_public_reply_result(results: list[dict[str, Any]], *, dry_run: bool) -> str:
    title = "Torben / GTM Public Reply Dry Run" if dry_run else "Torben / GTM Public Reply"
    lines = [title, ""]
    for item in results:
        handle = item.get("handle") or "unknown"
        status = item.get("status")
        if status == "sent":
            lines.append(f"- [{handle}] Sent public X reply: {item.get('posted_url')}")
        elif status == "dry_run":
            lines.append(f"- [{handle}] Dry run passed for target {item.get('target_tweet_id')}. Nothing was posted.")
        else:
            lines.append(f"- [{handle}] Blocked: {item.get('error') or item.get('error_code') or 'not sent'}")
    lines.append("")
    public_actions = sum(int(item.get("public_actions_taken") or 0) for item in results)
    if public_actions:
        lines.append(f"Public replies sent: {public_actions}.")
    else:
        lines.append("Nothing was posted, scheduled, or sent.")
    return "\n".join(lines).rstrip() + "\n"
