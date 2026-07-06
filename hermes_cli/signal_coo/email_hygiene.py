"""Approval-gated Gmail hygiene recommendations for Torben."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .action_ledger import ActionLedger, ActionRecord, parse_time
from .automation_policy import ea_automation_decisions, load_torben_automation_policy
from .google_auth import account_for_alias
from .google_evidence import GMAIL_API_ROOT, _read_token


HYGIENE_POLICY_VERSION = 3
HYGIENE_OPEN_STATUSES = {"staged", "approval_required", "approved", "executing"}
ACTION_PREFIX = "email_hygiene"
DEFAULT_LLM_PROVIDER = "openai-codex"
DEFAULT_LLM_MODEL = "gpt-5.5"
DEFAULT_LLM_TIMEOUT_SECONDS = 30
DEFAULT_FILTER_RECOMMENDATION_MIN_MESSAGES = 3
SAFE_HYGIENE_LABEL_NAMES = {
    "Account Security",
    "AI Security Newsletters",
    "Developer Notifications",
    "Inbox Zero Review",
    "Low Signal Newsletters",
    "Receipts",
}

MFA_TERMS = (
    "one time passcode",
    "one-time passcode",
    "verification code",
    "security code",
    "login code",
    "authentication code",
    "password reset",
)
NOISE_TERMS = (
    "privacy policy",
    "terms of service",
    "terms update",
    "policy update",
    "rebranding",
    "reward",
    "rewards",
    "lendingclub",
    "lending club",
    "mens wearhouse",
    "men's wearhouse",
    "unsubscribe",
)
RESOLVED_INFO_TERMS = (
    "confirmed",
    "confirmation",
    "completed",
    "complete",
    "resolved",
    "closed",
    "delivered",
    "shipped",
    "processed",
    "receipt",
    "statement available",
    "payment received",
    "invoice paid",
    "your report is ready",
    "survey has closed",
)
CONTENT_KEEP_TERMS = (
    "action required",
    "please sign",
    "signature required",
    "requires your signature",
    "please review",
    "respond by",
    "due by",
    "overdue",
    "final notice",
    "urgent",
    "are you available",
    "can you",
    "could you",
)
ACTIONABLE_CATEGORIES = {
    "calendar_scheduling",
    "deadline_or_action",
    "founder_funding_customer",
    "human_review_reply_candidate",
}
ARCHIVABLE_CATEGORIES = {
    "developer_notification_noise",
    "newsletter_ai_research",
    "newsletter_general",
    "newsletter_security",
    "promotions_noise",
    "receipt_vendor_ops",
    "account_security",
}
LOW_SIGNAL_TRASH_CATEGORIES = {
    "account_security",
    "developer_notification_noise",
    "newsletter_ai_research",
    "newsletter_general",
    "newsletter_security",
    "promotions_noise",
}


@dataclass
class HygieneGroup:
    key: str
    title: str
    operation: str
    risk_class: str
    rationale: str
    apply_labels: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    llm_review: dict[str, Any] = field(default_factory=dict)

    def to_action_summary(self) -> str:
        return f"{self.title} ({len(self.items)} item{'s' if len(self.items) != 1 else ''})"

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "title": self.title,
            "operation": self.operation,
            "risk_class": self.risk_class,
            "rationale": self.rationale,
            "items": self.items,
        }
        if self.apply_labels:
            payload["apply_labels"] = self.apply_labels
        if self.llm_review:
            payload["llm_review"] = self.llm_review
        return payload


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _internal_date(record: dict[str, Any]) -> datetime | None:
    raw = str(record.get("internal_date_ms") or "").strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
    return parse_time(str(record.get("date") or ""))


def _age_hours(record: dict[str, Any], now: datetime) -> float:
    internal = _internal_date(record)
    if not internal:
        return 0.0
    return max(0.0, (now - internal).total_seconds() / 3600)


def _text(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "")
        for key in ("sender", "sender_email", "sender_domain", "subject", "snippet", "body_excerpt")
    ).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _labels(record: dict[str, Any]) -> list[str]:
    labels = record.get("labels")
    if not isinstance(labels, list):
        return []
    return [str(label or "").strip() for label in labels if str(label or "").strip()]


def _compact_item(
    record: dict[str, Any],
    *,
    reason: str,
    cleanup_status: str,
    retention_policy: str,
    stale_after_hours: int,
    content_signals: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "account_alias": record.get("account_alias"),
        "message_id": record.get("message_id"),
        "thread_id": record.get("thread_id"),
        "sender": record.get("sender"),
        "subject": record.get("subject"),
        "category": record.get("category"),
        "juno_bucket": record.get("juno_bucket"),
        "reason": reason,
        "cleanup_status": cleanup_status,
        "retention_policy": retention_policy,
        "stale_after_hours": stale_after_hours,
        "age_hours": round(float(record.get("age_hours") or 0), 1),
        "labels": _labels(record),
        "snippet": record.get("snippet"),
        "evidence_ids": list(record.get("evidence_ids") or []),
    }
    if content_signals:
        payload["content_signals"] = content_signals[:8]
    return payload


def _content_signals(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text][:8]


def _has_inbox_label(record: dict[str, Any]) -> bool:
    labels = {label.upper() for label in _labels(record)}
    return not labels or "INBOX" in labels


def _is_info_lane(record: dict[str, Any]) -> bool:
    return str(record.get("juno_bucket") or "info") in {"", "info"}


def _should_hold_actionable(record: dict[str, Any], text: str) -> bool:
    category = str(record.get("category") or "")
    juno_bucket = str(record.get("juno_bucket") or "")
    if category in ACTIONABLE_CATEGORIES and juno_bucket in {"reply", "deadline", "flag"}:
        return True
    return _contains_any(text, CONTENT_KEEP_TERMS)


def _filter_source_key(record: dict[str, Any]) -> str:
    return str(record.get("list_id") or record.get("sender_email") or record.get("sender_domain") or "unknown")


def _filter_criteria(record: dict[str, Any]) -> dict[str, str]:
    list_id = str(record.get("list_id") or "").strip()
    sender_email = str(record.get("sender_email") or "").strip().lower()
    sender_domain = str(record.get("sender_domain") or "").strip().lower()
    if list_id:
        return {"list_id": list_id}
    if sender_email:
        return {"from": sender_email}
    if sender_domain:
        return {"from_domain": sender_domain}
    return {"source": str(record.get("sender") or "unknown")}


def _sample_subjects(items: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    subjects: list[str] = []
    for item in sorted(items, key=lambda record: str(record.get("internal_date_ms") or ""), reverse=True):
        subject = str(item.get("subject") or "(no subject)")
        if subject not in subjects:
            subjects.append(subject)
        if len(subjects) >= limit:
            break
    return subjects


def build_inbox_filter_recommendations(
    records: list[dict[str, Any]],
    *,
    min_messages: int = DEFAULT_FILTER_RECOMMENDATION_MIN_MESSAGES,
) -> list[dict[str, Any]]:
    """Return read-only Gmail filter recommendations for repeated inbox clutter."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not _has_inbox_label(record):
            continue
        grouped[_filter_source_key(record)].append(record)

    recommendations: list[dict[str, Any]] = []
    for source, items in grouped.items():
        if len(items) < min_messages:
            continue
        category_counts: Counter[str] = Counter(str(item.get("category") or "") for item in items)
        actionable_count = sum(category_counts.get(category, 0) for category in ACTIONABLE_CATEGORIES)
        if actionable_count:
            continue
        first = items[0]
        total = len(items)
        low_signal_count = sum(
            category_counts.get(category, 0)
            for category in {
                "developer_notification_noise",
                "newsletter_general",
                "promotions_noise",
                "receipt_vendor_ops",
            }
        )
        newsletter_signal_count = category_counts.get("newsletter_security", 0) + category_counts.get("newsletter_ai_research", 0)
        account_security_count = category_counts.get("account_security", 0)

        recommendation: dict[str, Any] | None = None
        if category_counts.get("developer_notification_noise", 0) / total >= 0.6:
            recommendation = {
                "recommendation": "create_filter_archive_and_label",
                "suggested_actions": ["skip_inbox", "apply_label:Developer Notifications"],
                "risk_class": "low",
                "confidence": "high",
                "reason": "Repeated developer/CI notifications are clutter after their operational window.",
            }
        elif (category_counts.get("promotions_noise", 0) + category_counts.get("newsletter_general", 0)) / total >= 0.6:
            recommendation = {
                "recommendation": "create_filter_archive_and_label",
                "suggested_actions": ["skip_inbox", "apply_label:Low Signal Newsletters"],
                "risk_class": "low",
                "confidence": "medium",
                "reason": "Repeated promotional/general newsletter mail is not decision-bearing.",
            }
        elif category_counts.get("receipt_vendor_ops", 0) / total >= 0.6:
            recommendation = {
                "recommendation": "create_filter_archive_and_label",
                "suggested_actions": ["skip_inbox", "apply_label:Receipts"],
                "risk_class": "medium",
                "confidence": "medium",
                "reason": "Repeated receipt/vendor confirmations should stay searchable without occupying the inbox.",
            }
        elif newsletter_signal_count / total >= 0.6:
            recommendation = {
                "recommendation": "create_filter_label_for_briefing",
                "suggested_actions": ["apply_label:AI Security Newsletters"],
                "risk_class": "medium",
                "confidence": "medium",
                "reason": "Repeated AI/security newsletter source should be labeled for briefing before any skip-inbox rule.",
            }
        elif account_security_count / total >= 0.6:
            recommendation = {
                "recommendation": "create_filter_label_only",
                "suggested_actions": ["apply_label:Account Security"],
                "risk_class": "medium",
                "confidence": "medium",
                "reason": "Repeated account-security notices should be grouped but not auto-archived by filter.",
            }
        elif low_signal_count / total >= 0.8:
            recommendation = {
                "recommendation": "review_source_for_archive_filter",
                "suggested_actions": ["consider_skip_inbox", "apply_label:Inbox Zero Review"],
                "risk_class": "medium",
                "confidence": "low",
                "reason": "Source is mostly low-signal, but category mix needs manual review before a filter.",
            }

        if recommendation is None:
            continue
        recommendations.append(
            {
                "source": source,
                "sample_sender": first.get("sender"),
                "criteria": _filter_criteria(first),
                "message_count": total,
                "category_counts": dict(category_counts),
                "sample_subjects": _sample_subjects(items),
                **recommendation,
                "mutation_boundary": "recommendation only; no Gmail filter created",
            }
        )

    return sorted(
        recommendations,
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(str(item.get("confidence")), 3),
            {"low": 0, "medium": 1, "high": 2}.get(str(item.get("risk_class")), 3),
            -int(item.get("message_count") or 0),
            str(item.get("source") or ""),
        ),
    )


def _group_candidate_records(records: list[dict[str, Any]], *, now: datetime) -> list[HygieneGroup]:
    groups = {
        "trash_mfa_codes": HygieneGroup(
            key="trash_mfa_codes",
            title="Trash stale MFA/password-code emails",
            operation="trash",
            risk_class="low",
            rationale="Security-code emails are disposable after the login window has passed.",
            apply_labels=["Account Security"],
        ),
        "archive_policy_rewards_noise": HygieneGroup(
            key="archive_policy_rewards_noise",
            title="Trash policy/rebrand/rewards noise",
            operation="trash",
            risk_class="low",
            rationale="Policy updates, rewards mail, and rebrand notices are disposable once classified as low-signal.",
            apply_labels=["Low Signal Newsletters"],
        ),
        "archive_stale_receipts": HygieneGroup(
            key="archive_stale_receipts",
            title="Archive stale receipts and vendor confirmations",
            operation="archive_and_label",
            risk_class="low",
            rationale="Old receipts and confirmations should be searchable, not inbox-visible.",
            apply_labels=["Receipts"],
        ),
        "archive_stale_low_signal_info": HygieneGroup(
            key="archive_stale_low_signal_info",
            title="Trash stale low-signal info mail",
            operation="trash",
            risk_class="low",
            rationale="Old low-signal info/newsletter/promotional mail is disposable after the review window.",
            apply_labels=["Low Signal Newsletters"],
        ),
        "archive_stale_newsletter_signal": HygieneGroup(
            key="archive_stale_newsletter_signal",
            title="Trash stale newsletter and read-later signal",
            operation="trash",
            risk_class="low",
            rationale="Newsletter signal should be labeled for audit, then trashed once stale.",
            apply_labels=["AI Security Newsletters"],
        ),
        "archive_stale_developer_notifications": HygieneGroup(
            key="archive_stale_developer_notifications",
            title="Trash stale developer notifications",
            operation="trash",
            risk_class="low",
            rationale="Old CI, PR, and platform notifications are disposable after the operational window passes.",
            apply_labels=["Developer Notifications"],
        ),
        "archive_stale_account_security_notices": HygieneGroup(
            key="archive_stale_account_security_notices",
            title="Trash stale account-security notices",
            operation="trash",
            risk_class="medium",
            rationale="Non-code account-security notices can leave Gmail after a review window unless action-shaped.",
            apply_labels=["Account Security"],
        ),
        "archive_resolved_vendor_admin": HygieneGroup(
            key="archive_resolved_vendor_admin",
            title="Trash resolved non-receipt admin confirmations",
            operation="trash",
            risk_class="low",
            rationale="Completed, delivered, confirmed, or closed non-receipt messages are disposable once stale.",
            apply_labels=["Low Signal Newsletters"],
        ),
        "trash_existing_spam": HygieneGroup(
            key="trash_existing_spam",
            title="Trash messages already marked spam",
            operation="trash",
            risk_class="low",
            rationale="Gmail already classed these as spam; Torben still stages the action for approval first.",
        ),
        "nudge_stale_replies": HygieneGroup(
            key="nudge_stale_replies",
            title="Re-bump stale threads that may still matter",
            operation="nudge_only",
            risk_class="medium",
            rationale="Older unreplied action-shaped threads should be reviewed instead of silently decaying.",
        ),
    }

    for record in records:
        category = str(record.get("category") or "")
        juno_bucket = str(record.get("juno_bucket") or "")
        text = _text(record)
        age_hours = _age_hours(record, now)
        enriched = {**record, "age_hours": age_hours}
        label_set = {label.upper() for label in _labels(record)}
        if not _has_inbox_label(record):
            continue
        if "SPAM" in label_set and age_hours >= 24:
            groups["trash_existing_spam"].items.append(
                _compact_item(
                    enriched,
                    reason="already marked spam and older than one day",
                    cleanup_status="trash_disposable_spam",
                    retention_policy="trash after one day when Gmail already marked spam",
                    stale_after_hours=24,
                    content_signals=["SPAM label"],
                )
            )
            continue
        if category == "account_security" and age_hours >= 1 and _contains_any(text, MFA_TERMS):
            groups["trash_mfa_codes"].items.append(
                _compact_item(
                    enriched,
                    reason="account-security code older than one hour",
                    cleanup_status="trash_disposable_security_code",
                    retention_policy="trash MFA/password codes after one hour",
                    stale_after_hours=1,
                    content_signals=_content_signals(text, MFA_TERMS),
                )
            )
            continue
        if _should_hold_actionable(record, text):
            if category in ACTIONABLE_CATEGORIES and juno_bucket in {"reply", "deadline", "flag"} and age_hours >= 7 * 24:
                groups["nudge_stale_replies"].items.append(
                    _compact_item(
                        enriched,
                        reason="action-shaped thread older than one week",
                        cleanup_status="stale_action_needs_nudge",
                        retention_policy="keep in inbox and rebump until Eric resolves or dismisses",
                        stale_after_hours=7 * 24,
                        content_signals=_content_signals(text, CONTENT_KEEP_TERMS),
                    )
                )
            continue
        if age_hours >= 24 and _contains_any(text, NOISE_TERMS) and category in LOW_SIGNAL_TRASH_CATEGORIES:
            groups["archive_policy_rewards_noise"].items.append(
                _compact_item(
                    enriched,
                    reason="policy/rebrand/rewards-style inbox noise older than one day",
                    cleanup_status="trash_stale_noise",
                    retention_policy="label then trash low-signal policy/rebrand/rewards mail after one day",
                    stale_after_hours=24,
                    content_signals=_content_signals(text, NOISE_TERMS),
                )
            )
            continue
        if category == "developer_notification_noise" and age_hours >= 72 and _is_info_lane(record):
            groups["archive_stale_developer_notifications"].items.append(
                _compact_item(
                    enriched,
                    reason="developer notification older than three days and not action-routed",
                    cleanup_status="trash_stale_operational_notification",
                    retention_policy="label then trash CI/PR/platform notifications after three days unless still action-routed",
                    stale_after_hours=72,
                )
            )
            continue
        if category in {"newsletter_security", "newsletter_ai_research"} and age_hours >= 7 * 24 and _is_info_lane(record):
            groups["archive_stale_newsletter_signal"].items.append(
                _compact_item(
                    enriched,
                    reason="security/AI newsletter signal older than seven days",
                    cleanup_status="trash_stale_newsletter_signal",
                    retention_policy="label then trash security/AI newsletter signal after seven days once it has had a chance to surface",
                    stale_after_hours=7 * 24,
                )
            )
            continue
        if category == "receipt_vendor_ops" and (
            age_hours >= 14 * 24
            or (
                age_hours >= 7 * 24
                and _is_info_lane(record)
                and _contains_any(text, RESOLVED_INFO_TERMS)
            )
        ):
            groups["archive_stale_receipts"].items.append(
                _compact_item(
                    enriched,
                    reason="receipt/vendor confirmation ready for receipt archive",
                    cleanup_status="archive_stale_receipt",
                    retention_policy="archive receipts/vendor confirmations after resolution or two weeks",
                    stale_after_hours=7 * 24 if _contains_any(text, RESOLVED_INFO_TERMS) else 14 * 24,
                    content_signals=_content_signals(text, RESOLVED_INFO_TERMS),
                )
            )
            continue
        if (
            category in {"newsletter_general", "promotions_noise", "account_security"}
            and age_hours >= 7 * 24
            and _is_info_lane(record)
            and _contains_any(text, RESOLVED_INFO_TERMS)
        ):
            groups["archive_resolved_vendor_admin"].items.append(
                _compact_item(
                    enriched,
                    reason="resolved/confirmed non-receipt info older than seven days",
                    cleanup_status="trash_resolved_info",
                    retention_policy="label then trash completed/confirmed/closed non-receipt info after seven days",
                    stale_after_hours=7 * 24,
                    content_signals=_content_signals(text, RESOLVED_INFO_TERMS),
                )
            )
            continue
        if category == "account_security" and age_hours >= 7 * 24 and _is_info_lane(record):
            groups["archive_stale_account_security_notices"].items.append(
                _compact_item(
                    enriched,
                    reason="non-code account-security notice older than seven days",
                    cleanup_status="trash_reviewed_security_notice",
                    retention_policy="label then trash non-code account-security notices after seven days unless still action-shaped",
                    stale_after_hours=7 * 24,
                )
            )
            continue
        if category in ARCHIVABLE_CATEGORIES and age_hours >= 30 * 24 and juno_bucket == "info":
            groups["archive_stale_low_signal_info"].items.append(
                _compact_item(
                    enriched,
                    reason="low-signal info mail older than thirty days",
                    cleanup_status="trash_low_signal_long_tail",
                    retention_policy="label then trash low-signal info after thirty days",
                    stale_after_hours=30 * 24,
                )
            )

    for group in groups.values():
        group.items = group.items[:50]
    return [group for group in groups.values() if group.items]


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = str(payload.get("output_text") or "").strip()
    if output_text:
        return output_text
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = str(content.get("text") or "").strip()
                if text:
                    parts.append(text)
    return "\n\n".join(parts).strip()


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _llm_review_request(groups: list[HygieneGroup]) -> dict[str, Any]:
    compact_groups = []
    for group in groups:
        compact_groups.append(
            {
                        "key": group.key,
                        "operation": group.operation,
                        "rationale": group.rationale,
                        "risk_class": group.risk_class,
                        "apply_labels": group.apply_labels,
                        "items": [
                    {
                        "message_id": item.get("message_id"),
                        "thread_id": item.get("thread_id"),
                        "account_alias": item.get("account_alias"),
                        "sender": item.get("sender"),
                        "subject": item.get("subject"),
                        "category": item.get("category"),
                        "juno_bucket": item.get("juno_bucket"),
                        "reason": item.get("reason"),
                        "cleanup_status": item.get("cleanup_status"),
                        "retention_policy": item.get("retention_policy"),
                        "stale_after_hours": item.get("stale_after_hours"),
                        "age_hours": item.get("age_hours"),
                        "labels": item.get("labels"),
                        "content_signals": item.get("content_signals"),
                        "snippet": item.get("snippet"),
                    }
                    for item in group.items[:12]
                ],
            }
        )
    return {"candidate_groups": compact_groups}


def _hygiene_review_prompt(groups: list[HygieneGroup]) -> str:
    return (
        "Review these Gmail cleanup candidates for Eric's Torben COO agent.\n"
        "This is an inbox-zero hygiene review, not an apply step. You may keep or drop cleanup candidates. "
        "Decision keep means keep the cleanup recommendation for Eric to approve; decision drop means leave the email alone for now. "
        "Do not invent messages. Treat sender identity, category, labels, reason, and snippet as evidence.\n\n"
        "Goal:\n"
        "- Move Eric toward inbox zero over time.\n"
        "- Keep things in the inbox while they are still relevant, actionable, relationship-sensitive, or decision-bearing.\n"
        "- Archive searchable info once stale; trash only disposable classes.\n\n"
        "Hard rules:\n"
        "- Keep important relationship, funding, customer, legal, admin, family, school, health, finance, or scheduling mail out of archive/trash.\n"
        "- If a stale thread may still matter, prefer the nudge_only group instead of archive/trash.\n"
        "- Trash means Gmail Trash, never permanent delete.\n"
        "- Trash existing spam only when labels include SPAM and the item already looks non-actionable.\n"
        "- Trash MFA/password-code mail only when it is a stale account-security code.\n"
        "- Archive only stale low-signal info, newsletters/read-later items, developer notifications, receipts/vendor ops, resolved confirmations, policy/rewards/rebrand noise, or reviewed account-security notices.\n"
        "- Cleanup status, stale_after_hours, retention_policy, labels, and content_signals are deterministic evidence; use them but override if the sender/snippet suggests risk.\n"
        "- If unsure, drop the cleanup candidate and leave it for review.\n\n"
        "Return one JSON object with this schema only:\n"
        "{\n"
        '  "recommendations": [\n'
        '    {"key": "group key", "decision": "keep|drop", "reason": "short reason", "items": [\n'
        '      {"message_id": "id", "decision": "keep|drop", "reason": "short reason"}\n'
        "    ]}\n"
        "  ],\n"
        '  "global_notes": ["short note"]\n'
        "}\n\n"
        f"Candidates:\n{json.dumps(_llm_review_request(groups), ensure_ascii=False, sort_keys=True)}"
    )


def _call_hygiene_llm(groups: list[HygieneGroup]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the conservative hygiene review through an LLM.

    Prefers the shared auxiliary client (agent.auxiliary_client), which speaks
    every configured provider transport correctly - including the ChatGPT Codex
    OAuth backend, which REQUIRES streaming plus Cloudflare headers and therefore
    returns HTTP 400 ("Stream must be set to true") for a plain non-streaming
    requests.post to /responses.

    Falls back to a direct /responses POST only when the auxiliary client is
    unavailable, for providers (xAI, direct OpenAI, compatible gateways) that
    accept the non-streaming Responses shape.
    """

    system_prompt = (
        "You are Torben, Eric Freeman's operational COO. "
        "Review inbox cleanup candidates conservatively. Return JSON only."
    )
    user_prompt = _hygiene_review_prompt(groups)
    timeout = _positive_int(os.getenv("TORBEN_EMAIL_HYGIENE_LLM_TIMEOUT_SECONDS"), DEFAULT_LLM_TIMEOUT_SECONDS)
    provider_override = str(os.getenv("TORBEN_EMAIL_HYGIENE_LLM_PROVIDER") or "").strip()
    provider = provider_override or DEFAULT_LLM_PROVIDER
    provider_key = provider.strip().lower()
    model_override = str(os.getenv("TORBEN_EMAIL_HYGIENE_LLM_MODEL") or "").strip()
    use_auxiliary_client = provider_key in {"openai-codex", "codex"}

    aux_error: Exception | None = None
    try:
        if not use_auxiliary_client:
            raise RuntimeError(f"provider {provider} uses direct /responses path")
        from agent.auxiliary_client import get_auxiliary_extra_body, get_text_auxiliary_client

        client, default_model = get_text_auxiliary_client("email_hygiene_review")
        if client is not None and default_model:
            model = model_override or default_model
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=1600,
                timeout=timeout,
                extra_body=get_auxiliary_extra_body() or None,
            )
            try:
                raw_text = resp.choices[0].message.content or ""
            except Exception:  # pragma: no cover - defensive shape guard
                raw_text = ""
            generated = _parse_json_object(raw_text)
            if not generated:
                raise RuntimeError("auxiliary hygiene review returned unparseable content")
            return generated, {
                "provider": "auxiliary_client",
                "model": model,
                "transport": type(client).__name__,
            }
    except Exception as exc:  # noqa: BLE001 - fall through to the direct path.
        aux_error = exc

    # Fallback: direct /responses POST for providers that accept the
    # non-streaming Responses shape (xAI, direct OpenAI, compatible gateways).
    from hermes_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested=provider)
    api_key = str(runtime.get("api_key") or "").strip()
    if not api_key:
        if aux_error is not None:
            raise RuntimeError(
                "hygiene LLM unavailable: auxiliary client failed "
                f"({type(aux_error).__name__}: {aux_error}); {provider} credentials unavailable"
            )
        raise RuntimeError(f"{provider} credentials unavailable")
    base_url = str(runtime.get("base_url") or "https://api.openai.com/v1").strip().rstrip("/")
    api_mode = str(runtime.get("api_mode") or "").strip()
    if "backend-api/codex" in base_url or provider_key in {"openai-codex", "codex"}:
        # This endpoint requires streaming + Cloudflare headers, which only the
        # auxiliary client implements. Surface the real reason, not a raw 400.
        raise RuntimeError(
            "hygiene LLM unavailable: Codex backend requires the auxiliary "
            f"client streaming transport (aux error: {type(aux_error).__name__ if aux_error else 'n/a'})"
        )
    model = str(
        model_override
        or runtime.get("model")
        or runtime.get("default_model")
        or DEFAULT_LLM_MODEL
    ).strip()
    request_payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "store": False,
        "max_output_tokens": 1600,
    }
    response = requests.post(
        f"{base_url}/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=request_payload,
        timeout=timeout,
    )
    response.raise_for_status()
    response_payload = response.json()
    generated = _parse_json_object(_extract_response_text(response_payload))
    return generated, {"provider": provider, "model": model, "base_url_host": base_url.split("//")[-1].split("/")[0]}


def _apply_llm_review(
    groups: list[HygieneGroup],
    generated: dict[str, Any],
    *,
    meta: dict[str, Any],
) -> list[HygieneGroup]:
    recommendations = generated.get("recommendations")
    if not isinstance(recommendations, list):
        raise ValueError("LLM hygiene review returned no recommendations list")
    by_key = {
        str(item.get("key") or ""): item
        for item in recommendations
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    reviewed: list[HygieneGroup] = []
    for group in groups:
        group_decision = by_key.get(group.key) or {}
        decision = str(group_decision.get("decision") or "keep").strip().lower()
        if decision == "drop":
            continue
        item_decisions = {
            str(item.get("message_id") or ""): item
            for item in group_decision.get("items", []) or []
            if isinstance(item, dict)
        }
        kept_items: list[dict[str, Any]] = []
        for item in group.items:
            item_decision = item_decisions.get(str(item.get("message_id") or "")) or {}
            if str(item_decision.get("decision") or "keep").strip().lower() == "drop":
                continue
            kept = dict(item)
            kept["llm_decision"] = str(item_decision.get("decision") or decision or "keep")
            kept["llm_reason"] = str(item_decision.get("reason") or group_decision.get("reason") or "").strip()
            kept_items.append(kept)
        if not kept_items:
            continue
        reviewed.append(
            HygieneGroup(
                key=group.key,
                title=group.title,
                operation=group.operation,
                risk_class=group.risk_class,
                rationale=group.rationale,
                apply_labels=group.apply_labels,
                items=kept_items,
                llm_review={
                    **meta,
                    "decision": decision or "keep",
                    "reason": str(group_decision.get("reason") or "").strip(),
                },
            )
        )
    return reviewed


def _review_hygiene_groups_with_llm(
    groups: list[HygieneGroup],
    *,
    enabled: bool,
) -> tuple[list[HygieneGroup], dict[str, Any]]:
    if not groups:
        return groups, {"invoked": False, "status": "no_candidates"}
    if not enabled:
        return groups, {"invoked": False, "status": "disabled"}
    try:
        generated, runtime_meta = _call_hygiene_llm(groups)
        meta = {
            "invoked": True,
            "status": "accepted",
            "fallback": False,
            "global_notes": list(generated.get("global_notes") or [])[:5],
            **runtime_meta,
        }
        reviewed = _apply_llm_review(groups, generated, meta=meta)
        return reviewed, {**meta, "groups_before": len(groups), "groups_after": len(reviewed)}
    except Exception as exc:  # noqa: BLE001 - cleanup must fail closed and keep review visible.
        meta = {
            "invoked": True,
            "status": "failed_deterministic_fallback",
            "fallback": True,
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
            "groups_before": len(groups),
            "groups_after": len(groups),
        }
        for group in groups:
            group.llm_review = meta
        return groups, meta


def _existing_hygiene_actions(ledger: ActionLedger) -> dict[str, ActionRecord]:
    existing: dict[str, ActionRecord] = {}
    for record in ledger.load():
        state = record.executor_state or {}
        key = state.get("hygiene_action_key")
        if (
            record.scope == "ea"
            and isinstance(key, str)
            and state.get("hygiene_policy_version") == HYGIENE_POLICY_VERSION
            and record.status in HYGIENE_OPEN_STATUSES
        ):
            existing[key] = record
    return existing


def stage_hygiene_actions(
    *,
    ledger: ActionLedger,
    records: list[dict[str, Any]],
    now: datetime | None = None,
    enable_llm_review: bool = False,
    review_metadata_out: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    now = (now or _now()).astimezone(timezone.utc)
    existing = _existing_hygiene_actions(ledger)
    groups, review_meta = _review_hygiene_groups_with_llm(
        _group_candidate_records(records, now=now),
        enabled=enable_llm_review,
    )
    if review_metadata_out is not None:
        review_metadata_out.update(review_meta)
    staged: list[dict[str, Any]] = []
    records_to_save: list[ActionRecord] | None = None
    for group in groups:
        action_key = f"{ACTION_PREFIX}:{group.key}:{now:%Y-%m-%d}"
        record = existing.get(action_key)
        evidence_ids = [
            evidence
            for item in group.items[:10]
            for evidence in (item.get("evidence_ids") or [])
        ]
        executor_state = {
            "mutation_type": "gmail_hygiene",
            "provider": "gmail",
            "mutation_status": "not_applied",
            "hygiene_policy_version": HYGIENE_POLICY_VERSION,
            "hygiene_action_key": action_key,
            "operation": group.operation,
            "apply_labels": group.apply_labels,
            "rationale": group.rationale,
            "items": group.items,
            "llm_review": group.llm_review or review_meta,
            "approval_required": True,
        }
        if record is None:
            record = ledger.add_action(
                scope="EA",
                summary=group.to_action_summary(),
                evidence_ids=evidence_ids,
                allowed_next_actions=["approve_hygiene_apply", "revise", "discard"],
                status="approval_required",
                risk_class=group.risk_class,
                ttl_hours=14 * 24,
                now=now,
                executor_state=executor_state,
            )
            existing[action_key] = record
        else:
            if records_to_save is None:
                records_to_save = ledger.load()
            for candidate in records_to_save:
                if candidate.handle != record.handle:
                    continue
                candidate.summary = group.to_action_summary()
                candidate.evidence_ids = evidence_ids
                candidate.risk_class = group.risk_class
                candidate.executor_state.update(executor_state)
                candidate.resolution_history.append(
                    {
                        "at": now.isoformat().replace("+00:00", "Z"),
                        "status": "recommendation_refreshed",
                        "reason": "Weekly email hygiene recommendation refreshed with current inbox evidence.",
                    }
                )
                record = candidate
                existing[action_key] = candidate
                break
        staged.append(
            {
                "handle": record.handle,
                "status": record.status,
                **group.to_payload(),
            }
        )
    if records_to_save is not None:
        ledger.save(records_to_save)
    return staged


def _gmail_post(url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _gmail_get(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _profile_home_from_config(config_path: str | Path) -> Path:
    config = Path(config_path)
    if config.name == "google_accounts.yaml" and config.parent.name == "config":
        return config.parent.parent
    return config.parent


def _policy_context(
    *,
    config_path: str | Path,
    profile_home: str | Path | None = None,
    policy_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    resolved_home = Path(profile_home).expanduser() if profile_home else _profile_home_from_config(config_path)
    policy = load_torben_automation_policy(profile_home=resolved_home, policy_path=policy_path)
    ea = policy.get("ea") if isinstance(policy.get("ea"), dict) else {}
    mutations = ea.get("mutations") if isinstance(ea.get("mutations"), dict) else {}
    mutation_policy = (
        mutations.get("email_archive_delete_label")
        if isinstance(mutations.get("email_archive_delete_label"), dict)
        else {}
    )
    decision = ea_automation_decisions(policy=policy)["email_archive_delete_label"]
    return policy, mutation_policy, decision, resolved_home


def _resolve_audit_path(*, profile_home: Path, policy_decision: dict[str, Any]) -> Path:
    raw = str(policy_decision.get("audit_log_path") or "state/torben-email-hygiene-audit.jsonl").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = profile_home / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_hygiene_audit(
    *,
    audit_path: Path,
    handle: str,
    operation: str,
    approved_by: str,
    result: dict[str, Any],
    policy_decision: dict[str, Any],
    now: str,
) -> None:
    if not result.get("applied") and not result.get("errors"):
        return
    record = {
        "ts": now,
        "handle": handle,
        "operation": operation,
        "approved_by": approved_by,
        "dry_run": bool(result.get("dry_run")),
        "external_mutations": int(result.get("external_mutations") or 0),
        "gmail_write_api_calls": int(result.get("gmail_write_api_calls") or 0),
        "applied": result.get("applied") or [],
        "skipped": result.get("skipped") or [],
        "errors": result.get("errors") or [],
        "policy_decision": policy_decision,
        "rollback_note": (
            "Archive/label can be reversed by restoring INBOX or removing labels; "
            "trash can be restored from Gmail Trash until Gmail purges it."
        ),
    }
    with audit_path.open("a", encoding="utf-8") as handle_obj:
        handle_obj.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _label_names_for_item(state: dict[str, Any], item: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = []
    for key in ("apply_labels", "label_names", "labels_to_apply"):
        value = item.get(key)
        if value is not None:
            raw_values.append(value)
    for key in ("apply_labels", "label_names", "labels_to_apply"):
        value = state.get(key)
        if value is not None:
            raw_values.append(value)
    for action in list(item.get("suggested_actions") or []) + list(state.get("suggested_actions") or []):
        action_text = str(action or "").strip()
        if action_text.lower().startswith("apply_label:"):
            raw_values.append(action_text.split(":", 1)[1].strip())

    labels: list[str] = []
    for value in raw_values:
        items = value if isinstance(value, list) else [value]
        for item_value in items:
            label = str(item_value or "").strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def _validate_label_names(label_names: list[str]) -> None:
    for label_name in label_names:
        if label_name not in SAFE_HYGIENE_LABEL_NAMES:
            raise ValueError(f"Refusing unapproved hygiene label: {label_name}")


def _gmail_label_id_for_name(
    *,
    token: str,
    label_name: str,
    cache: dict[str, str],
) -> str:
    cached = cache.get(label_name)
    if cached:
        return cached
    labels = _gmail_get(f"{GMAIL_API_ROOT}/labels", token).get("labels") or []
    for label in labels:
        if str(label.get("name") or "") == label_name and label.get("id"):
            cache[label_name] = str(label["id"])
            return cache[label_name]
    created = _gmail_post(
        f"{GMAIL_API_ROOT}/labels",
        token,
        {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    )
    label_id = str(created.get("id") or "").strip()
    if not label_id:
        raise RuntimeError(f"Gmail did not return an id for created label {label_name!r}")
    cache[label_name] = label_id
    return label_id


def _validate_item_for_operation(operation: str, item: dict[str, Any]) -> None:
    category = str(item.get("category") or "")
    reason = str(item.get("reason") or "").lower()
    cleanup_status = str(item.get("cleanup_status") or "").lower()
    juno_bucket = str(item.get("juno_bucket") or "")
    labels = {str(label or "").upper() for label in item.get("labels") or []}
    stale_account_code = category == "account_security" and "older than one hour" in reason
    existing_spam = "SPAM" in labels and "already marked spam" in reason
    safe_v3_trash = (
        cleanup_status.startswith("trash_")
        and category in LOW_SIGNAL_TRASH_CATEGORIES
        and juno_bucket in {"", "info"}
    )
    if operation == "trash" and not (stale_account_code or existing_spam or safe_v3_trash):
        raise ValueError(f"Refusing to trash item outside approved stale-code/spam classes: {item.get('message_id')}")
    if operation in {"archive", "archive_and_label"} and category not in ARCHIVABLE_CATEGORIES:
        raise ValueError(f"Refusing to archive actionable category {category}: {item.get('message_id')}")
    if operation == "label" and category in ACTIONABLE_CATEGORIES:
        raise ValueError(f"Refusing to label actionable category {category}: {item.get('message_id')}")


def apply_hygiene_action(
    *,
    ledger: ActionLedger,
    config_path: str | Path,
    handle: str,
    approved_by: str = "signal",
    dry_run: bool = False,
    auto_apply: bool = False,
    profile_home: str | Path | None = None,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    record = ledger.get(handle)
    if record is None:
        raise ValueError(f"No action found for handle: {handle}")
    state = dict(record.executor_state or {})
    if state.get("mutation_type") != "gmail_hygiene":
        raise ValueError(f"Action {handle} is not a Gmail hygiene action.")
    if "approve_hygiene_apply" not in record.allowed_next_actions:
        raise ValueError(f"Action {handle} is not approved for Gmail hygiene apply.")
    if record.status not in {"approval_required", "approved", "executing"}:
        raise ValueError(f"Action {handle} is not open for hygiene apply: {record.status}")
    operation = str(state.get("operation") or "")
    if operation not in {"trash", "archive", "archive_and_label", "label", "nudge_only"}:
        raise ValueError(f"Unsupported hygiene operation for {handle}: {operation}")
    items = list(state.get("items") or [])
    if len(items) > 50:
        raise ValueError(f"Refusing to apply more than 50 items in one hygiene action: {len(items)}")
    _, mutation_policy, policy_decision, resolved_home = _policy_context(
        config_path=config_path,
        profile_home=profile_home,
        policy_path=policy_path,
    )
    policy_max = int(mutation_policy.get("max_per_run") or 0)

    now = _now().isoformat().replace("+00:00", "Z")
    result = {
        "handle": handle,
        "operation": operation,
        "dry_run": dry_run,
        "auto_apply": auto_apply,
        "policy_decision": policy_decision,
        "applied": [],
        "skipped": [],
        "errors": [],
        "external_mutations": 0,
        "gmail_write_api_calls": 0,
    }
    if auto_apply:
        if not bool(policy_decision.get("mutation_allowed")):
            result["errors"].append(
                {
                    "error": "email_archive_delete_label_policy_blocks_auto_apply",
                    "reason": policy_decision.get("reason"),
                }
            )
        elif policy_max > 0 and len(items) > policy_max:
            result["errors"].append(
                {
                    "error": "email_archive_delete_label_policy_max_per_run_exceeded",
                    "max_per_run": policy_max,
                    "requested": len(items),
                }
            )
    if result["errors"]:
        audit_path = _resolve_audit_path(profile_home=resolved_home, policy_decision=policy_decision)
        _append_hygiene_audit(
            audit_path=audit_path,
            handle=handle,
            operation=operation,
            approved_by=approved_by,
            result=result,
            policy_decision=policy_decision,
            now=now,
        )
        return result
    tokens: dict[str, str] = {}
    label_cache_by_account: dict[str, dict[str, str]] = {}
    for item in items:
        account_alias = str(item.get("account_alias") or "")
        message_id = str(item.get("message_id") or "")
        if not account_alias or not message_id:
            result["skipped"].append({"item": item, "reason": "missing account_alias or message_id"})
            continue
        try:
            _validate_item_for_operation(operation, item)
        except ValueError as exc:
            result["errors"].append({"message_id": message_id, "error": str(exc)})
            continue
        label_names = _label_names_for_item(state, item)
        if operation in {"label", "archive_and_label"} and not label_names:
            result["errors"].append({"message_id": message_id, "error": "missing label_names for label operation"})
            continue
        try:
            _validate_label_names(label_names)
        except ValueError as exc:
            result["errors"].append({"message_id": message_id, "error": str(exc)})
            continue
        if operation == "nudge_only":
            result["applied"].append(
                {
                    "account_alias": account_alias,
                    "message_id": message_id,
                    "nudge_only": True,
                    "reason": "rebumped in action ledger without Gmail mutation",
                }
            )
            continue
        if dry_run:
            result["applied"].append(
                {
                    "account_alias": account_alias,
                    "message_id": message_id,
                    "dry_run": True,
                    "labels": label_names,
                }
            )
            continue
        token = tokens.get(account_alias)
        if token is None:
            token = _read_token(account_for_alias(config_path, account_alias))
            tokens[account_alias] = token
        try:
            if operation == "trash":
                if label_names:
                    label_cache = label_cache_by_account.setdefault(account_alias, {})
                    label_ids = [
                        _gmail_label_id_for_name(token=token, label_name=label_name, cache=label_cache)
                        for label_name in label_names
                    ]
                    _gmail_post(
                        f"{GMAIL_API_ROOT}/messages/{message_id}/modify",
                        token,
                        {"addLabelIds": label_ids},
                    )
                    result["gmail_write_api_calls"] += 1
                    result["external_mutations"] += 1
                _gmail_post(f"{GMAIL_API_ROOT}/messages/{message_id}/trash", token)
                applied_payload = {"account_alias": account_alias, "message_id": message_id, "labels": label_names}
            elif operation in {"archive", "archive_and_label", "label"}:
                label_ids: list[str] = []
                if label_names:
                    label_cache = label_cache_by_account.setdefault(account_alias, {})
                    label_ids = [
                        _gmail_label_id_for_name(token=token, label_name=label_name, cache=label_cache)
                        for label_name in label_names
                    ]
                payload: dict[str, Any] = {}
                if operation in {"archive", "archive_and_label"}:
                    payload["removeLabelIds"] = ["INBOX"]
                if label_ids:
                    payload["addLabelIds"] = label_ids
                _gmail_post(
                    f"{GMAIL_API_ROOT}/messages/{message_id}/modify",
                    token,
                    payload,
                )
                applied_payload = {
                    "account_alias": account_alias,
                    "message_id": message_id,
                    "labels": label_names,
                }
            result["gmail_write_api_calls"] += 1
            result["external_mutations"] += 1
            result["applied"].append(applied_payload)
        except urllib.error.HTTPError as exc:  # pragma: no cover - live API path
            result["gmail_write_api_calls"] += 1
            result["errors"].append({"message_id": message_id, "error": f"HTTP {exc.code}"})
        except Exception as exc:  # pragma: no cover - live API path
            result["errors"].append({"message_id": message_id, "error": type(exc).__name__})

    records = ledger.load()
    success = bool(result["applied"]) and not result["errors"] and not dry_run
    if dry_run:
        mutation_status = "dry_run"
    elif success and operation == "nudge_only":
        mutation_status = "nudged"
    elif success:
        mutation_status = "applied"
    else:
        mutation_status = "blocked"
    for candidate in records:
        if candidate.handle != record.handle:
            continue
        candidate.status = "executed" if success else candidate.status
        candidate.executor_state.update(
            {
                "mutation_status": mutation_status,
                "last_apply_result": result,
                "applied_at": now if success else None,
            }
        )
        candidate.resolution_history.append(
            {
                "at": now,
                "status": "dry_run" if dry_run else candidate.executor_state["mutation_status"],
                "reason": f"Email hygiene apply requested by {approved_by}.",
            }
        )
    ledger.save(records)
    audit_path = _resolve_audit_path(profile_home=resolved_home, policy_decision=policy_decision)
    _append_hygiene_audit(
        audit_path=audit_path,
        handle=handle,
        operation=operation,
        approved_by=approved_by,
        result=result,
        policy_decision=policy_decision,
        now=now,
    )
    return result
