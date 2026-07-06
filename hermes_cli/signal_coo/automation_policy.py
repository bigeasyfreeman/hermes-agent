"""Shared Torben automation policy decisions.

The policy is deliberately conservative. Scheduled loops may collect evidence,
draft, and surface recommendations automatically. Public, destructive, or
capital-moving actions remain fail-closed unless a scoped allowlist explicitly
permits the exact mutation class.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

try:
    import yaml
except Exception:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


POLICY_FILENAME = "torben-automation-policy.yaml"
SCHEMA_VERSION = 1


def _default_policy() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_id": "torben-automation-policy-default-fail-closed",
        "mode": "fail_closed",
        "gtm": {
            "auto_invoke": {
                "radar": True,
                "engagement_radar": True,
                "draft_content": True,
                "draft_reply": True,
            },
            "recommendations": {
                "auto_surface": True,
                "max_items_per_run": 3,
            },
            "delivery_cooldown_minutes": 45,
            "public_mutations": {
                "enabled": False,
                "allowed_accounts": [],
                "allowed_content_types": [],
                "max_risk_class": "medium",
                "approval_mode": "explicit_signal_handle",
                "rollback_path": "docs/operations/torben-gtm-public-write-runbook.md",
                "audit_log_path": "state/torben-public-write-audit.jsonl",
            },
        },
        "ea": {
            "auto_invoke": {
                "recommendation_surface": True,
                "relationship_learning_question": True,
            },
            "relationship_learning": {
                "auto_capture_questions": True,
                "act_requires_answer_or_trusted_source": True,
                "write_path": "config/learned_contacts.yaml",
            },
            "mutations": {
                "email_send": {
                    "enabled": False,
                    "allowed_senders": [],
                    "allowed_domains": [],
                    "max_per_run": 0,
                    "approval_mode": "explicit_signal_handle",
                    "dry_run_required": True,
                    "audit_log_path": "state/torben-email-mutation-audit.jsonl",
                },
                "email_archive_delete_label": {
                    "enabled": False,
                    "allowed_senders": [],
                    "allowed_domains": [],
                    "max_per_run": 0,
                    "approval_mode": "explicit_signal_handle",
                    "dry_run_required": True,
                    "audit_log_path": "state/torben-email-hygiene-audit.jsonl",
                },
                "calendar_edit": {
                    "enabled": False,
                    "allowed_calendars": [],
                    "allowed_event_types": [],
                    "max_per_run": 0,
                    "approval_mode": "explicit_signal_handle",
                    "dry_run_required": True,
                    "audit_log_path": "state/torben-calendar-mutation-audit.jsonl",
                },
            },
        },
        "finance": {
            "auto_invoke": {
                "research_refresh": True,
                "recommendation_surface": True,
                "paper_canary": True,
                "monarch_daily_savings": True,
                "monarch_weekly_savings": True,
            },
            "monarch_research": {
                "enabled": True,
                "required_read_tools": [
                    "GetTransactions",
                    "GetRecurring",
                    "GetSpendingByCategory",
                    "GetBudget",
                    "GetCashFlow",
                    "GetAccounts",
                    "GetMerchants",
                    "GetCategories",
                    "GetTags",
                    "ListRules",
                ],
                "max_transactions_per_run": 200,
                "redact_raw_transactions": True,
                "write_latest_artifact": True,
                "stage_fin_review_handles": True,
            },
            "monarch_mutations": {
                "enabled": False,
                "allowed_tools": [],
                "max_writes_per_run": 0,
                "approval_mode": "explicit_signal_handle",
                "dry_run_required": True,
                "audit_log_path": "state/torben-monarch-mutation-audit.jsonl",
            },
            "live_orders": {
                "enabled": False,
                "allowed_accounts": [],
                "allowed_symbols": [],
                "max_notional_usd": 0,
                "max_orders_per_run": 0,
                "approval_mode": "scoped_live_trading_policy",
                "requires_mandate": True,
                "requires_kill_switch": True,
                "requires_reconciliation": True,
                "audit_log_path": "state/torben-finance-live-order-audit.jsonl",
            },
        },
    }


def load_torben_automation_policy(
    *,
    profile_home: str | Path | None = None,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load Torben's policy from profile config or return fail-closed defaults."""

    env_path = str(os.getenv("TORBEN_AUTOMATION_POLICY_PATH") or "").strip()
    resolved_path = Path(policy_path or env_path) if (policy_path or env_path) else _policy_path(profile_home)
    policy = _default_policy()
    meta = {
        "path": str(resolved_path),
        "loaded": False,
        "source": "default_fail_closed",
        "error": None,
    }
    if resolved_path.exists():
        try:
            if yaml is None:
                raise RuntimeError("PyYAML is unavailable")
            loaded = yaml.safe_load(resolved_path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError("policy root must be a mapping")
            policy = _deep_merge(policy, loaded)
            meta["loaded"] = True
            meta["source"] = "profile_config"
        except Exception as exc:  # noqa: BLE001
            meta["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    policy["_meta"] = meta
    return policy


def gtm_automation_decision(
    *,
    action: str,
    public_mutation: bool = False,
    account: str | None = None,
    content_type: str | None = None,
    risk_class: str = "medium",
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or load_torben_automation_policy()
    gtm = _dict(policy.get("gtm"))
    public_policy = _dict(gtm.get("public_mutations"))
    auto = _dict(gtm.get("auto_invoke"))
    recommendations = _dict(gtm.get("recommendations"))
    auto_allowed = bool(auto.get("radar")) and bool(auto.get(action, True))
    recommendation_allowed = bool(recommendations.get("auto_surface"))
    if public_mutation:
        mutation_allowed = _public_mutation_allowed(
            public_policy,
            account=account,
            content_type=content_type,
            risk_class=risk_class,
        )
        decision = "allowed" if mutation_allowed else "approval_required"
        reason = (
            "gtm_public_mutation_allowlisted"
            if mutation_allowed
            else "gtm_public_mutation_requires_explicit_allowlist_and_approval"
        )
    else:
        mutation_allowed = False
        decision = "allowed" if auto_allowed and recommendation_allowed else "blocked"
        reason = (
            "gtm_auto_surface_recommendation_allowed"
            if decision == "allowed"
            else "gtm_auto_surface_disabled_by_policy"
        )
    return _decision(
        policy=policy,
        domain="gtm",
        action=action,
        decision=decision,
        reason=reason,
        auto_invoke_allowed=auto_allowed and not public_mutation,
        recommendation_allowed=recommendation_allowed and not public_mutation,
        mutation_allowed=mutation_allowed,
        approval_mode=str(public_policy.get("approval_mode") or "explicit_signal_handle"),
        audit_log_path=str(public_policy.get("audit_log_path") or ""),
        rollback_path=str(public_policy.get("rollback_path") or ""),
    )


def ea_automation_decisions(*, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_torben_automation_policy()
    ea = _dict(policy.get("ea"))
    auto = _dict(ea.get("auto_invoke"))
    relationship = _dict(ea.get("relationship_learning"))
    mutations = _dict(ea.get("mutations"))
    recommendation_allowed = bool(auto.get("recommendation_surface"))
    relationship_allowed = bool(auto.get("relationship_learning_question")) and bool(
        relationship.get("auto_capture_questions")
    )
    return {
        "recommendations": _decision(
            policy=policy,
            domain="ea",
            action="surface_recommendation",
            decision="allowed" if recommendation_allowed else "blocked",
            reason=(
                "ea_recommendations_auto_surface_allowed"
                if recommendation_allowed
                else "ea_recommendations_disabled_by_policy"
            ),
            auto_invoke_allowed=recommendation_allowed,
            recommendation_allowed=recommendation_allowed,
            mutation_allowed=False,
        ),
        "relationship_learning": _decision(
            policy=policy,
            domain="ea",
            action="relationship_learning_question",
            decision="allowed" if relationship_allowed else "blocked",
            reason=(
                "relationship_questions_auto_capture_allowed_acting_requires_answer"
                if relationship_allowed
                else "relationship_learning_questions_disabled_by_policy"
            ),
            auto_invoke_allowed=relationship_allowed,
            recommendation_allowed=relationship_allowed,
            mutation_allowed=False,
            approval_mode="answer_or_trusted_source_required",
            audit_log_path=str(relationship.get("write_path") or ""),
        ),
        "email_send": _mutation_decision(
            policy=policy,
            domain="ea",
            action="email_send",
            mutation_policy=_dict(mutations.get("email_send")),
        ),
        "email_archive_delete_label": _mutation_decision(
            policy=policy,
            domain="ea",
            action="email_archive_delete_label",
            mutation_policy=_dict(mutations.get("email_archive_delete_label")),
        ),
        "calendar_edit": _mutation_decision(
            policy=policy,
            domain="ea",
            action="calendar_edit",
            mutation_policy=_dict(mutations.get("calendar_edit")),
        ),
    }


def finance_automation_decisions(*, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_torben_automation_policy()
    finance = _dict(policy.get("finance"))
    auto = _dict(finance.get("auto_invoke"))
    live_orders = _dict(finance.get("live_orders"))
    monarch_research = _dict(finance.get("monarch_research"))
    monarch_mutations = _dict(finance.get("monarch_mutations"))
    research_allowed = bool(auto.get("research_refresh")) and bool(auto.get("recommendation_surface"))
    paper_allowed = research_allowed and bool(auto.get("paper_canary"))
    monarch_required_tools = {str(item) for item in _list(monarch_research.get("required_read_tools"))}
    monarch_research_allowed = (
        research_allowed
        and bool(monarch_research.get("enabled"))
        and bool(auto.get("monarch_daily_savings"))
        and bool(auto.get("monarch_weekly_savings"))
        and _required_monarch_read_tools().issubset(monarch_required_tools)
        and bool(monarch_research.get("redact_raw_transactions"))
    )
    monarch_mutation_allowed = (
        bool(monarch_mutations.get("enabled"))
        and int(monarch_mutations.get("max_writes_per_run") or 0) > 0
        and bool(_list(monarch_mutations.get("allowed_tools")))
    )
    live_enabled = bool(live_orders.get("enabled"))
    live_allowed = live_enabled and int(live_orders.get("max_orders_per_run") or 0) > 0
    return {
        "research": _decision(
            policy=policy,
            domain="finance",
            action="research_recommendation",
            decision="allowed" if research_allowed else "blocked",
            reason=(
                "finance_research_recommendations_auto_surface_allowed"
                if research_allowed
                else "finance_research_auto_surface_disabled_by_policy"
            ),
            auto_invoke_allowed=research_allowed,
            recommendation_allowed=research_allowed,
            mutation_allowed=False,
        ),
        "paper_canary": _decision(
            policy=policy,
            domain="finance",
            action="paper_canary",
            decision="allowed" if paper_allowed else "blocked",
            reason=(
                "finance_paper_canary_allowed_no_live_order"
                if paper_allowed
                else "finance_paper_canary_disabled_by_policy"
            ),
            auto_invoke_allowed=paper_allowed,
            recommendation_allowed=paper_allowed,
            mutation_allowed=False,
        ),
        "monarch_research": _decision(
            policy=policy,
            domain="finance",
            action="monarch_savings_research",
            decision="allowed" if monarch_research_allowed else "blocked",
            reason=(
                "monarch_savings_read_only_research_allowed"
                if monarch_research_allowed
                else "monarch_savings_research_requires_read_allowlist_and_redaction"
            ),
            auto_invoke_allowed=monarch_research_allowed,
            recommendation_allowed=monarch_research_allowed,
            mutation_allowed=False,
            audit_log_path="state/torben-monarch-savings-ledger.json",
        ),
        "monarch_mutation": _decision(
            policy=policy,
            domain="finance",
            action="monarch_mutation",
            decision="allowed" if monarch_mutation_allowed else "approval_required",
            reason=(
                "monarch_mutation_allowlisted"
                if monarch_mutation_allowed
                else "monarch_mutations_require_explicit_allowlist_and_approval"
            ),
            auto_invoke_allowed=False,
            recommendation_allowed=False,
            mutation_allowed=monarch_mutation_allowed,
            approval_mode=str(monarch_mutations.get("approval_mode") or "explicit_signal_handle"),
            audit_log_path=str(monarch_mutations.get("audit_log_path") or ""),
        ),
        "live_order": _decision(
            policy=policy,
            domain="finance",
            action="live_order",
            decision="allowed" if live_allowed else "blocked",
            reason=(
                "finance_live_order_scoped_policy_enabled"
                if live_allowed
                else "finance_live_orders_blocked_without_scoped_live_trading_policy"
            ),
            auto_invoke_allowed=False,
            recommendation_allowed=False,
            mutation_allowed=live_allowed,
            approval_mode=str(live_orders.get("approval_mode") or "scoped_live_trading_policy"),
            audit_log_path=str(live_orders.get("audit_log_path") or ""),
        ),
    }


def automation_policy_digest(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_torben_automation_policy()
    return {
        "policy_id": policy.get("policy_id"),
        "schema_version": policy.get("schema_version"),
        "mode": policy.get("mode"),
        "path": _dict(policy.get("_meta")).get("path"),
        "loaded": bool(_dict(policy.get("_meta")).get("loaded")),
        "gtm_delivery_cooldown_minutes": int(_dict(policy.get("gtm")).get("delivery_cooldown_minutes") or 0),
        "gtm_public_mutations_enabled": bool(
            _dict(_dict(policy.get("gtm")).get("public_mutations")).get("enabled")
        ),
        "ea_mutations_enabled": any(
            bool(_dict(item).get("enabled"))
            for item in _dict(_dict(policy.get("ea")).get("mutations")).values()
        ),
        "finance_live_orders_enabled": bool(
            _dict(_dict(policy.get("finance")).get("live_orders")).get("enabled")
        ),
        "finance_monarch_research_enabled": bool(
            _dict(_dict(policy.get("finance")).get("monarch_research")).get("enabled")
        ),
        "finance_monarch_mutations_enabled": bool(
            _dict(_dict(policy.get("finance")).get("monarch_mutations")).get("enabled")
        ),
    }


def validate_automation_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_torben_automation_policy()
    errors: list[str] = []
    warnings: list[str] = []
    if int(policy.get("schema_version") or 0) != SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if str(policy.get("mode") or "") != "fail_closed":
        errors.append("mode_must_be_fail_closed")

    gtm_public = _dict(_dict(policy.get("gtm")).get("public_mutations"))
    for key in ("approval_mode", "rollback_path", "audit_log_path"):
        if not str(gtm_public.get(key) or "").strip():
            errors.append(f"gtm_public_mutations_missing_{key}")
    if bool(gtm_public.get("enabled")) and not _list(gtm_public.get("allowed_accounts")):
        errors.append("gtm_public_mutations_enabled_without_allowed_accounts")

    ea_mutations = _dict(_dict(policy.get("ea")).get("mutations"))
    for name in ("email_send", "email_archive_delete_label", "calendar_edit"):
        mutation = _dict(ea_mutations.get(name))
        for key in ("approval_mode", "audit_log_path"):
            if not str(mutation.get(key) or "").strip():
                errors.append(f"ea_{name}_missing_{key}")
        if bool(mutation.get("enabled")) and int(mutation.get("max_per_run") or 0) <= 0:
            errors.append(f"ea_{name}_enabled_without_positive_max_per_run")

    live_orders = _dict(_dict(policy.get("finance")).get("live_orders"))
    monarch_research = _dict(_dict(policy.get("finance")).get("monarch_research"))
    monarch_mutations = _dict(_dict(policy.get("finance")).get("monarch_mutations"))
    configured_read_tools = {str(item) for item in _list(monarch_research.get("required_read_tools"))}
    missing_read_tools = sorted(_required_monarch_read_tools() - configured_read_tools)
    if not bool(monarch_research.get("enabled")):
        warnings.append("finance_monarch_research_disabled")
    if missing_read_tools:
        errors.append(f"finance_monarch_research_missing_read_tools:{','.join(missing_read_tools)}")
    if not bool(monarch_research.get("redact_raw_transactions")):
        errors.append("finance_monarch_research_must_redact_raw_transactions")
    if int(monarch_research.get("max_transactions_per_run") or 0) <= 0:
        errors.append("finance_monarch_research_missing_positive_max_transactions_per_run")
    for key in ("approval_mode", "audit_log_path"):
        if not str(monarch_mutations.get(key) or "").strip():
            errors.append(f"finance_monarch_mutations_missing_{key}")
    if bool(monarch_mutations.get("enabled")):
        if int(monarch_mutations.get("max_writes_per_run") or 0) <= 0:
            errors.append("finance_monarch_mutations_enabled_without_positive_max_writes_per_run")
        if not _list(monarch_mutations.get("allowed_tools")):
            errors.append("finance_monarch_mutations_enabled_without_allowed_tools")
        warnings.append("finance_monarch_mutations_enabled_requires_current_human_approval")

    for key in ("approval_mode", "audit_log_path"):
        if not str(live_orders.get(key) or "").strip():
            errors.append(f"finance_live_orders_missing_{key}")
    if bool(live_orders.get("enabled")):
        if int(live_orders.get("max_orders_per_run") or 0) <= 0:
            errors.append("finance_live_orders_enabled_without_positive_max_orders_per_run")
        if not _list(live_orders.get("allowed_accounts")):
            errors.append("finance_live_orders_enabled_without_allowed_accounts")
        warnings.append("finance_live_orders_enabled_requires_current_human_approval")

    meta = _dict(policy.get("_meta"))
    if meta.get("error"):
        errors.append("policy_load_error")
    return {
        "status": "pass" if not errors else "fail_closed",
        "errors": errors,
        "warnings": warnings,
        "policy": automation_policy_digest(policy),
    }


def write_automation_policy_artifact(
    *,
    profile_home: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    policy = load_torben_automation_policy(profile_home=profile_home)
    validation = validate_automation_policy(policy)
    home = Path(profile_home) if profile_home else get_hermes_home()
    output = Path(output_path) if output_path else home / "state" / "torben-automation-policy-latest.json"
    artifact = {
        "task": "torben_automation_policy_verify",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": validation["status"],
        "validation": validation,
        "decisions": {
            "gtm_recommendation": gtm_automation_decision(action="draft_content", policy=policy),
            "gtm_public_post": gtm_automation_decision(
                action="public_post",
                public_mutation=True,
                account="default",
                content_type="x_post",
                policy=policy,
            ),
            "ea": ea_automation_decisions(policy=policy),
            "finance": finance_automation_decisions(policy=policy),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output, json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    return artifact


def _policy_path(profile_home: str | Path | None) -> Path:
    home = Path(profile_home) if profile_home else get_hermes_home()
    return home / "config" / POLICY_FILENAME


def _decision(
    *,
    policy: dict[str, Any],
    domain: str,
    action: str,
    decision: str,
    reason: str,
    auto_invoke_allowed: bool,
    recommendation_allowed: bool,
    mutation_allowed: bool,
    approval_mode: str | None = None,
    audit_log_path: str | None = None,
    rollback_path: str | None = None,
) -> dict[str, Any]:
    return {
        "policy_id": policy.get("policy_id"),
        "policy_path": _dict(policy.get("_meta")).get("path"),
        "policy_loaded": bool(_dict(policy.get("_meta")).get("loaded")),
        "domain": domain,
        "action": action,
        "decision": decision,
        "reason": reason,
        "auto_invoke_allowed": bool(auto_invoke_allowed),
        "recommendation_allowed": bool(recommendation_allowed),
        "mutation_allowed": bool(mutation_allowed),
        "approval_mode": approval_mode,
        "audit_log_path": audit_log_path,
        "rollback_path": rollback_path,
    }


def _mutation_decision(
    *,
    policy: dict[str, Any],
    domain: str,
    action: str,
    mutation_policy: dict[str, Any],
) -> dict[str, Any]:
    enabled = bool(mutation_policy.get("enabled"))
    capped = int(mutation_policy.get("max_per_run") or 0) > 0
    allowed = enabled and capped
    return _decision(
        policy=policy,
        domain=domain,
        action=action,
        decision="allowed" if allowed else "approval_required",
        reason=(
            f"{domain}_{action}_allowlisted"
            if allowed
            else f"{domain}_{action}_requires_explicit_allowlist_and_approval"
        ),
        auto_invoke_allowed=False,
        recommendation_allowed=False,
        mutation_allowed=allowed,
        approval_mode=str(mutation_policy.get("approval_mode") or "explicit_signal_handle"),
        audit_log_path=str(mutation_policy.get("audit_log_path") or ""),
    )


def _public_mutation_allowed(
    public_policy: dict[str, Any],
    *,
    account: str | None,
    content_type: str | None,
    risk_class: str,
) -> bool:
    if not bool(public_policy.get("enabled")):
        return False
    accounts = {str(item).lower() for item in _list(public_policy.get("allowed_accounts"))}
    content_types = {str(item).lower() for item in _list(public_policy.get("allowed_content_types"))}
    if accounts and str(account or "").lower() not in accounts:
        return False
    if content_types and str(content_type or "").lower() not in content_types:
        return False
    return _risk_rank(risk_class) <= _risk_rank(str(public_policy.get("max_risk_class") or "low"))


def _risk_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(str(value or "").lower(), 99)


def _required_monarch_read_tools() -> set[str]:
    return {
        "GetTransactions",
        "GetRecurring",
        "GetSpendingByCategory",
        "GetBudget",
        "GetCashFlow",
        "GetAccounts",
        "GetMerchants",
        "GetCategories",
        "GetTags",
        "ListRules",
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
