from __future__ import annotations

import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

sys.path.insert(0, "/Users/ericfreeman/.hermes/hermes-agent")
from hermes_cli.signal_coo.google_auth import check_account, load_google_accounts

HOME = Path("/Users/ericfreeman/.hermes/profiles/torben")
CONFIG = HOME / "config" / "google_accounts.yaml"
CASE_PATH = HOME / "state" / "finance-cancellation-cases" / "FIN-20260629-003-manus-cancellation.md"
LEDGER = HOME / "state" / "torben-action-ledger.jsonl"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
ACCOUNT_ALIAS = "personal_freeman"
CASE_HANDLE = "FIN-20260629-003"
SENT_MESSAGE_ID = "19f15015cf403035"
SENT_AFTER = "2026-06-29T18:55:00Z"
SUPPORT_CHANNEL = "contact@manus.im"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def token_for_account() -> tuple[str, str]:
    account = load_google_accounts(CONFIG)[ACCOUNT_ALIAS]
    status = check_account(account)
    if not status.status.startswith("authenticated"):
        raise RuntimeError(f"Google account {ACCOUNT_ALIAS} not authenticated: {status.status} {status.reason or ''}")
    payload = json.loads(account.token_path.read_text(encoding="utf-8"))
    return account.email, str(payload["token"])


def gmail_get(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def headers(message: dict[str, Any]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in ((message.get("payload") or {}).get("headers") or [])}


def decode_b64(data: str | None) -> str:
    if not data:
        return ""
    data += "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")


def extract_text(part: dict[str, Any]) -> list[str]:
    out: list[str] = []
    mime = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if data and mime in {"text/plain", "text/html"}:
        text = decode_b64(data)
        if mime == "text/html":
            text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
            text = re.sub(r"</p>", "\n", text, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
        out.append(re.sub(r"\s+", " ", text).strip())
    for child in part.get("parts") or []:
        out.extend(extract_text(child))
    return out


def latest_case_messages(token: str) -> list[dict[str, Any]]:
    queries = [
        'newer_than:14d (from:manus.im OR from:stripe.com OR from:contact@manus.im OR to:contact@manus.im) (Manus OR subscription OR cancel OR cancellation)',
        'newer_than:14d subject:("Cancel Manus subscription")',
        f'rfc822msgid:{SENT_MESSAGE_ID}',
    ]
    ids: dict[str, str] = {}
    for q in queries:
        url = f"{GMAIL}/messages?" + urllib.parse.urlencode({"q": q, "maxResults": "20"})
        try:
            listed = gmail_get(url, token)
        except Exception:
            continue
        for item in listed.get("messages") or []:
            ids[str(item["id"])] = str(item.get("threadId") or "")
    messages: list[dict[str, Any]] = []
    for mid, thread_id in ids.items():
        params = urllib.parse.urlencode(
            {"format": "full", "metadataHeaders": ["From", "To", "Cc", "Subject", "Date", "Message-ID", "In-Reply-To", "References"]},
            doseq=True,
        )
        msg = gmail_get(f"{GMAIL}/messages/{mid}?{params}", token)
        h = headers(msg)
        body = "\n".join(extract_text(msg.get("payload") or {}))[:4000]
        messages.append(
            {
                "id": mid,
                "thread_id": msg.get("threadId") or thread_id,
                "internal_date": int(msg.get("internalDate") or 0),
                "from": h.get("from"),
                "to": h.get("to"),
                "subject": h.get("subject"),
                "date": h.get("date"),
                "snippet": msg.get("snippet"),
                "body_excerpt": body,
            }
        )
    return sorted(messages, key=lambda m: int(m.get("internal_date") or 0), reverse=True)


def main() -> int:
    account_email, token = token_for_account()
    messages = latest_case_messages(token)
    vendor_messages = []
    for m in messages:
        if m.get("id") == SENT_MESSAGE_ID:
            continue
        blob = ((m.get("from") or "") + "\n" + (m.get("subject") or "") + "\n" + (m.get("snippet") or "") + "\n" + (m.get("body_excerpt") or "")).lower()
        if "manus" in blob and ("manus.im" in blob or "stripe" in blob or "subscription" in blob or "cancel" in blob):
            vendor_messages.append(m)
    combined = "\n".join((m.get("subject") or "") + "\n" + (m.get("snippet") or "") + "\n" + (m.get("body_excerpt") or "") for m in vendor_messages).lower()
    confirmed = any(term in combined for term in ["cancelled", "canceled", "subscription has been cancelled", "subscription has been canceled", "will not renew", "no longer be charged"])
    blocked = any(term in combined for term in ["sign in", "log in", "cannot locate", "unable to locate", "use the app", "downgrade to free"])
    output = {
        "case_handle": CASE_HANDLE,
        "checked_at": utcnow(),
        "account_email": account_email,
        "case_path": str(CASE_PATH),
        "support_channel": SUPPORT_CHANNEL,
        "sent_message_id": SENT_MESSAGE_ID,
        "vendor_messages_found": len(vendor_messages),
        "latest_messages": messages[:5],
        "cancellation_confirmed_detected": confirmed,
        "blocked_detected": blocked,
        "suggested_action": "mark_confirmed" if confirmed else ("notify_blocked" if blocked else "wait_or_follow_up_if_past_deadline"),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("manus_cancellation_watch", main))
