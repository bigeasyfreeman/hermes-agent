"""Read-only Monarch savings research loop for Torben."""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .action_ledger import ActionLedger, ActionRecord
from .automation_policy import finance_automation_decisions, load_torben_automation_policy

MONARCH_SERVER_NAME = "monarch-money-mcp"
ALLOWED_MONARCH_READ_TOOLS = frozenset(
    {
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
)
MONARCH_MUTATION_PREFIXES = ("Create", "Update", "Bulk", "Delete", "Merge", "Contribute", "Withdraw")
MONARCH_SAVINGS_STATE_VERSION = 1
DEFAULT_DAILY_MAX_ITEMS = 5
DEFAULT_WEEKLY_MAX_ITEMS = 10
DEFAULT_DAILY_MIN_SCORE = 70
DEFAULT_WEEKLY_MIN_SCORE = 55

Dispatcher = Callable[[str, dict[str, Any]], str]


class MonarchReadOnlyToolBlocked(RuntimeError):
    """Raised before a non-read Monarch MCP tool can be dispatched."""


@dataclass
class MonarchReadOnlyClient:
    """Deterministic read-only facade over Hermes-registered MCP handlers."""

    server_name: str = MONARCH_SERVER_NAME
    dispatcher: Dispatcher | None = None
    discoverer: Callable[[], list[str]] | None = None
    read_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    blocked_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    _discovered: bool = False

    def call_read_tool(self, tool_name: str, args: dict[str, Any] | None = None) -> Any:
        args = dict(args or {})
        if not is_allowed_monarch_read_tool(tool_name):
            blocked = {
                "tool": tool_name,
                "status": "blocked",
                "reason": "monarch_read_only_allowlist",
                "argument_keys": sorted(args),
            }
            self.blocked_tool_calls.append(blocked)
            raise MonarchReadOnlyToolBlocked(f"Monarch tool is not read-allowlisted: {tool_name}")

        registry_name = self._registry_tool_name(tool_name)
        raw = self._dispatch(registry_name, args)
        parsed = _parse_dispatch_result(raw)
        self.read_tool_calls.append(
            {
                "tool": tool_name,
                "registry_tool": registry_name,
                "status": "ok",
                "argument_keys": sorted(args),
                "item_count": _estimate_item_count(parsed),
            }
        )
        return parsed

    def _dispatch(self, registry_name: str, args: dict[str, Any]) -> str:
        if self.dispatcher is not None:
            return self.dispatcher(registry_name, args)
        self._ensure_discovered()
        from tools.registry import registry

        entry = registry.get_entry(registry_name)
        if entry is None:
            raise RuntimeError(f"Monarch MCP tool was not registered: {registry_name}")
        return registry.dispatch(registry_name, args)

    def _ensure_discovered(self) -> None:
        if self._discovered:
            return
        discoverer = self.discoverer
        if discoverer is None:
            from tools.mcp_tool import discover_mcp_tools

            discoverer = discover_mcp_tools
        discoverer()
        self._discovered = True

    def _registry_tool_name(self, tool_name: str) -> str:
        try:
            from tools.mcp_tool import sanitize_mcp_name_component

            safe_server = sanitize_mcp_name_component(self.server_name)
        except Exception:
            safe_server = self.server_name.replace("-", "_")
        return f"mcp_{safe_server}_{tool_name}"


def is_allowed_monarch_read_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip() in ALLOWED_MONARCH_READ_TOOLS


def is_monarch_mutation_tool(tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    return any(name.startswith(prefix) for prefix in MONARCH_MUTATION_PREFIXES)


def collect_live_monarch_savings_packet(
    *,
    client: MonarchReadOnlyClient,
    loop: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect bounded live Monarch evidence through read-only MCP tools."""

    loop = _normalize_loop(loop)
    now_dt = _coerce_now(now)
    today = now_dt.date()
    month_start = today.replace(day=1)
    if loop == "daily":
        tx_start = today - timedelta(days=7)
        cash_start = today - timedelta(days=30)
        tx_limit = 100
    else:
        tx_start = today - timedelta(days=180)
        cash_start = today - timedelta(days=90)
        tx_limit = 200

    tool_results: dict[str, Any] = {}
    tool_errors: list[dict[str, Any]] = []

    def call(alias: str, tool: str, args: dict[str, Any]) -> None:
        try:
            tool_results[alias] = client.call_read_tool(tool, args)
        except Exception as exc:  # noqa: BLE001
            tool_errors.append({"alias": alias, "tool": tool, "error": f"{type(exc).__name__}: {str(exc)[:220]}"})

    call("recurring", "GetRecurring", {"include_liabilities": False, "include_pending": True})
    call(
        "transactions",
        "GetTransactions",
        {
            "start_date": tx_start.isoformat(),
            "end_date": today.isoformat(),
            "filters": json.dumps({"transaction_type": "All"}),
            "limit": tx_limit,
            "sort_by": "date",
            "include_details": False,
        },
    )
    call(
        "spending_current",
        "GetSpendingByCategory",
        {
            "start_date": month_start.isoformat(),
            "end_date": today.isoformat(),
            "totals_and_categories_only": True,
        },
    )
    call(
        "budget",
        "GetBudget",
        {"start_date": month_start.isoformat(), "end_date": today.isoformat(), "include_actuals": True},
    )
    call(
        "cash_flow",
        "GetCashFlow",
        {
            "start_date": cash_start.isoformat(),
            "end_date": today.isoformat(),
            "base_query": json.dumps({"group_by_time": "month", "group_by_entity": "category"}),
            "filters": json.dumps({"category_type": "expense"}),
        },
    )
    if loop == "weekly":
        call("merchants", "GetMerchants", {"limit": 200})

    return {
        "source": "monarch-money-mcp",
        "loop": loop,
        "generated_at": _iso(now_dt),
        "source_window": {
            "transactions_start_date": tx_start.isoformat(),
            "transactions_end_date": today.isoformat(),
            "cash_flow_start_date": cash_start.isoformat(),
            "budget_month_start": month_start.isoformat(),
        },
        "tool_results": tool_results,
        "tool_errors": tool_errors,
        "read_tool_calls": list(client.read_tool_calls),
        "blocked_tool_calls": list(client.blocked_tool_calls),
    }


def analyze_monarch_savings_packet(
    packet: dict[str, Any],
    *,
    loop: str,
    now: datetime | None = None,
    daily_large_charge_threshold: float = 250.0,
) -> list[dict[str, Any]]:
    """Return normalized savings/anomaly candidates from a redaction-safe packet."""

    loop = _normalize_loop(loop)
    now_dt = _coerce_now(now)
    tool_results = _dict(packet.get("tool_results"))
    recurring_rows = _records(packet.get("recurring") or tool_results.get("recurring"), _RECURRING_KEYS)
    transaction_rows = _records(packet.get("transactions") or tool_results.get("transactions"), _TRANSACTION_KEYS)
    current_categories = _records(
        packet.get("category_spend_current") or tool_results.get("spending_current"),
        _CATEGORY_KEYS,
    )
    baseline_categories = _records(packet.get("category_spend_baseline"), _CATEGORY_KEYS)
    budget_rows = _records(packet.get("budget") or tool_results.get("budget"), _BUDGET_KEYS)
    candidates: list[dict[str, Any]] = []

    candidates.extend(_recurring_candidates(recurring_rows, loop=loop, now=now_dt, packet=packet))
    candidates.extend(
        _price_increase_candidates(
            transaction_rows,
            loop=loop,
            now=now_dt,
            source_window=_dict(packet.get("source_window")),
        )
    )
    candidates.extend(_duplicate_charge_candidates(transaction_rows, loop=loop, now=now_dt, packet=packet))
    candidates.extend(
        _category_spike_candidates(
            current_categories=current_categories,
            baseline_categories=baseline_categories,
            budget_rows=budget_rows,
            loop=loop,
            packet=packet,
        )
    )
    if loop == "daily":
        candidates.extend(
            _unexpected_large_charge_candidates(
                transaction_rows,
                now=now_dt,
                amount_threshold=daily_large_charge_threshold,
                packet=packet,
            )
        )

    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        normalized = _normalize_candidate(candidate, loop=loop, packet=packet)
        existing = deduped.get(normalized["fingerprint"])
        if existing is None or normalized["score"] > existing["score"]:
            deduped[normalized["fingerprint"]] = normalized
    return sorted(deduped.values(), key=lambda item: (item["score"], item["estimated_annual_savings"]), reverse=True)


def build_torben_monarch_savings_payload(
    packet: dict[str, Any],
    *,
    loop: str,
    ledger: ActionLedger,
    state_path: str | Path,
    now: datetime | None = None,
    stage_actions: bool = True,
    force_wake: bool = False,
    max_items: int | None = None,
    min_score: int | None = None,
) -> dict[str, Any]:
    """Adapt Monarch savings candidates into stage-only FIN review handles."""

    loop = _normalize_loop(loop)
    now_dt = _coerce_now(now)
    state_file = Path(state_path)
    state = _load_state(state_file)
    delivered = _dict(state.get("delivered_candidates"))
    policy = load_torben_automation_policy()
    policy_decisions = finance_automation_decisions(policy=policy)
    threshold = min_score if min_score is not None else (DEFAULT_DAILY_MIN_SCORE if loop == "daily" else DEFAULT_WEEKLY_MIN_SCORE)
    cap = max_items if max_items is not None else (DEFAULT_DAILY_MAX_ITEMS if loop == "daily" else DEFAULT_WEEKLY_MAX_ITEMS)
    read_calls = _list(packet.get("read_tool_calls"))
    blocked_calls = _list(packet.get("blocked_tool_calls"))
    candidates = analyze_monarch_savings_packet(packet, loop=loop, now=now_dt)
    qualified = [
        candidate
        for candidate in candidates
        if int(candidate.get("score") or 0) >= threshold
        or float(candidate.get("estimated_monthly_savings") or 0) >= (25 if loop == "daily" else 0)
    ][:cap]
    fresh = [candidate for candidate in qualified if force_wake or candidate["fingerprint"] not in delivered]

    unsafe = _unsafe_monarch_counts(packet)
    base = {
        "task": f"torben_monarch_savings_{loop}",
        "loop": loop,
        "generated_at": _iso(now_dt),
        "source": str(packet.get("source") or "monarch-money-mcp"),
        "source_window": _dict(packet.get("source_window")),
        "policy": {
            "automation_policy": policy_decisions,
            "monarch_research": policy_decisions.get("monarch_research"),
            "monarch_mutation": policy_decisions.get("monarch_mutation"),
        },
        "policy_decision_present": bool(policy_decisions.get("monarch_research") and policy_decisions.get("monarch_mutation")),
        "redaction_status": "pass",
        "read_tool_calls": read_calls,
        "blocked_tool_calls": blocked_calls,
        "tool_errors": _list(packet.get("tool_errors")),
        "monarch_read_calls": len(read_calls),
        "monarch_write_calls": unsafe["monarch_write_calls"],
        "public_actions_taken": 0,
        "external_mutations": unsafe["external_mutations"],
        "candidate_count": len(candidates),
        "qualified_count": len(qualified),
        "selected_count": len(fresh),
        "suppressed_duplicate_count": max(0, len(qualified) - len(fresh)),
        "min_score": threshold,
        "recommendations_created": len(fresh),
        "estimated_monthly_savings": round(sum(_float(c.get("estimated_monthly_savings")) for c in fresh), 2),
        "estimated_annual_savings": round(sum(_float(c.get("estimated_annual_savings")) for c in fresh), 2),
    }

    if unsafe["monarch_write_calls"] or unsafe["external_mutations"]:
        return {
            **base,
            "wakeAgent": True,
            "status": "fail_closed",
            "reason": "monarch_savings_loop_reported_mutation",
            "candidates": [],
            "actions": [],
            "text": (
                f"Torben / Monarch Savings {loop.title()}\n\n"
                "Fail-closed: the Monarch savings loop reported a write or external mutation counter. "
                "I did not stage FIN review cards.\n"
            ),
        }

    actions: list[ActionRecord] = []
    if stage_actions:
        for rank, candidate in enumerate(fresh, start=1):
            actions.append(_stage_monarch_action(ledger=ledger, candidate=candidate, loop=loop, rank=rank, now=now_dt))
    else:
        actions = [
            _preview_monarch_action(candidate=candidate, loop=loop, rank=rank, now=now_dt)
            for rank, candidate in enumerate(fresh, start=1)
        ]

    if not fresh:
        reason = "no Monarch savings candidate reached the review threshold" if not qualified else "no fresh Monarch savings candidate after dedupe"
        return {
            **base,
            "wakeAgent": False,
            "reason": reason,
            "status": "quiet",
            "candidates": qualified,
            "actions": [],
            "text": "",
        }

    text = render_monarch_savings_text(candidates=fresh, actions=actions, loop=loop, now=now_dt, policy_decisions=policy_decisions)
    payload = {
        **base,
        "wakeAgent": True,
        "status": "review_ready",
        "reason": None,
        "candidates": fresh,
        "actions": [action.to_dict() for action in actions],
        "text": text,
    }
    if stage_actions:
        _mark_delivered(state_file, state, candidates=fresh, loop=loop, now=now_dt)
    return payload


def render_monarch_savings_text(
    *,
    candidates: list[dict[str, Any]],
    actions: list[ActionRecord],
    loop: str,
    now: datetime,
    policy_decisions: dict[str, Any],
) -> str:
    title = "Daily" if loop == "daily" else "Weekly"
    total_monthly = sum(_float(candidate.get("estimated_monthly_savings")) for candidate in candidates)
    total_annual = sum(_float(candidate.get("estimated_annual_savings")) for candidate in candidates)
    mutation_decision = _dict(policy_decisions.get("monarch_mutation"))
    lines = [
        f"Torben / Monarch Savings {title} / {now:%Y-%m-%d %H:%M UTC}",
        "",
        f"Found {len(candidates)} review item(s), about ${total_monthly:,.0f}/mo or ${total_annual:,.0f}/yr in possible savings or avoided spend.",
        "Read-only Monarch research. Nothing was changed in Monarch.",
        f"Monarch writes: {mutation_decision.get('decision') or 'blocked'}; {mutation_decision.get('reason') or 'fail closed'}.",
        "",
    ]
    for idx, (candidate, action) in enumerate(zip(candidates, actions), start=1):
        merchant = _compact(candidate.get("merchant"), "Unknown merchant")
        ctype = _compact(candidate.get("candidate_type"), "review")
        cadence = _compact(candidate.get("cadence"), "unknown cadence")
        amount = _float(candidate.get("amount"))
        annual = _float(candidate.get("annualized_cost"))
        why = _compact(candidate.get("why_it_matters"), "Review for savings.")
        rec = _compact(candidate.get("recommended_action"), "Review and decide.")
        lines.extend(
            [
                f"{idx}. {merchant}: {ctype.replace('_', ' ')}.",
                f"Amount/cadence: ${amount:,.2f} / {cadence}; annualized ${annual:,.0f}.",
                f"Why: {why}",
                f"Next: {rec}",
                f"[{action.handle}] {', '.join(action.allowed_next_actions[:3])}.",
                "",
            ]
        )
    lines.append("No account numbers, transaction IDs, rules, categories, goals, or Monarch records were written.")
    return "\n".join(lines).rstrip() + "\n"


def write_monarch_savings_artifacts(payload: dict[str, Any], *, json_path: str | Path, text_path: str | Path) -> None:
    json_output = Path(json_path)
    text_output = Path(text_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    text_output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(json_output, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _atomic_write(text_output, str(payload.get("text") or ""))


def update_monarch_savings_ledger(payload: dict[str, Any], *, ledger_path: str | Path) -> dict[str, Any]:
    path = Path(ledger_path)
    existing = _load_json(path) or {}
    opportunities = _dict(existing.get("opportunities"))
    now_text = str(payload.get("generated_at") or _iso(_coerce_now(None)))
    for candidate in _list(payload.get("candidates")):
        if not isinstance(candidate, dict):
            continue
        key = str(candidate.get("fingerprint") or "")
        if not key:
            continue
        current = _dict(opportunities.get(key))
        opportunities[key] = {
            **current,
            "fingerprint": key,
            "first_seen_at": current.get("first_seen_at") or now_text,
            "last_seen_at": now_text,
            "merchant": candidate.get("merchant"),
            "candidate_type": candidate.get("candidate_type"),
            "estimated_monthly_savings": candidate.get("estimated_monthly_savings"),
            "estimated_annual_savings": candidate.get("estimated_annual_savings"),
            "status": current.get("status") or "proposed",
            "mutation_status": "review_only",
            "monarch_write_allowed": False,
        }
    ledger = {
        "version": MONARCH_SAVINGS_STATE_VERSION,
        "updated_at": now_text,
        "source": "torben_monarch_savings",
        "opportunities": opportunities,
        "external_mutations": 0,
        "monarch_write_calls": 0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    return ledger


def _stage_monarch_action(
    *,
    ledger: ActionLedger,
    candidate: dict[str, Any],
    loop: str,
    rank: int,
    now: datetime,
) -> ActionRecord:
    merchant = _compact(candidate.get("merchant"), "Unknown merchant")
    ctype = _compact(candidate.get("candidate_type"), "review")
    aliases = _reply_aliases(loop=loop, candidate_type=ctype, rank=rank)
    return ledger.add_action(
        scope="FIN",
        summary=f"Review Monarch savings {loop} item {rank}: {merchant}",
        evidence_ids=[str(item) for item in candidate.get("evidence_refs") or []],
        allowed_next_actions=aliases[:3],
        status="staged",
        risk_class="medium",
        ttl_hours=168 if loop == "weekly" else 48,
        now=now,
        executor_state={
            "mutation_type": "monarch_savings_review",
            "mutation_status": "review_only",
            "provider": MONARCH_SERVER_NAME,
            "source": "torben_monarch_savings",
            "loop": loop,
            "candidate": candidate,
            "candidate_fingerprint": candidate.get("fingerprint"),
            "monarch_write_allowed": False,
            "monarch_mutation_tools_available": False,
            "monarch_write_calls": 0,
            "external_mutations": 0,
            "reply_actions": aliases[:3],
            "reply_aliases": aliases,
            "execution_blocked_until": [
                "explicit_signal_handle",
                "human_decision",
                "future_monarch_mutation_policy_enabled",
            ],
        },
    )


def _preview_monarch_action(*, candidate: dict[str, Any], loop: str, rank: int, now: datetime) -> ActionRecord:
    merchant = _compact(candidate.get("merchant"), "Unknown merchant")
    aliases = _reply_aliases(loop=loop, candidate_type=_compact(candidate.get("candidate_type"), "review"), rank=rank)
    return ActionRecord(
        handle=f"FIN-{now:%Y%m%d}-{rank:03d}",
        scope="fin",
        summary=f"Preview Monarch savings {loop} item {rank}: {merchant}",
        evidence_ids=[str(item) for item in candidate.get("evidence_refs") or []],
        allowed_next_actions=aliases[:3],
        status="staged",
        risk_class="medium",
        created_at=now,
        user_visible_summary=f"Preview Monarch savings {loop} item {rank}: {merchant}",
        executor_state={
            "mutation_type": "monarch_savings_review",
            "mutation_status": "preview_only",
            "provider": MONARCH_SERVER_NAME,
            "candidate": candidate,
            "monarch_write_allowed": False,
            "monarch_write_calls": 0,
            "external_mutations": 0,
        },
    )


def _reply_aliases(*, loop: str, candidate_type: str, rank: int) -> list[str]:
    if loop == "daily":
        if candidate_type in {"duplicate_charge", "unexpected_large_charge", "price_increase", "category_spike"}:
            return [f"review spend {rank}", f"ignore spend {rank}", f"snooze merchant {rank}"]
        return [f"review renewal {rank}", f"ignore renewal {rank}", f"snooze merchant {rank}"]
    if candidate_type in {"cancel_review", "duplicate_subscription"}:
        return [f"review cancel {rank}", f"mark keep {rank}", f"ask source {rank}"]
    return [f"review savings {rank}", f"mark keep {rank}", f"ask source {rank}"]


def _recurring_candidates(rows: list[dict[str, Any]], *, loop: str, now: datetime, packet: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        merchant = _merchant(row)
        if not merchant:
            continue
        amount = _money(row, "amount", "average_amount", "last_amount", "monthly_amount", "payment_amount")
        if amount <= 0:
            continue
        cadence = _cadence(row)
        annualized = _annualized(amount, cadence)
        text = " ".join(
            str(row.get(key) or "")
            for key in ("name", "merchant", "merchant_name", "category", "category_name", "type", "cadence")
        )
        looks_subscription = _looks_like_subscription(text) or annualized >= 180
        if not looks_subscription:
            continue
        candidate_type = "cancel_review"
        if _looks_like_license(text):
            candidate_type = "downgrade_review"
        elif annualized >= 1000:
            candidate_type = "renegotiate_review"
        if loop == "daily":
            next_date = _first_date(row, "next_date", "next_payment_date", "due_date", "date")
            if next_date and 0 <= (next_date - now.date()).days <= 14:
                candidate_type = "trial_or_renewal_watch"
            elif not bool(row.get("is_new") or row.get("is_pending") or row.get("include_pending")):
                continue
        score = 56 + min(24, int(annualized / 80))
        if candidate_type in {"renegotiate_review", "trial_or_renewal_watch"}:
            score += 8
        candidates.append(
            {
                "candidate_type": candidate_type,
                "merchant": merchant,
                "category": _category(row),
                "amount": amount,
                "cadence": cadence,
                "annualized_cost": annualized,
                "estimated_monthly_savings": round(_monthly_equivalent(amount, cadence), 2),
                "estimated_annual_savings": round(annualized, 2),
                "confidence": 0.72,
                "urgency": "high" if candidate_type == "trial_or_renewal_watch" else "medium",
                "score": min(95, score),
                "why_it_matters": f"{merchant} appears recurring and costs about ${annualized:,.0f}/yr.",
                "recommended_action": _recommended_recurring_action(candidate_type),
                "evidence_refs": [_evidence_ref("recurring", row)],
                "source_window": _dict(packet.get("source_window")),
            }
        )
    return candidates


def _price_increase_candidates(
    rows: list[dict[str, Any]],
    *,
    loop: str,
    now: datetime,
    source_window: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped = _transactions_by_merchant(rows)
    candidates = []
    recent_floor = now.date() - timedelta(days=14 if loop == "daily" else 45)
    for merchant, txs in grouped.items():
        dated = [tx for tx in txs if _tx_date(tx) is not None and _tx_amount(tx) > 0]
        dated.sort(key=lambda tx: _tx_date(tx) or date.min, reverse=True)
        if len(dated) < 2:
            continue
        latest = dated[0]
        latest_date = _tx_date(latest)
        if latest_date is None or latest_date < recent_floor:
            continue
        prior_amounts = [_tx_amount(tx) for tx in dated[1:6] if _tx_amount(tx) > 0]
        if not prior_amounts:
            continue
        baseline = statistics.median(prior_amounts)
        latest_amount = _tx_amount(latest)
        diff = latest_amount - baseline
        if baseline <= 0 or diff < 5 or latest_amount < baseline * 1.2:
            continue
        annualized = diff * 12
        candidates.append(
            {
                "candidate_type": "price_increase",
                "merchant": merchant,
                "category": _category(latest),
                "amount": latest_amount,
                "cadence": "monthly",
                "annualized_cost": latest_amount * 12,
                "estimated_monthly_savings": round(diff, 2),
                "estimated_annual_savings": round(annualized, 2),
                "confidence": 0.78,
                "urgency": "high" if loop == "daily" else "medium",
                "score": min(96, 70 + int(min(20, annualized / 25))),
                "why_it_matters": f"{merchant} rose from a ${baseline:,.2f} baseline to ${latest_amount:,.2f}.",
                "recommended_action": "Review whether the plan renewed, upgraded, or should be downgraded.",
                "evidence_refs": [_evidence_ref("transaction", latest), _hash_ref("baseline", merchant, f"{baseline:.2f}")],
                "source_window": source_window,
            }
        )
    return candidates


def _duplicate_charge_candidates(rows: list[dict[str, Any]], *, loop: str, now: datetime, packet: dict[str, Any]) -> list[dict[str, Any]]:
    grouped = _transactions_by_merchant(rows)
    candidates = []
    recent_floor = now.date() - timedelta(days=10 if loop == "daily" else 45)
    for merchant, txs in grouped.items():
        dated = [tx for tx in txs if _tx_date(tx) is not None and _tx_amount(tx) > 0]
        dated.sort(key=lambda tx: _tx_date(tx) or date.min, reverse=True)
        for idx, first in enumerate(dated):
            first_date = _tx_date(first)
            if first_date is None or first_date < recent_floor:
                continue
            first_amount = _tx_amount(first)
            for second in dated[idx + 1 : idx + 6]:
                second_date = _tx_date(second)
                if second_date is None:
                    continue
                if abs((first_date - second_date).days) > 3:
                    continue
                second_amount = _tx_amount(second)
                if abs(first_amount - second_amount) > max(1.0, first_amount * 0.03):
                    continue
                candidates.append(
                    {
                        "candidate_type": "duplicate_charge",
                        "merchant": merchant,
                        "category": _category(first),
                        "amount": first_amount,
                        "cadence": "one_time",
                        "annualized_cost": first_amount * 2,
                        "estimated_monthly_savings": round(first_amount, 2),
                        "estimated_annual_savings": round(first_amount, 2),
                        "confidence": 0.84,
                        "urgency": "high",
                        "score": min(98, 78 + int(min(16, first_amount / 25))),
                        "why_it_matters": f"{merchant} charged about ${first_amount:,.2f} twice within three days.",
                        "recommended_action": "Review for duplicate billing or a dispute.",
                        "evidence_refs": [_evidence_ref("transaction", first), _evidence_ref("transaction", second)],
                        "source_window": _dict(packet.get("source_window")),
                    }
                )
                break
            if any(c.get("merchant") == merchant and c.get("candidate_type") == "duplicate_charge" for c in candidates):
                break
    return candidates


def _category_spike_candidates(
    *,
    current_categories: list[dict[str, Any]],
    baseline_categories: list[dict[str, Any]],
    budget_rows: list[dict[str, Any]],
    loop: str,
    packet: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    baseline_by_category = {_category(row): _category_amount(row) for row in baseline_categories if _category(row)}
    budget_by_category = {_category(row): _budget_amount(row) for row in budget_rows if _category(row)}
    for row in current_categories:
        category = _category(row)
        if not category:
            continue
        current = _category_amount(row)
        if current <= 0:
            continue
        baseline = baseline_by_category.get(category, 0)
        budget = budget_by_category.get(category, 0)
        over_baseline = baseline > 0 and current >= baseline * 1.5 and (current - baseline) >= 50
        over_budget = budget > 0 and current >= budget * 1.25 and (current - budget) >= 50
        if not over_baseline and not over_budget:
            continue
        reference = baseline if over_baseline else budget
        diff = current - reference
        candidates.append(
            {
                "candidate_type": "category_spike",
                "merchant": category,
                "category": category,
                "amount": current,
                "cadence": "month_to_date",
                "annualized_cost": current * 12,
                "estimated_monthly_savings": round(max(0, diff), 2),
                "estimated_annual_savings": round(max(0, diff) * 12, 2),
                "confidence": 0.7,
                "urgency": "medium" if loop == "weekly" else "high",
                "score": min(94, 68 + int(min(22, diff / 25))),
                "why_it_matters": f"{category} is at ${current:,.2f}, above the ${reference:,.2f} comparison level.",
                "recommended_action": "Find the merchant driving the overrun and decide what to cut or cap.",
                "evidence_refs": [_evidence_ref("category", row), _hash_ref("category-reference", category, f"{reference:.2f}")],
                "source_window": _dict(packet.get("source_window")),
            }
        )
    return candidates


def _unexpected_large_charge_candidates(
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    amount_threshold: float,
    packet: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped = _transactions_by_merchant(rows)
    candidates = []
    recent_floor = now.date() - timedelta(days=7)
    for merchant, txs in grouped.items():
        historical_count = len([tx for tx in txs if _tx_amount(tx) > 0])
        for tx in txs:
            tx_date = _tx_date(tx)
            amount = _tx_amount(tx)
            if tx_date is None or tx_date < recent_floor or amount < amount_threshold:
                continue
            if historical_count > 2:
                continue
            candidates.append(
                {
                    "candidate_type": "unexpected_large_charge",
                    "merchant": merchant,
                    "category": _category(tx),
                    "amount": amount,
                    "cadence": "one_time",
                    "annualized_cost": amount,
                    "estimated_monthly_savings": round(amount, 2),
                    "estimated_annual_savings": round(amount, 2),
                    "confidence": 0.62,
                    "urgency": "high",
                    "score": min(92, 70 + int(min(18, amount / 50))),
                    "why_it_matters": f"{merchant} is a recent ${amount:,.2f} charge with weak recent history.",
                    "recommended_action": "Review whether this is expected, refundable, or should be disputed.",
                    "evidence_refs": [_evidence_ref("transaction", tx)],
                    "source_window": _dict(packet.get("source_window")),
                }
            )
            break
    return candidates


def _normalize_candidate(candidate: dict[str, Any], *, loop: str, packet: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "merchant": _compact(candidate.get("merchant"), "Unknown merchant"),
        "category": _compact(candidate.get("category"), "uncategorized"),
        "amount": round(_float(candidate.get("amount")), 2),
        "cadence": _compact(candidate.get("cadence"), "unknown"),
        "annualized_cost": round(_float(candidate.get("annualized_cost")), 2),
        "estimated_monthly_savings": round(_float(candidate.get("estimated_monthly_savings")), 2),
        "estimated_annual_savings": round(_float(candidate.get("estimated_annual_savings")), 2),
        "confidence": round(_float(candidate.get("confidence")), 2),
        "urgency": _compact(candidate.get("urgency"), "medium"),
        "candidate_type": _compact(candidate.get("candidate_type"), "review"),
        "why_it_matters": _compact(candidate.get("why_it_matters"), "Review for savings."),
        "recommended_action": _compact(candidate.get("recommended_action"), "Review and decide."),
        "evidence_refs": [str(ref) for ref in _list(candidate.get("evidence_refs"))[:8]],
        "source_window": _dict(candidate.get("source_window") or packet.get("source_window")),
        "mutation_status": "review_only",
        "monarch_write_allowed": False,
        "score": int(round(_float(candidate.get("score")))),
        "loop": loop,
    }
    normalized["fingerprint"] = _hash_ref(
        "monarch-savings",
        loop,
        normalized["candidate_type"],
        normalized["merchant"].lower(),
        f"{normalized['amount']:.2f}",
        ",".join(normalized["evidence_refs"]),
    )
    return normalized


def _parse_dispatch_result(raw: str) -> Any:
    try:
        wrapper = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"text": str(raw or "")}
    if isinstance(wrapper, dict) and wrapper.get("error"):
        raise RuntimeError(str(wrapper.get("error")))
    if isinstance(wrapper, dict) and "structuredContent" in wrapper and wrapper["structuredContent"] is not None:
        structured = wrapper["structuredContent"]
        if isinstance(structured, (dict, list)):
            return structured
    if isinstance(wrapper, dict) and "result" in wrapper:
        result = wrapper["result"]
        if isinstance(result, (dict, list)):
            return result
        if isinstance(result, str):
            text = result.strip()
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text[:8000], "raw_text_length": len(text)}
    return wrapper


_TRANSACTION_KEYS = ("transactions", "results", "items", "data", "records", "nodes")
_RECURRING_KEYS = ("recurring", "recurring_items", "subscriptions", "bills", "items", "results", "data", "records")
_CATEGORY_KEYS = ("categories", "spending", "category_spending", "items", "results", "data", "records")
_BUDGET_KEYS = ("budget", "budgets", "categories", "items", "results", "data", "records")


def _records(payload: Any, preferred_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _records(value, preferred_keys)
            if nested:
                return nested
    lists = [value for value in payload.values() if isinstance(value, list) and any(isinstance(item, dict) for item in value)]
    if not lists:
        return []
    best = max(lists, key=len)
    return [item for item in best if isinstance(item, dict)]


def _transactions_by_merchant(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        merchant = _merchant(row)
        if merchant:
            grouped.setdefault(merchant, []).append(row)
    return grouped


def _merchant(row: dict[str, Any]) -> str:
    for key in ("merchant_name", "merchant", "merchantDisplayName", "original_merchant_name", "name", "payee"):
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("display_name")
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _category(row: dict[str, Any]) -> str:
    for key in ("category_name", "category", "category_group", "group_name", "name"):
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("display_name")
        text = str(value or "").strip()
        if text:
            return text
    return "uncategorized"


def _tx_date(row: dict[str, Any]) -> date | None:
    return _first_date(row, "date", "posted_at", "authorized_at", "created_at")


def _first_date(row: dict[str, Any], *keys: str) -> date | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip().replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(text).date()
            except ValueError:
                try:
                    return date.fromisoformat(text[:10])
                except ValueError:
                    continue
    return None


def _tx_amount(row: dict[str, Any]) -> float:
    return _money(row, "amount", "signed_amount", "value")


def _money(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        amount = _float(row.get(key))
        if amount:
            return abs(amount)
    return 0.0


def _category_amount(row: dict[str, Any]) -> float:
    return _money(row, "amount", "total", "actual", "actual_amount", "spend", "spent")


def _budget_amount(row: dict[str, Any]) -> float:
    return _money(row, "budget", "budgeted", "budget_amount", "planned", "target")


def _cadence(row: dict[str, Any]) -> str:
    for key in ("cadence", "frequency", "period", "interval", "recurrence"):
        text = str(row.get(key) or "").strip().lower()
        if text:
            return text
    return "monthly"


def _annualized(amount: float, cadence: str) -> float:
    cadence = str(cadence or "").lower()
    if "year" in cadence or "annual" in cadence:
        return amount
    if "quarter" in cadence:
        return amount * 4
    if "biweekly" in cadence or "every 2 week" in cadence:
        return amount * 26
    if "week" in cadence:
        return amount * 52
    if "day" in cadence:
        return amount * 365
    return amount * 12


def _monthly_equivalent(amount: float, cadence: str) -> float:
    return _annualized(amount, cadence) / 12


def _looks_like_subscription(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "subscription",
        "license",
        "membership",
        "saas",
        "software",
        "cloud",
        "hosting",
        "app ",
        "gym",
        "stream",
        "storage",
        "renewal",
    )
    return any(marker in lowered for marker in markers)


def _looks_like_license(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("license", "software", "saas", "cloud", "hosting", "app "))


def _recommended_recurring_action(candidate_type: str) -> str:
    if candidate_type == "renegotiate_review":
        return "Check current usage and ask for a discount or annual-plan correction."
    if candidate_type == "downgrade_review":
        return "Check whether a lower tier or fewer seats covers current usage."
    if candidate_type == "trial_or_renewal_watch":
        return "Review before renewal and cancel or downgrade if it is not actively used."
    return "Review usage and decide whether to cancel, keep, or snooze."


def _unsafe_monarch_counts(packet: dict[str, Any]) -> dict[str, int]:
    blocked_calls = [
        call
        for call in _list(packet.get("blocked_tool_calls"))
        if isinstance(call, dict) and is_monarch_mutation_tool(str(call.get("tool") or ""))
    ]
    return {
        "monarch_write_calls": _int(packet.get("monarch_write_calls")),
        "external_mutations": _int(packet.get("external_mutations")),
        "blocked_mutation_tool_calls": len(blocked_calls),
    }


def _evidence_ref(kind: str, row: dict[str, Any]) -> str:
    material = {
        "id": row.get("id") or row.get("transaction_id") or row.get("recurring_id"),
        "merchant": _merchant(row),
        "category": _category(row),
        "date": str(_tx_date(row) or _first_date(row, "next_date", "due_date", "date") or ""),
        "amount": _tx_amount(row) or _money(row, "amount", "average_amount", "last_amount", "monthly_amount"),
    }
    return _hash_ref(kind, json.dumps(material, sort_keys=True, default=str))


def _hash_ref(*parts: Any) -> str:
    material = "\0".join(str(part or "") for part in parts)
    return "ref_" + sha256(material.encode("utf-8")).hexdigest()[:12]


def _candidate_state_key(candidate: dict[str, Any]) -> str:
    return str(candidate.get("fingerprint") or _hash_ref("candidate", json.dumps(candidate, sort_keys=True, default=str)))


def _mark_delivered(path: Path, state: dict[str, Any], *, candidates: list[dict[str, Any]], loop: str, now: datetime) -> None:
    delivered = _dict(state.get("delivered_candidates"))
    for candidate in candidates:
        delivered[_candidate_state_key(candidate)] = {
            "delivered_at": _iso(now),
            "loop": loop,
            "merchant": candidate.get("merchant"),
            "candidate_type": candidate.get("candidate_type"),
        }
    state.update({"version": MONARCH_SAVINGS_STATE_VERSION, "updated_at": _iso(now), "delivered_candidates": delivered})
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _load_state(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _normalize_loop(loop: str) -> str:
    value = str(loop or "").strip().lower()
    if value not in {"daily", "weekly"}:
        raise ValueError(f"Unsupported Monarch savings loop: {loop!r}")
    return value


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _estimate_item_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        records = _records(value, ("transactions", "items", "results", "data", "records", "categories"))
        return len(records)
    return 0


def _float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return float(text)
    except ValueError:
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback
