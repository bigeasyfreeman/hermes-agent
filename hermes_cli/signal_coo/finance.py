"""Finance worker for Torben's Signal COO operator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .action_ledger import ActionLedger, ActionRecord
from .automation_policy import finance_automation_decisions, load_torben_automation_policy
from .briefs import ScopeBrief

DEFAULT_FINANCE_MIN_SCORE = 0.70
DEFAULT_MAX_FINANCE_ITEMS = 2
FINANCE_QUALITY_GATE_VERSION = "finance_quality_gate_v1"
DEFAULT_OPPORTUNITY_UNIVERSE_VERSION = "torben_broad_opportunity_universe_v1"
DEFAULT_FINANCE_SCAN_WINDOWS = ("market_open", "midday", "late_afternoon")
DEFAULT_OPPORTUNITY_UNIVERSE_SCOPE = (
    "existing_holdings",
    "user_watchlist",
    "small_mid_cap_catalysts",
    "underfollowed_company_events",
    "sector_dislocations",
    "unusual_volume_news_deltas",
    "earnings_revenue_inflections",
    "product_or_technical_catalysts",
    "insider_or_institutional_flow_when_sourced",
)


def _compact(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


@dataclass(frozen=True)
class FinanceQualityGateResult:
    """Decision for whether a finance candidate is allowed to wake Eric."""

    passed: bool
    failed_criteria: list[str]
    silent_reason: str | None
    quality_gate_version: str = FINANCE_QUALITY_GATE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed_criteria": list(self.failed_criteria),
            "silent_reason": self.silent_reason,
            "quality_gate_version": self.quality_gate_version,
        }


class FinanceQualityGate:
    """Suppress no-data/generic finance radar candidates before Signal wake.

    The gate is intentionally conservative: a score above the review threshold
    is not enough. A visible `FIN-*` card needs evidence, a thesis, freshness,
    risk framing, and explicit stage-only guard status.
    """

    version = FINANCE_QUALITY_GATE_VERSION

    def evaluate_candidate(
        self,
        ratatosk_run: dict[str, Any],
        candidate: dict[str, Any],
    ) -> FinanceQualityGateResult:
        failed: list[str] = []

        if _run_is_no_live_market_data(ratatosk_run):
            failed.append("run_reports_no_live_market_data")
        if _run_is_data_source_degraded(ratatosk_run):
            failed.append("data_source_degraded")
        if not _has_market_packet(ratatosk_run, candidate):
            failed.append("missing_live_data_packet")
        if not _has_thesis(candidate):
            failed.append("missing_thesis")
        if not _evidence_refs(candidate):
            failed.append("missing_evidence_refs")
        if not _candidate_quote_timestamp(candidate):
            failed.append("missing_quote_timestamp")
        if not _data_freshness(candidate):
            failed.append("missing_data_freshness")
        if not _risk_notes(candidate):
            failed.append("missing_risk_notes")
        elif _risk_notes_are_only_no_data(_risk_notes(candidate)):
            failed.append("risk_notes_only_research_no_data")
        if bool(candidate.get("can_place_order_directly") or candidate.get("can_trade_directly")):
            failed.append("unsafe_direct_order_capability")

        # Surface schema: do not let a visible candidate omit decision-grade
        # fields. market_implied_probability is required when Ratatosk has it;
        # otherwise the adapter records an explicit unavailable value.
        if not _compact(candidate.get("proposed_action") or candidate.get("action") or candidate.get("direction"), ""):
            failed.append("missing_proposed_action")
        if candidate.get("edge") in (None, ""):
            failed.append("missing_edge")
        if candidate.get("conviction") in (None, "") and candidate.get("confidence") in (None, ""):
            failed.append("missing_conviction")
        if not _compact(candidate.get("invalidation_condition"), ""):
            failed.append("missing_invalidation_condition")
        if not _compact(candidate.get("recommended_review_action"), ""):
            failed.append("missing_recommended_review_action")
        if not isinstance(candidate.get("guard_result"), dict):
            failed.append("missing_guard_result")
        if _candidate_requires_historical_analogs(candidate) and not _list(candidate.get("historical_analogs")):
            failed.append("missing_historical_analogs")
        candidate_counts = _candidate_mutation_counters(candidate)
        for key, value in candidate_counts.items():
            if value > 0:
                failed.append(f"candidate_{key}_nonzero")

        failed = sorted(dict.fromkeys(failed))
        return FinanceQualityGateResult(
            passed=not failed,
            failed_criteria=failed,
            silent_reason=_quality_silent_reason(failed),
        )


class FinanceSlice:
    """Stage hard-limited trading and personal-finance proposals."""

    def __init__(self, ledger: ActionLedger):
        self.ledger = ledger

    def generate_brief(
        self,
        evidence: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> ScopeBrief:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        trade_signals = _list(evidence.get("trade_signals") or evidence.get("market_signals"))
        personal_finance = _list(evidence.get("personal_finance_signals") or evidence.get("monarch_signals"))

        if trade_signals:
            return self._trade_brief(_dict(trade_signals[0]), now=now)
        if personal_finance:
            return self._personal_finance_brief(_dict(personal_finance[0]), now=now)
        return ScopeBrief(
            scope="finance",
            title="Finance",
            status="quiet",
            priority="low",
            text="Finance: no trade or Monarch signal supplied. No capital is at risk.",
        )

    def _trade_brief(self, signal: dict[str, Any], *, now: datetime) -> ScopeBrief:
        catalyst = _compact(signal.get("catalyst") or signal.get("event"), "market catalyst")
        thesis = _compact(signal.get("thesis"), "the trade needs a clearer thesis before execution")
        expression = _compact(signal.get("expression") or signal.get("instrument"), "supported option or marginable equity")
        max_loss = _compact(signal.get("max_loss") or signal.get("premium") or signal.get("risk_cap"), "unset")
        exit_rule = _compact(signal.get("exit_rule"), "exit rule required before execution")
        expected_payoff = _compact(signal.get("expected_payoff"), "payoff model required before execution")
        evidence_ids = [str(item) for item in signal.get("evidence_ids") or []]

        action = self.ledger.add_action(
            scope="FIN",
            summary=f"Review live-trading setup: {expression}",
            evidence_ids=evidence_ids,
            allowed_next_actions=["revise", "approve_trade_review", "discard"],
            status="approval_required",
            risk_class="critical",
            now=now,
            executor_state={
                "mutation_type": "broker_order",
                "provider": "robinhood-agentic-mcp",
                "mutation_status": "review_only",
                "auth_required": True,
                "execution_blocked_until": [
                    "broker_auth",
                    "account_eligibility_check",
                    "risk_policy_limits",
                    "explicit_signal_approval",
                ],
                "requires_options_margin_review": True,
            },
        )

        lines = [
            "Finance: I staged a trade review, not an order.",
            "",
            f"Catalyst: {catalyst}.",
            f"Thesis: {thesis}.",
            f"Expression: {expression}.",
            f"Max loss: {max_loss}.",
            f"Expected payoff: {expected_payoff}.",
            f"Exit rule: {exit_rule}.",
            "",
            f"[{action.handle}] Approve trade review or ask for a smaller risk version.",
        ]
        return ScopeBrief(
            scope="finance",
            title="Finance",
            text="\n".join(lines),
            priority="high",
            actions=[action],
            evidence_ids=evidence_ids,
        )

    def _personal_finance_brief(self, signal: dict[str, Any], *, now: datetime) -> ScopeBrief:
        summary = _compact(signal.get("summary") or signal.get("opportunity"), "personal finance opportunity")
        recommendation = _compact(signal.get("recommendation"), "review the expense and decide whether to cut it")
        evidence_ids = [str(item) for item in signal.get("evidence_ids") or []]
        action = self.ledger.add_action(
            scope="FIN",
            summary=f"Review Monarch finance action: {summary}",
            evidence_ids=evidence_ids,
            allowed_next_actions=["revise", "approve_note", "discard"],
            status="staged",
            risk_class="medium",
            now=now,
            executor_state={
                "mutation_type": "monarch_review",
                "provider": "monarch-money-mcp",
                "mutation_status": "draft_only",
                "external_change_blocked_until": "explicit_signal_approval",
            },
        )
        lines = [
            "Finance: I found a Monarch action to review.",
            "",
            f"Signal: {summary}.",
            f"Recommendation: {recommendation}.",
            "",
            f"[{action.handle}] Review the finance action. Nothing is changed in Monarch.",
        ]
        return ScopeBrief(
            scope="finance",
            title="Finance",
            text="\n".join(lines),
            priority="normal",
            actions=[action],
            evidence_ids=evidence_ids,
        )


def build_torben_finance_radar_adapter(
    ratatosk_run: dict[str, Any],
    *,
    ledger: ActionLedger,
    state_path: str | Path,
    min_score: float = DEFAULT_FINANCE_MIN_SCORE,
    max_items: int = DEFAULT_MAX_FINANCE_ITEMS,
    now: datetime | None = None,
    mark_delivered: bool = True,
    stage_actions: bool = True,
    force_wake: bool = False,
) -> dict[str, Any]:
    """Adapt a Ratatosk Robinhood v0.1 run into Torben FIN actions.

    The Ratatosk run is research/staging evidence only. This adapter never
    places, cancels, modifies, or approves broker orders.
    """

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    policy = load_torben_automation_policy()
    policy_decisions = finance_automation_decisions(policy=policy)
    loop_context = _trading_loop_context(ratatosk_run)
    state_file = Path(state_path)
    state = _load_state(state_file)
    delivered = state.get("delivered_candidates") if isinstance(state.get("delivered_candidates"), dict) else {}
    candidates = _candidate_rows(ratatosk_run)
    quality_gate = FinanceQualityGate()
    scan_window = _scan_window(ratatosk_run, now)
    scan_windows = _scan_windows(ratatosk_run)
    opportunity_universe_version = _opportunity_universe_version(ratatosk_run)
    opportunity_universe_scope = _opportunity_universe_scope(ratatosk_run)
    candidate_class_counts = _candidate_class_counts(candidates)
    underfollowed_signal_count = _underfollowed_signal_count(candidates)
    quality_gate_results = {
        id(candidate): quality_gate.evaluate_candidate(ratatosk_run, candidate)
        for candidate in candidates
    }
    unsafe_counts = _unsafe_mutation_counts(ratatosk_run)
    if unsafe_counts["broker_orders_submitted"] > 0 or unsafe_counts["external_mutations"] > 0:
        return _unsafe_mutation_payload(
            ratatosk_run=ratatosk_run,
            candidates=candidates,
            counts=unsafe_counts,
            min_score=min_score,
            now=now,
            policy_decisions=policy_decisions,
        )
    selected = _select_candidate_rows(
        candidates,
        min_score=min_score,
        max_items=max_items,
        force_wake=force_wake,
        quality_gate_results=quality_gate_results,
    )
    for candidate in selected:
        gate_result = quality_gate_results.get(id(candidate))
        if gate_result:
            candidate["quality_gate"] = gate_result.to_dict()
    fresh = [candidate for candidate in selected if _candidate_key(ratatosk_run, candidate) not in delivered]

    if not fresh:
        failed_gate_results = [result for result in quality_gate_results.values() if not result.passed]
        failed_criteria = sorted({
            criterion
            for result in failed_gate_results
            for criterion in result.failed_criteria
        })
        silent_reason = _silent_reason(
            ratatosk_run=ratatosk_run,
            candidates=candidates,
            min_score=min_score,
            failed_criteria=failed_criteria,
        )
        payload = {
            "task": "torben_finance_radar",
            "wakeAgent": False,
            "generated_at": _iso(now),
            "reason": silent_reason,
            "silent_reason": silent_reason,
            "quality_gate_version": quality_gate.version,
            "quality_gate_failed_criteria": failed_criteria,
            "suppressed_candidates": [
                {
                    "symbol": candidate.get("symbol") or candidate.get("market_id"),
                    "score": _score(candidate),
                    "quality_gate": quality_gate_results[id(candidate)].to_dict(),
                }
                for candidate in candidates
                if id(candidate) in quality_gate_results and not quality_gate_results[id(candidate)].passed
            ],
            "ratatosk_status": ratatosk_run.get("status"),
            "ratatosk_phase": ratatosk_run.get("phase"),
            "ratatosk_run_id": _ratatosk_run_id(ratatosk_run),
            "candidate_count": len(candidates),
            "selected_count": 0,
            "suppressed_duplicate_count": len(selected),
            "min_score": min_score,
            "scan_window": scan_window,
            "scan_windows": scan_windows,
            "scan_windows_count": len(scan_windows),
            "opportunity_universe_version": opportunity_universe_version,
            "opportunity_universe_scope": opportunity_universe_scope,
            "candidate_class_counts": candidate_class_counts,
            "underfollowed_signal_count": underfollowed_signal_count,
            "llm_triggered": False,
            "quiet_scan_llm_triggered": False,
            "llm_trigger_reason": None,
            "no_llm_reason": "quiet scan produced no fresh decision-grade candidate",
            "market_regime": _llm_result(ratatosk_run).get("market_regime"),
            "no_trade_reason": _llm_result(ratatosk_run).get("no_trade_reason"),
            "llm_judge": _llm_audit(ratatosk_run),
            "loop_heartbeat": loop_context["heartbeat"],
            **_stop_condition_payload_fields(loop_context),
            "scan_candidate_supply": loop_context["scan_candidate_supply"],
            "paper_outcome": loop_context["paper_outcome"],
            "sample_collector": loop_context["sample_collector"],
            "paper_performance": loop_context["paper_performance"],
            "historical_verifier": loop_context["historical_verifier"],
            "signal_optimizer": loop_context["signal_optimizer"],
            "experiment_evaluation": loop_context["experiment_evaluation"],
            "active_experiment_sample_window": loop_context["active_experiment_sample_window"],
            "candidate_selection_policy": loop_context["candidate_selection_policy"],
            "sample_acquisition_plan": loop_context["sample_acquisition_plan"],
            "live_status": loop_context["live_status"],
            "risk_incident": loop_context["risk_incident"],
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": int(ratatosk_run.get("orders_submitted") or 0),
            "broker_orders_submitted": int(ratatosk_run.get("orders_submitted") or 0),
            "automation_policy": policy_decisions,
            "auto_invoke_allowed": bool((policy_decisions.get("research") or {}).get("auto_invoke_allowed")),
            "recommendation_status": (
                "auto_surface_allowed"
                if (policy_decisions.get("research") or {}).get("recommendation_allowed")
                else "auto_surface_blocked"
            ),
            "text": "",
        }
        return payload

    actions = [
        _stage_finance_action(
            ledger=ledger,
            ratatosk_run=ratatosk_run,
            candidate=candidate,
            rank=rank,
            now=now,
            min_score=min_score,
            loop_context=loop_context,
        )
        if stage_actions
        else _preview_finance_action(
            ratatosk_run=ratatosk_run,
            candidate=candidate,
            rank=rank,
            now=now,
            min_score=min_score,
            loop_context=loop_context,
        )
        for rank, candidate in enumerate(fresh, start=1)
    ]
    text = render_torben_finance_radar_text(
        ratatosk_run=ratatosk_run,
        candidates=fresh,
        actions=actions,
        min_score=min_score,
        now=now,
        policy_decisions=policy_decisions,
        loop_context=loop_context,
    )
    payload = {
        "task": "torben_finance_radar",
        "wakeAgent": True,
        "generated_at": _iso(now),
        "ratatosk_status": ratatosk_run.get("status"),
        "ratatosk_phase": ratatosk_run.get("phase"),
        "ratatosk_run_id": _ratatosk_run_id(ratatosk_run),
        "candidate_count": len(candidates),
        "selected_count": len(fresh),
        "suppressed_duplicate_count": max(0, len(selected) - len(fresh)),
        "min_score": min_score,
        "scan_window": scan_window,
        "scan_windows": scan_windows,
        "scan_windows_count": len(scan_windows),
        "opportunity_universe_version": opportunity_universe_version,
        "opportunity_universe_scope": opportunity_universe_scope,
        "candidate_class_counts": candidate_class_counts,
        "underfollowed_signal_count": _underfollowed_signal_count(fresh),
        "llm_triggered": _llm_result(ratatosk_run) != {},
        "quiet_scan_llm_triggered": False,
        "llm_trigger_reason": "decision-grade finance candidate crossed quality gate",
        "no_llm_reason": None,
        "quality_gate_version": quality_gate.version,
        "quality_gate_failed_criteria": [],
        "market_regime": _llm_result(ratatosk_run).get("market_regime"),
        "no_trade_reason": _llm_result(ratatosk_run).get("no_trade_reason"),
        "candidates": fresh,
        "actions": [action.to_dict() for action in actions],
        "llm_judge": _llm_audit(ratatosk_run),
        "loop_heartbeat": loop_context["heartbeat"],
        **_stop_condition_payload_fields(loop_context),
        "scan_candidate_supply": loop_context["scan_candidate_supply"],
        "paper_outcome": loop_context["paper_outcome"],
        "sample_collector": loop_context["sample_collector"],
        "paper_performance": loop_context["paper_performance"],
        "historical_verifier": loop_context["historical_verifier"],
        "signal_optimizer": loop_context["signal_optimizer"],
        "experiment_evaluation": loop_context["experiment_evaluation"],
        "active_experiment_sample_window": loop_context["active_experiment_sample_window"],
        "candidate_selection_policy": loop_context["candidate_selection_policy"],
        "sample_acquisition_plan": loop_context["sample_acquisition_plan"],
        "live_status": loop_context["live_status"],
        "risk_incident": loop_context["risk_incident"],
        "automation_policy": policy_decisions,
        "auto_invoke_allowed": bool((policy_decisions.get("research") or {}).get("auto_invoke_allowed")),
        "recommendation_status": (
            "auto_surface_allowed"
            if (policy_decisions.get("research") or {}).get("recommendation_allowed")
            else "auto_surface_blocked"
        ),
        "text": text,
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": int(ratatosk_run.get("orders_submitted") or 0),
        "broker_orders_submitted": int(ratatosk_run.get("orders_submitted") or 0),
        "delivery": {
            "surface": "signal",
            "operator": "torben",
            "source": "ratatosk_robinhood_v01",
            "delivery_mode": "adapter_text",
        },
    }
    if mark_delivered and stage_actions:
        _mark_delivered(state_file, state, ratatosk_run=ratatosk_run, candidates=fresh, now=now)
    return payload


def render_torben_finance_radar_text(
    *,
    ratatosk_run: dict[str, Any],
    candidates: list[dict[str, Any]],
    actions: list[ActionRecord],
    min_score: float,
    now: datetime,
    policy_decisions: dict[str, Any] | None = None,
    loop_context: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"Torben / Finance Radar / {now:%Y-%m-%d %H:%M UTC}",
        "",
        f"Ratatosk ran {_ratatosk_source_label(ratatosk_run)} and found "
        f"{len(candidates)} candidate(s) above the {min_score:.2f} review bar.",
        f"Scan window: {_scan_window(ratatosk_run, now)}. "
        f"Universe: {_opportunity_universe_version(ratatosk_run)}.",
        "Universe scope: broad opportunity radar; not limited to existing holdings or blue-chip names.",
        "This is a stage-only finance review. No order was placed, cancelled, modified, or approved.",
        "Research can create candidates; it cannot trade directly.",
        _finance_automation_line(policy_decisions),
        "",
    ]
    loop_lines = _trading_loop_text_lines(loop_context or {})
    if loop_lines:
        lines.extend(loop_lines)
        lines.append("")
    regime = _compact(_llm_result(ratatosk_run).get("market_regime"), "")
    if regime:
        lines.append(f"Market read: {regime}.")
    no_trade_reason = _compact(_llm_result(ratatosk_run).get("no_trade_reason"), "")
    if no_trade_reason:
        lines.append(f"Guard note: {no_trade_reason}")
    if regime or no_trade_reason:
        lines.append("")

    for idx, (candidate, action) in enumerate(zip(candidates, actions), start=1):
        symbol = _compact(candidate.get("symbol"), "unknown")
        score = _score(candidate)
        instrument = _compact(candidate.get("instrument_type") or candidate.get("asset_class"), "instrument")
        direction = _compact(candidate.get("proposed_action") or candidate.get("action") or candidate.get("direction"), "review")
        note = _compact(candidate.get("thesis") or candidate.get("research_note"), "Thesis required before review.")
        edge = _compact(candidate.get("edge"), "unavailable")
        conviction = _compact(candidate.get("conviction") or candidate.get("confidence"), "unavailable")
        market_implied = _compact(candidate.get("market_implied_probability"), "unavailable")
        quote_timestamp = _compact(candidate.get("quote_timestamp"), "unavailable")
        freshness = _compact(candidate.get("data_freshness"), "unavailable")
        refs = _evidence_refs(candidate)
        risks = _risk_notes(candidate)
        invalidation = _compact(candidate.get("invalidation_condition"), "not supplied")
        review_action = _compact(candidate.get("recommended_review_action"), "review or hold")
        opportunity_class = _opportunity_class(candidate)
        underfollowed = _compact(
            candidate.get("why_underfollowed")
            or candidate.get("underfollowed_signal")
            or candidate.get("discovery_rationale"),
            "",
        )
        guard = _dict(candidate.get("guard_result"))
        guard_status = _compact(guard.get("status") or guard.get("decision"), "stage_only")
        constraints = [str(item) for item in candidate.get("constraints") or [] if str(item).strip()]
        lines.extend(
            [
                f"{idx}. {symbol} {direction} {instrument} candidate, score {score:.2f}.",
                f"Opportunity class: {opportunity_class}.",
                f"Why: {note}",
                f"Edge/conviction: {edge} / {conviction}. Market-implied probability: {market_implied}.",
                f"Quote/data freshness: {quote_timestamp} / {freshness}.",
                f"Evidence refs: {', '.join(refs[:8])}.",
                f"Risk notes: {', '.join(risks[:5])}.",
                f"Invalidation: {invalidation}.",
                f"Recommended review action: {review_action}. Guard: {guard_status}.",
            ]
        )
        if underfollowed:
            lines.append(f"Why it may be underfollowed: {underfollowed}.")
        if constraints:
            lines.append(f"Constraints: {', '.join(constraints[:8])}.")
        lines.append(f"[{action.handle}] Review the thesis, ask for a smaller-risk version, or hold.")
        lines.append("")
    lines.append("Live trading remains blocked until the finance mandate, consent, kill switch, and guard all pass.")
    return "\n".join(lines).rstrip() + "\n"


def write_finance_radar_artifacts(
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


def _stage_finance_action(
    *,
    ledger: ActionLedger,
    ratatosk_run: dict[str, Any],
    candidate: dict[str, Any],
    rank: int,
    now: datetime,
    min_score: float,
    loop_context: dict[str, Any],
) -> ActionRecord:
    symbol = _compact(candidate.get("symbol"), "unknown")
    score = _score(candidate)
    evidence_ids = [_ratatosk_run_id(ratatosk_run), _candidate_key(ratatosk_run, candidate)]
    source_refs = [str(item) for item in candidate.get("source_refs") or [] if str(item).strip()]
    evidence_ids.extend(source_refs[:5])
    provider = _compact(ratatosk_run.get("source") or ratatosk_run.get("task"), "ratatosk_equity_scan")
    label = _ratatosk_candidate_label(ratatosk_run)
    return ledger.add_action(
        scope="FIN",
        summary=f"Review Ratatosk {label} candidate {rank}: {symbol} score {score:.2f}",
        evidence_ids=evidence_ids,
        allowed_next_actions=["review_thesis", "smaller_risk", "hold"],
        status="staged",
        risk_class="critical",
        ttl_hours=18,
        now=now,
        executor_state={
            "mutation_type": "broker_order_candidate",
            "mutation_status": "stage_only_not_ordered",
            "provider": provider,
            "source": provider,
            "ratatosk_run_id": _ratatosk_run_id(ratatosk_run),
            "ratatosk_phase": ratatosk_run.get("phase"),
            "radar_rank": rank,
            "candidate_fingerprint": _candidate_key(ratatosk_run, candidate),
            "candidate": candidate,
            "llm_judged": _llm_result(ratatosk_run) != {},
            "llm_score": score,
            "min_score": min_score,
            "can_place_order_directly": bool(candidate.get("can_place_order_directly")),
            "research_signal_can_trade_directly": False,
            "order_tools_available": False,
            "orders_submitted": int(ratatosk_run.get("orders_submitted") or 0),
            "external_mutations": int(ratatosk_run.get("external_mutations") or 0),
            "execution_blocked_until": [
                "TBC-DECIDE-LIVE-FINANCE",
                "written_mandate",
                "human_consent",
                "kill_switch_allows",
                "pre_trade_guard_passes",
                "reconciliation_canary_passes",
            ],
            "reply_actions": ["review", "smaller_risk", "hold"],
            "reply_aliases": [f"review finance {rank}", f"smaller risk {rank}", f"hold finance {rank}"],
            "trading_loop": loop_context,
        },
    )


def _preview_finance_action(
    *,
    ratatosk_run: dict[str, Any],
    candidate: dict[str, Any],
    rank: int,
    now: datetime,
    min_score: float,
    loop_context: dict[str, Any],
) -> ActionRecord:
    symbol = _compact(candidate.get("symbol"), "unknown")
    score = _score(candidate)
    provider = _compact(ratatosk_run.get("source") or ratatosk_run.get("task"), "ratatosk_equity_scan")
    label = _ratatosk_candidate_label(ratatosk_run)
    return ActionRecord(
        handle=f"FIN-{now:%Y%m%d}-{rank:03d}",
        scope="fin",
        summary=f"Preview Ratatosk {label} candidate {rank}: {symbol} score {score:.2f}",
        evidence_ids=[_ratatosk_run_id(ratatosk_run), _candidate_key(ratatosk_run, candidate)],
        allowed_next_actions=["review_thesis", "smaller_risk", "hold"],
        status="staged",
        risk_class="critical",
        created_at=now,
        user_visible_summary=f"Preview Ratatosk {label} candidate {rank}: {symbol} score {score:.2f}",
        executor_state={
            "mutation_type": "broker_order_candidate",
            "mutation_status": "preview_only_not_ordered",
            "provider": provider,
            "candidate": candidate,
            "llm_score": score,
            "min_score": min_score,
            "can_place_order_directly": bool(candidate.get("can_place_order_directly")),
            "research_signal_can_trade_directly": False,
            "order_tools_available": False,
            "orders_submitted": int(ratatosk_run.get("orders_submitted") or 0),
            "external_mutations": int(ratatosk_run.get("external_mutations") or 0),
            "execution_blocked_until": [
                "TBC-DECIDE-LIVE-FINANCE",
                "written_mandate",
                "human_consent",
                "kill_switch_allows",
                "pre_trade_guard_passes",
                "reconciliation_canary_passes",
            ],
            "trading_loop": loop_context,
        },
    )


def _llm_result(ratatosk_run: dict[str, Any]) -> dict[str, Any]:
    value = ratatosk_run.get("llm_result")
    return value if isinstance(value, dict) else {}


def _candidate_rows(ratatosk_run: dict[str, Any]) -> list[dict[str, Any]]:
    if _is_research_agent_run(ratatosk_run):
        rows = ratatosk_run.get("candidates")
        if not isinstance(rows, list) or not rows:
            packet = ratatosk_run.get("research_signal_packet")
            rows = [packet] if isinstance(packet, dict) and packet.get("status") == "qa_passed" else []
        return [_normalize_candidate_row(row, ratatosk_run) for row in rows if isinstance(row, dict)]

    result = _llm_result(ratatosk_run)
    rows = result.get("candidates")
    if not isinstance(rows, list):
        rows = ratatosk_run.get("candidates")
    if not isinstance(rows, list):
        rows = ratatosk_run.get("signals")
    if not isinstance(rows, list):
        return []
    return [_normalize_candidate_row(row, ratatosk_run) for row in rows if isinstance(row, dict)]


def _normalize_candidate_row(row: dict[str, Any], ratatosk_run: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(row)
    symbol = _compact(candidate.get("symbol") or candidate.get("market_id") or candidate.get("primary_symbol"), "")
    if symbol:
        candidate.setdefault("symbol", symbol)
        candidate.setdefault("market_id", symbol)
    market = _candidate_market_packet(candidate) or _market_packet_for_symbol(ratatosk_run, symbol)
    if market:
        for source_key, target_key in (
            ("price", "market_price"),
            ("bid", "bid"),
            ("ask", "ask"),
            ("volume", "volume"),
            ("quote_timestamp", "quote_timestamp"),
            ("data_freshness", "data_freshness"),
        ):
            if candidate.get(target_key) in (None, "") and market.get(source_key) not in (None, ""):
                candidate[target_key] = market.get(source_key)
    scan_timestamp = ratatosk_run.get("scan_timestamp") or ratatosk_run.get("generated_at")
    if candidate.get("quote_timestamp") in (None, "") and market and scan_timestamp:
        candidate["quote_timestamp"] = scan_timestamp
    if candidate.get("data_freshness") in (None, ""):
        source_freshness = _dict(ratatosk_run.get("source_freshness"))
        freshness = source_freshness.get("status") or ratatosk_run.get("data_freshness")
        if freshness:
            candidate["data_freshness"] = freshness
    if candidate.get("score") in (None, ""):
        candidate["score"] = candidate.get("confidence") or candidate.get("conviction") or 0
    if candidate.get("proposed_action") in (None, ""):
        candidate["proposed_action"] = candidate.get("action") or candidate.get("direction")
    if candidate.get("opportunity_class") in (None, ""):
        candidate["opportunity_class"] = _derive_opportunity_class(candidate)
    expression = candidate.get("execution_expression") if isinstance(candidate.get("execution_expression"), dict) else {}
    if candidate.get("instrument_type") in (None, "") and expression.get("instrument_type") not in (None, ""):
        candidate["instrument_type"] = expression.get("instrument_type")
    if candidate.get("thesis") in (None, "") and candidate.get("research_note"):
        candidate["thesis"] = candidate.get("research_note")
    if candidate.get("research_note") in (None, "") and candidate.get("thesis"):
        candidate["research_note"] = candidate.get("thesis")
    if candidate.get("market_implied_probability") in (None, ""):
        candidate["market_implied_probability"] = candidate.get("yes_price") or candidate.get("market_price_probability") or "unavailable"
    if not _list(candidate.get("source_refs")):
        refs: list[Any] = []
        for key in ("source_refs", "evidence_refs", "catalyst_refs", "news_refs", "earnings_refs"):
            refs.extend(_list(candidate.get(key)))
        refs.extend(_event_refs_as_sources(candidate))
        refs.extend(_historical_analog_refs(candidate))
        if ratatosk_run.get("scan_timestamp"):
            refs.append(f"ratatosk-equity-scan:{ratatosk_run.get('scan_timestamp')}")
        if ratatosk_run.get("episode_id"):
            refs.append(f"research-episode:{ratatosk_run.get('episode_id')}")
        if refs:
            candidate["source_refs"] = [str(item) for item in refs if str(item).strip()]
    if candidate.get("guard_result") is None:
        candidate["guard_result"] = {
            "status": "stage_only_blocked",
            "external_mutations": int(ratatosk_run.get("external_mutations") or 0),
            "orders_submitted": int(ratatosk_run.get("orders_submitted") or 0),
            "broker_orders_submitted": int(ratatosk_run.get("broker_orders_submitted") or ratatosk_run.get("orders_submitted") or 0),
        }
    return candidate


def _scan_window(ratatosk_run: dict[str, Any], now: datetime | None = None) -> str:
    for key in ("scan_window", "market_window", "phase"):
        value = str(ratatosk_run.get(key) or "").strip()
        if value:
            return value
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hour = current.hour
    if 13 <= hour < 15:
        return "market_open"
    if 15 <= hour < 18:
        return "midday"
    if 18 <= hour < 21:
        return "late_afternoon"
    return "off_hours"


def _scan_windows(ratatosk_run: dict[str, Any]) -> list[str]:
    values = ratatosk_run.get("scan_windows")
    if isinstance(values, list):
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if cleaned:
            return cleaned
    return list(DEFAULT_FINANCE_SCAN_WINDOWS)


def _opportunity_universe_version(ratatosk_run: dict[str, Any]) -> str:
    return _compact(
        ratatosk_run.get("opportunity_universe_version")
        or ratatosk_run.get("universe_version")
        or ratatosk_run.get("watchlist_version"),
        DEFAULT_OPPORTUNITY_UNIVERSE_VERSION,
    )


def _opportunity_universe_scope(ratatosk_run: dict[str, Any]) -> list[str]:
    values = ratatosk_run.get("opportunity_universe_scope") or ratatosk_run.get("universe_scope")
    if isinstance(values, list):
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if cleaned:
            return cleaned
    return list(DEFAULT_OPPORTUNITY_UNIVERSE_SCOPE)


def _opportunity_class(candidate: dict[str, Any]) -> str:
    return _compact(candidate.get("opportunity_class") or _derive_opportunity_class(candidate), "uncategorized")


def _derive_opportunity_class(candidate: dict[str, Any]) -> str:
    for key in ("signal_family", "candidate_type", "thesis_type", "event_type"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    symbol = str(candidate.get("symbol") or "").upper()
    if symbol in {"SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLE"}:
        return "index_or_sector_context"
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("thesis", "research_note", "proposed_action", "recommended_review_action")
    ).lower()
    if "earnings" in text or "revenue" in text:
        return "earnings_revenue_inflection"
    if "volume" in text or "unusual" in text:
        return "unusual_volume_news_delta"
    if "product" in text or "technical" in text:
        return "product_or_technical_catalyst"
    if "underfollowed" in text or "small cap" in text or "mid cap" in text:
        return "underfollowed_company_catalyst"
    return "company_event"


def _candidate_class_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        klass = _opportunity_class(candidate)
        counts[klass] = counts.get(klass, 0) + 1
    return dict(sorted(counts.items()))


def _underfollowed_signal_count(candidates: list[dict[str, Any]]) -> int:
    count = 0
    for candidate in candidates:
        text = " ".join(
            str(candidate.get(key) or "")
            for key in (
                "opportunity_class",
                "signal_family",
                "candidate_type",
                "why_underfollowed",
                "underfollowed_signal",
                "discovery_rationale",
                "thesis",
                "research_note",
            )
        ).lower()
        if any(marker in text for marker in ("underfollowed", "small_cap", "small cap", "mid_cap", "mid cap", "dislocation")):
            count += 1
    return count


def _market_packet_for_symbol(ratatosk_run: dict[str, Any], symbol: str) -> dict[str, Any]:
    if not symbol:
        return {}
    packet = ratatosk_run.get("research_signal_packet")
    if isinstance(packet, dict) and str(packet.get("primary_symbol") or "").upper() == symbol.upper():
        market_packet = _candidate_market_packet(packet)
        if market_packet:
            return market_packet
    for market in _list(ratatosk_run.get("markets")):
        if not isinstance(market, dict):
            continue
        market_symbol = str(market.get("symbol") or market.get("market_id") or "").upper()
        if market_symbol == symbol.upper():
            return market
    return {}


def _select_candidate_rows(
    candidates: list[dict[str, Any]],
    *,
    min_score: float,
    max_items: int,
    force_wake: bool,
    quality_gate_results: dict[int, FinanceQualityGateResult],
) -> list[dict[str, Any]]:
    sorted_rows = sorted(candidates, key=_score, reverse=True)
    selected = []
    for candidate in sorted_rows:
        if _score(candidate) < min_score:
            continue
        gate_result = quality_gate_results.get(id(candidate))
        if gate_result is not None and not gate_result.passed:
            continue
        if bool(candidate.get("can_place_order_directly")):
            continue
        selected.append(candidate)
        if len(selected) >= max_items:
            break
    return selected


def _score(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("score") or candidate.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0


def _run_is_no_live_market_data(ratatosk_run: dict[str, Any]) -> bool:
    result = _llm_result(ratatosk_run)
    values = [
        ratatosk_run.get("status"),
        ratatosk_run.get("data_freshness"),
        ratatosk_run.get("evidence_mode"),
        result.get("market_regime"),
        result.get("no_trade_reason"),
        _dict(ratatosk_run.get("source_freshness")).get("status"),
    ]
    text = " ".join(str(value or "").lower() for value in values)
    return any(
        marker in text
        for marker in (
            "unknown_research_only_no_live_market_data",
            "preview_canary_no_live_market_data",
            "no live market data",
            "no-live-data",
            "placeholder analysis",
        )
    )


def _run_is_data_source_degraded(ratatosk_run: dict[str, Any]) -> bool:
    status = str(ratatosk_run.get("status") or "").lower()
    if status in {"data_source_degraded", "auth_failed", "degraded"}:
        return True
    source = _dict(ratatosk_run.get("source_freshness"))
    source_status = str(source.get("status") or "").lower()
    if source_status in {"auth_failed", "data_source_degraded", "degraded", "error"}:
        return True
    errors = _list(ratatosk_run.get("errors"))
    return any("auth" in str(error).lower() or "data source" in str(error).lower() for error in errors)


def _has_market_packet(ratatosk_run: dict[str, Any], candidate: dict[str, Any]) -> bool:
    freshness = _data_freshness(candidate)
    quote_timestamp = _candidate_quote_timestamp(candidate)
    if not freshness or not quote_timestamp:
        return False
    freshness_text = str(freshness).lower()
    if any(marker in freshness_text for marker in ("no_live", "no-live", "unknown", "placeholder", "stale")):
        return False
    has_price = any(candidate.get(key) not in (None, "") for key in ("market_price", "price", "bid", "ask"))
    symbol = _compact(candidate.get("symbol") or candidate.get("market_id"), "")
    has_market = bool(_market_packet_for_symbol(ratatosk_run, symbol))
    has_nested_market = bool(_candidate_market_packet(candidate))
    return (
        has_price
        or has_market
        or has_nested_market
        or str(ratatosk_run.get("evidence_mode") or "").lower() == "fixture_equivalent"
    )


def _has_thesis(candidate: dict[str, Any]) -> bool:
    thesis = _compact(candidate.get("thesis") or candidate.get("research_note"), "")
    if not thesis:
        return False
    return thesis.lower() not in {
        "no thesis provided",
        "no thesis provided.",
        "thesis required before review",
        "unknown",
    }


def _candidate_quote_timestamp(candidate: dict[str, Any]) -> str:
    return _compact(candidate.get("quote_timestamp") or candidate.get("market_data_timestamp"), "")


def _data_freshness(candidate: dict[str, Any]) -> str:
    return _compact(candidate.get("data_freshness") or candidate.get("freshness"), "")


def _evidence_refs(candidate: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("source_refs", "evidence_refs", "catalyst_refs", "news_refs", "earnings_refs"):
        refs.extend(str(item).strip() for item in _list(candidate.get(key)) if str(item).strip())
    refs.extend(_event_refs_as_sources(candidate))
    refs.extend(_historical_analog_refs(candidate))
    return list(dict.fromkeys(refs))


def _is_research_agent_run(ratatosk_run: dict[str, Any]) -> bool:
    return str(ratatosk_run.get("source") or "") == "ratatosk_equity_research_agent_v1"


def _candidate_market_packet(candidate: dict[str, Any]) -> dict[str, Any]:
    packet = candidate.get("market_packet")
    return packet if isinstance(packet, dict) else {}


def _candidate_requires_historical_analogs(candidate: dict[str, Any]) -> bool:
    action = str(candidate.get("proposed_action") or candidate.get("action") or candidate.get("direction") or "").lower()
    family = str(candidate.get("signal_family") or "").lower()
    return (
        "hedge" in action
        or "short" in action
        or "regime" in family
        or action in {"stage_hedge", "stage_short", "stage_pair"}
    )


def _candidate_mutation_counters(candidate: dict[str, Any]) -> dict[str, int]:
    counters = candidate.get("mutation_counters") if isinstance(candidate.get("mutation_counters"), dict) else {}
    return {
        "public_actions_taken": _int_count(counters.get("public_actions_taken", candidate.get("public_actions_taken"))),
        "external_mutations": _int_count(counters.get("external_mutations", candidate.get("external_mutations"))),
        "orders_submitted": _int_count(counters.get("orders_submitted", candidate.get("orders_submitted"))),
        "broker_orders_submitted": _int_count(
            counters.get("broker_orders_submitted", candidate.get("broker_orders_submitted"))
        ),
    }


def _event_refs_as_sources(candidate: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for event in _list(candidate.get("event_refs")):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or event.get("id") or "").strip()
        url = str(event.get("url") or event.get("source") or "").strip()
        if event_id:
            refs.append(f"event:{event_id}")
        if url:
            refs.append(url)
    return refs


def _historical_analog_refs(candidate: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for analog in _list(candidate.get("historical_analogs")):
        if not isinstance(analog, dict):
            continue
        regime_id = str(analog.get("regime_id") or "").strip()
        if regime_id:
            refs.append(f"regime:{regime_id}")
    return refs


def _risk_notes(candidate: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for key in ("risk_notes", "risk_factors", "constraints"):
        notes.extend(str(item).strip() for item in _list(candidate.get(key)) if str(item).strip())
    return list(dict.fromkeys(notes))


def _risk_notes_are_only_no_data(notes: list[str]) -> bool:
    if not notes:
        return False
    markers = ("no data", "no live", "research only", "preview", "placeholder", "needs data")
    return all(any(marker in note.lower() for marker in markers) for note in notes)


def _quality_silent_reason(failed_criteria: list[str]) -> str | None:
    if not failed_criteria:
        return None
    if "data_source_degraded" in failed_criteria:
        return "Ratatosk equity data source is degraded; no FIN card staged"
    if "run_reports_no_live_market_data" in failed_criteria or "missing_live_data_packet" in failed_criteria:
        return "candidate lacked live or fixture-equivalent market evidence"
    if "missing_thesis" in failed_criteria:
        return "candidate lacked a decision-grade thesis"
    return "candidate failed finance quality gate"


def _ratatosk_run_id(ratatosk_run: dict[str, Any]) -> str:
    llm_run = ratatosk_run.get("llm_run") if isinstance(ratatosk_run.get("llm_run"), dict) else {}
    for key in ("run_id", "cron_tick_id"):
        value = str(llm_run.get(key) or "").strip()
        if value:
            return value
    material = json.dumps(ratatosk_run, sort_keys=True, default=str)[:2000]
    return f"ratatosk-run-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def _ratatosk_source_label(ratatosk_run: dict[str, Any]) -> str:
    if _is_research_agent_run(ratatosk_run):
        return "the equity research agent"
    return f"the Robinhood v0.1 {ratatosk_run.get('phase') or 'market'} analysis"


def _ratatosk_candidate_label(ratatosk_run: dict[str, Any]) -> str:
    return "research" if _is_research_agent_run(ratatosk_run) else "Robinhood"


def _candidate_key(ratatosk_run: dict[str, Any], candidate: dict[str, Any]) -> str:
    material = {
        "run_id": _ratatosk_run_id(ratatosk_run),
        "phase": ratatosk_run.get("phase"),
        "symbol": candidate.get("symbol"),
        "score": candidate.get("score"),
        "instrument_type": candidate.get("instrument_type") or candidate.get("asset_class"),
        "direction": candidate.get("direction") or candidate.get("action"),
        "research_note": candidate.get("research_note") or candidate.get("thesis"),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"ratatosk-candidate-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _silent_reason(
    *,
    ratatosk_run: dict[str, Any],
    candidates: list[dict[str, Any]],
    min_score: float,
    failed_criteria: list[str] | None = None,
) -> str:
    status = str(ratatosk_run.get("status") or "")
    if status == "no_due_tick":
        return "no due Robinhood v0.1 market phase"
    if failed_criteria:
        return _quality_silent_reason(failed_criteria) or "candidate failed finance quality gate"
    if _run_is_data_source_degraded(ratatosk_run):
        return "Ratatosk equity data source is degraded; no FIN card staged"
    if not candidates:
        return "Ratatosk produced no research candidates"
    return f"no fresh Ratatosk candidate reached the {min_score:.2f} review threshold"


def _unsafe_mutation_counts(ratatosk_run: dict[str, Any]) -> dict[str, int]:
    return {
        "external_mutations": _int_count(ratatosk_run.get("external_mutations")),
        "broker_orders_submitted": max(
            _int_count(ratatosk_run.get("broker_orders_submitted")),
            _int_count(ratatosk_run.get("orders_submitted")),
        ),
    }


def _finance_automation_line(policy_decisions: dict[str, Any] | None) -> str:
    decisions = policy_decisions or {}
    research = decisions.get("research") if isinstance(decisions.get("research"), dict) else {}
    live_order = decisions.get("live_order") if isinstance(decisions.get("live_order"), dict) else {}
    if research.get("decision") == "allowed" and live_order.get("decision") != "allowed":
        return "Automation policy: finance research and paper-canary recommendations may auto-surface; live orders remain blocked."
    if live_order.get("decision") == "allowed":
        return "Automation policy: live orders require the scoped finance policy and run-level guard proof before execution."
    return "Automation policy: finance recommendation surfacing is blocked by policy; no live order is allowed."


def _trading_loop_context(ratatosk_run: dict[str, Any]) -> dict[str, Any]:
    heartbeat_present = str(ratatosk_run.get("task") or "") == "equity_trading_loop_tick"
    research = _dict(ratatosk_run.get("research"))
    candidate_selection_policy = _candidate_selection_policy_summary(
        _dict(research.get("candidate_selection_policy"))
    )
    scan_candidate_supply = _scan_candidate_supply_summary(
        _dict(research.get("scan_candidate_supply") or ratatosk_run.get("scan_candidate_supply"))
    )
    paper_canary = _dict(ratatosk_run.get("paper_canary"))
    paper_outcome = _paper_outcome_summary(_dict(ratatosk_run.get("paper_outcome")))
    raw_sample_collector = _dict(ratatosk_run.get("sample_collector"))
    raw_experiment_evaluation = _dict(
        ratatosk_run.get("experiment_evaluation") or raw_sample_collector.get("experiment_evaluation")
    )
    active_experiment_sample_window = _active_experiment_sample_window_summary(
        _dict(ratatosk_run.get("active_experiment_sample_window") or raw_sample_collector.get("active_experiment_sample_window")),
        raw_experiment_evaluation,
    )
    sample_collector = _sample_collector_summary(raw_sample_collector)
    if active_experiment_sample_window:
        sample_collector = {
            **sample_collector,
            "active_experiment_sample_window": active_experiment_sample_window,
        }
    live_status_payload = _dict(ratatosk_run.get("live_status") or ratatosk_run)
    paper_performance = _paper_performance_summary(
        _dict(ratatosk_run.get("paper_performance") or live_status_payload.get("paper_performance"))
    )
    raw_signal_optimizer = _dict(ratatosk_run.get("signal_optimizer") or live_status_payload.get("signal_optimizer"))
    historical_verifier = _historical_verifier_summary(
        _dict(
            ratatosk_run.get("historical_verifier")
            or raw_signal_optimizer.get("historical_verifier")
            or live_status_payload.get("historical_verifier")
        )
    )
    signal_optimizer = _signal_optimizer_summary(raw_signal_optimizer)
    stop_condition = _stop_condition_summary(ratatosk_run)
    experiment_evaluation = _experiment_evaluation_summary(raw_experiment_evaluation)
    optimizer_sample_plan = _dict(signal_optimizer.get("sample_acquisition_plan"))
    research_sample_plan = _dict(candidate_selection_policy.get("sample_acquisition_plan"))
    sample_acquisition_plan = research_sample_plan or optimizer_sample_plan
    if sample_acquisition_plan and not optimizer_sample_plan:
        signal_optimizer = {
            **signal_optimizer,
            "sample_acquisition_plan": sample_acquisition_plan,
        }
    live_status = _live_status_summary(live_status_payload)
    risk_incident = _risk_incident_summary(_dict(ratatosk_run.get("risk_incident")))
    return {
        "heartbeat": {
            "present": heartbeat_present,
            "tick_id": ratatosk_run.get("tick_id") if heartbeat_present else None,
            "status": ratatosk_run.get("status") if heartbeat_present else None,
            "research_mode": ratatosk_run.get("research_mode"),
            "research_status": research.get("status"),
            "research_signal_id": research.get("signal_id"),
            "research_candidate_count": research.get("candidate_count"),
            "research_symbols": [str(item) for item in _list(research.get("symbols"))],
            "candidate_selection_policy": candidate_selection_policy,
            "sample_acquisition_plan": sample_acquisition_plan,
            "scan_candidate_supply": scan_candidate_supply,
            "stop_condition": stop_condition,
            "paper_canary_status": paper_canary.get("status"),
            "paper_canary_reason": paper_canary.get("reason"),
            "active_experiment_sample_window": active_experiment_sample_window,
        },
        "scan_candidate_supply": scan_candidate_supply,
        "stop_condition": stop_condition,
        "paper_outcome": paper_outcome,
        "sample_collector": sample_collector,
        "paper_performance": paper_performance,
        "historical_verifier": historical_verifier,
        "signal_optimizer": signal_optimizer,
        "experiment_evaluation": experiment_evaluation,
        "active_experiment_sample_window": active_experiment_sample_window,
        "candidate_selection_policy": candidate_selection_policy,
        "sample_acquisition_plan": sample_acquisition_plan,
        "live_status": live_status,
        "risk_incident": risk_incident,
    }


def _stop_condition_payload_fields(loop_context: dict[str, Any]) -> dict[str, Any]:
    stop_condition = _dict(loop_context.get("stop_condition"))
    return {
        "stop_condition": stop_condition,
        "primary_next_action": stop_condition.get("primary_next_action"),
        "deterministic_stop_condition": stop_condition.get("deterministic_stop_condition"),
        "paper_optimization": stop_condition.get("paper_optimization"),
    }


def _stop_condition_summary(ratatosk_run: dict[str, Any]) -> dict[str, Any]:
    raw = _dict(ratatosk_run.get("stop_condition"))
    deterministic = _dict(raw.get("deterministic_stop_condition") or ratatosk_run.get("deterministic_stop_condition"))
    paper_optimization = _dict(raw.get("paper_optimization") or ratatosk_run.get("paper_optimization"))
    recommended_actions = _list(raw.get("recommended_actions") or ratatosk_run.get("recommended_actions"))
    release_conditions = [
        str(item.get("release_condition"))
        for item in recommended_actions
        if isinstance(item, dict) and item.get("release_condition")
    ]
    if not release_conditions:
        release_conditions = [str(item) for item in _list(raw.get("release_conditions")) if str(item).strip()]
    scan_candidate_supply = _scan_candidate_supply_summary(
        _dict(paper_optimization.get("scan_candidate_supply") or raw.get("scan_candidate_supply"))
    )
    bounded_commands = [
        {
            "command_id": item.get("command_id"),
            "command": item.get("command"),
        }
        for item in _list(paper_optimization.get("allowed_bounded_commands"))
        if isinstance(item, dict)
    ]
    present = bool(raw or deterministic or paper_optimization or ratatosk_run.get("primary_next_action"))
    summarized_paper_optimization = {
        "continue_reasons": [str(item) for item in _list(paper_optimization.get("continue_reasons"))],
        "max_new_samples": paper_optimization.get("max_new_samples"),
        "max_iterations": paper_optimization.get("max_iterations"),
        "scan_candidate_supply": scan_candidate_supply,
        "allowed_bounded_commands": bounded_commands,
    }
    return {
        "present": present,
        "status": raw.get("status"),
        "primary_next_action": raw.get("primary_next_action") or ratatosk_run.get("primary_next_action"),
        "release_conditions": release_conditions,
        "deterministic_stop_condition": deterministic,
        "paper_optimization": summarized_paper_optimization,
        "max_new_samples": paper_optimization.get("max_new_samples"),
        "max_iterations": paper_optimization.get("max_iterations"),
        "scan_candidate_supply": scan_candidate_supply,
        "wait_when": [str(item) for item in _list(deterministic.get("wait_when"))],
        "read_only": raw.get("read_only") is True,
        "live_order_authority": raw.get("live_order_authority"),
        "broker_orders_submitted": int(raw.get("broker_orders_submitted") or 0),
    }


def _scan_candidate_supply_summary(payload: dict[str, Any]) -> dict[str, Any]:
    rejection_reasons = (
        payload.get("rejection_reasons")
        or payload.get("rejection_reason_counts")
        or payload.get("rejected_reason_counts")
    )
    if isinstance(rejection_reasons, dict):
        reasons = [
            f"{reason}:{count}"
            for reason, count in sorted(
                rejection_reasons.items(),
                key=lambda item: (-int(item[1] or 0), str(item[0])),
            )
        ]
    else:
        reasons = [str(item) for item in _list(rejection_reasons)]
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "market_count": payload.get("market_count"),
        "dynamic_scan_limit": payload.get("dynamic_scan_limit") or payload.get("scan_limit"),
        "proposal_count": payload.get("proposal_count"),
        "validated_count": payload.get("validated_count"),
        "selected_candidate_count": payload.get("selected_candidate_count"),
        "rejected_count": payload.get("rejected_count"),
        "rejection_reasons": reasons,
        "broker_orders_submitted": int(payload.get("broker_orders_submitted") or 0),
    }


def _paper_outcome_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "signal_id": payload.get("signal_id"),
        "symbol": payload.get("symbol"),
        "entry_price": payload.get("entry_price"),
        "current_price": payload.get("current_price"),
        "unrealized_pnl": payload.get("unrealized_pnl"),
        "return_pct": payload.get("return_pct"),
        "failures": [str(item) for item in _list(payload.get("failures"))],
    }


def _paper_performance_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "sample_count": payload.get("sample_count"),
        "hit_rate": payload.get("hit_rate"),
        "average_return": payload.get("average_return"),
        "cumulative_return": payload.get("cumulative_return"),
        "sharpe_ratio": payload.get("sharpe_ratio"),
        "max_drawdown": payload.get("max_drawdown"),
        "newey_west_tstat_proxy": payload.get("newey_west_tstat_proxy"),
        "oos_months": payload.get("oos_months"),
        "max_symbol_concentration": payload.get("max_symbol_concentration"),
        "blocking_reasons": [str(item) for item in _list(payload.get("blocking_reasons"))],
        "broker_orders_submitted": int(payload.get("broker_orders_submitted") or 0),
    }


def _historical_verifier_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "validation_mode": payload.get("validation_mode"),
        "symbols": [str(item) for item in _list(payload.get("symbols"))],
        "missing_symbols": [str(item) for item in _list(payload.get("missing_symbols"))],
        "sample_count": payload.get("sample_count"),
        "sample_gap": payload.get("sample_gap"),
        "sharpe_ratio": payload.get("sharpe_ratio"),
        "max_drawdown": payload.get("max_drawdown"),
        "newey_west_tstat_proxy": payload.get("newey_west_tstat_proxy"),
        "oos_months": payload.get("oos_months"),
        "max_symbol_concentration": payload.get("max_symbol_concentration"),
        "live_order_authority": payload.get("live_order_authority"),
        "blocking_reasons": [str(item) for item in _list(payload.get("blocking_reasons"))],
        "broker_orders_submitted": int(payload.get("broker_orders_submitted") or 0),
    }


def _sample_collector_summary(payload: dict[str, Any]) -> dict[str, Any]:
    active_window = _active_experiment_sample_window_summary(
        _dict(payload.get("active_experiment_sample_window")),
        _dict(payload.get("experiment_evaluation")),
    )
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "eligible_research_packet_count": payload.get("eligible_research_packet_count"),
        "canaries_created_count": payload.get("canaries_created_count"),
        "canaries_reconciled_count": payload.get("canaries_reconciled_count"),
        "outcomes_observed": payload.get("outcomes_observed"),
        "outcomes_blocked": payload.get("outcomes_blocked"),
        "paper_sample_count_after": payload.get("paper_sample_count_after"),
        "sample_gap_after": payload.get("sample_gap_after"),
        "confidence_policy_applied": payload.get("confidence_policy_applied") is True,
        "confidence_policy_source": payload.get("confidence_policy_source"),
        "policy_deferred_candidate_count": payload.get("policy_deferred_candidate_count"),
        "active_experiment_sample_window": active_window,
        "artifact_path": payload.get("artifact_path"),
        "broker_orders_submitted": int(payload.get("broker_orders_submitted") or _dict(payload.get("mutation_counters")).get("broker_orders_submitted") or 0),
    }


def _active_experiment_sample_window_summary(
    payload: dict[str, Any],
    experiment_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if payload:
        waiting_loops = [
            {
                "loop_name": item.get("loop_name"),
                "experiment_id": item.get("experiment_id"),
                "samples_remaining": item.get("samples_remaining"),
                "calibrated_samples_remaining": item.get("calibrated_samples_remaining"),
                "new_samples_remaining": item.get("new_samples_remaining"),
                "manual_approval_required": item.get("manual_approval_required") is True,
                "live_order_authority": item.get("live_order_authority"),
            }
            for item in _list(payload.get("waiting_loops"))
            if isinstance(item, dict)
        ]
        return {
            "present": True,
            "status": payload.get("status"),
            "source": payload.get("source"),
            "new_sample_cap": payload.get("new_sample_cap"),
            "waiting_loop_count": payload.get("waiting_loop_count") or len(waiting_loops),
            "live_order_authority": payload.get("live_order_authority"),
            "waiting_loops": waiting_loops,
        }

    evaluation = experiment_evaluation if isinstance(experiment_evaluation, dict) else {}
    loops = evaluation.get("loops") if isinstance(evaluation.get("loops"), dict) else {}
    waiting_loops: list[dict[str, Any]] = []
    for loop_name, loop in sorted(loops.items()):
        if not isinstance(loop, dict):
            continue
        if str(loop.get("decision") or "") != "wait":
            continue
        samples_remaining = _nonnegative_int(loop.get("samples_remaining"))
        calibrated_remaining = _nonnegative_int(loop.get("calibrated_samples_remaining"))
        new_samples_remaining = samples_remaining
        if calibrated_remaining is not None:
            if new_samples_remaining is None:
                new_samples_remaining = calibrated_remaining
            else:
                new_samples_remaining = min(new_samples_remaining, calibrated_remaining)
        waiting_loops.append(
            {
                "loop_name": str(loop_name),
                "experiment_id": loop.get("experiment_id"),
                "samples_remaining": samples_remaining,
                "calibrated_samples_remaining": calibrated_remaining,
                "new_samples_remaining": new_samples_remaining,
                "manual_approval_required": loop.get("manual_approval_required") is True,
                "live_order_authority": loop.get("live_order_authority") or evaluation.get("live_order_authority"),
            }
        )
    caps = [
        item.get("new_samples_remaining")
        for item in waiting_loops
        if isinstance(item.get("new_samples_remaining"), int)
    ]
    if not waiting_loops:
        return {"present": False}
    return {
        "present": True,
        "status": "active",
        "source": evaluation.get("source") or "experiment_evaluation",
        "new_sample_cap": min(caps) if caps else None,
        "waiting_loop_count": len(waiting_loops),
        "live_order_authority": evaluation.get("live_order_authority"),
        "waiting_loops": waiting_loops,
    }


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _experiment_evaluation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    loops = payload.get("loops") if isinstance(payload.get("loops"), dict) else {}
    loop_summaries: dict[str, dict[str, Any]] = {}
    decisions: list[str] = []
    waiting_count = 0
    terminal_count = 0
    for loop_name, loop in loops.items():
        if not isinstance(loop, dict):
            continue
        decision = str(loop.get("decision") or "")
        if decision:
            decisions.append(decision)
        if decision == "wait":
            waiting_count += 1
        if decision in {"keep_candidate", "discard"}:
            terminal_count += 1
        loop_summaries[str(loop_name)] = {
            "experiment_id": loop.get("experiment_id"),
            "status": loop.get("status"),
            "decision": loop.get("decision"),
            "manual_approval_required": loop.get("manual_approval_required") is True,
            "samples_remaining": loop.get("samples_remaining"),
            "calibrated_samples_remaining": loop.get("calibrated_samples_remaining"),
            "history_appended": loop.get("history_appended") is True,
        }
    return {
        "present": payload.get("present") is True or payload.get("task") == "equity_experiment_evaluator",
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "history_appended_count": payload.get("history_appended_count"),
        "waiting_loop_count": waiting_count,
        "terminal_loop_count": terminal_count,
        "decisions": decisions or [str(item) for item in _list(payload.get("decisions"))],
        "loops": loop_summaries,
        "live_order_authority": payload.get("live_order_authority"),
        "artifact_path": payload.get("artifact_path"),
        "broker_orders_submitted": int(payload.get("broker_orders_submitted") or _dict(payload.get("mutation_counters")).get("broker_orders_submitted") or 0),
    }


def _sample_acquisition_plan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "status": payload.get("status"),
        "target_new_samples": payload.get("target_new_samples"),
        "non_overrepresented_sample_target": payload.get("non_overrepresented_sample_target"),
        "concentration_relief_samples_needed": payload.get("concentration_relief_samples_needed"),
        "avoid_symbols": [str(item) for item in _list(payload.get("avoid_symbols"))],
        "preferred_existing_symbols": [str(item) for item in _list(payload.get("preferred_existing_symbols"))],
        "live_order_authority": payload.get("live_order_authority"),
    }


def _calibration_repair_plan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "policy_id": payload.get("policy_id"),
        "status": payload.get("status"),
        "mode": payload.get("mode"),
        "target_new_samples": payload.get("target_new_samples"),
        "target_total_sample_count": payload.get("target_total_sample_count"),
        "target_total_calibrated_sample_count": payload.get("target_total_calibrated_sample_count"),
        "baseline_sample_count": payload.get("baseline_sample_count"),
        "baseline_calibrated_sample_count": payload.get("baseline_calibrated_sample_count"),
        "target_repair_sample_count": payload.get("target_repair_sample_count"),
        "repair_samples_collected": payload.get("repair_samples_collected"),
        "repair_samples_remaining": payload.get("repair_samples_remaining"),
        "repair_reason_ids": [str(item) for item in _list(payload.get("repair_reason_ids"))],
        "blocking_reasons": [str(item) for item in _list(payload.get("blocking_reasons"))],
        "avoid_symbols": [str(item) for item in _list(payload.get("avoid_symbols"))],
        "preferred_existing_symbols": [
            str(item)
            for item in _list(payload.get("preferred_existing_symbols"))
        ],
        "preferred_symbol_details": [
            _calibration_repair_symbol_detail_summary(_dict(item))
            for item in _list(payload.get("preferred_symbol_details"))
            if isinstance(item, dict)
        ],
        "concentration_limited_symbols": [
            str(item)
            for item in _list(payload.get("concentration_limited_symbols"))
        ],
        "high_brier_symbols": [str(item) for item in _list(payload.get("high_brier_symbols"))],
        "sample_acquisition_avoid_symbols": [
            str(item)
            for item in _list(payload.get("sample_acquisition_avoid_symbols"))
        ],
        "live_order_authority": payload.get("live_order_authority"),
    }


def _calibration_repair_symbol_detail_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": payload.get("symbol"),
        "repair_priority_rank": payload.get("repair_priority_rank"),
        "repair_priority_score": payload.get("repair_priority_score"),
        "preference_sources": [str(item) for item in _list(payload.get("preference_sources"))],
        "calibration_sample_count": payload.get("calibration_sample_count"),
        "performance_sample_count": payload.get("performance_sample_count"),
        "brier_score": payload.get("brier_score"),
        "realized_win_rate": payload.get("realized_win_rate"),
        "average_return": payload.get("average_return"),
        "sharpe_ratio": payload.get("sharpe_ratio"),
        "live_order_authority": payload.get("live_order_authority"),
    }


def _historical_policy_coverage_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "status": payload.get("status"),
        "coverage_basis": payload.get("coverage_basis"),
        "policy_id": payload.get("policy_id"),
        "historical_strategy_search_status": payload.get("historical_strategy_search_status"),
        "repair_plan_status": payload.get("repair_plan_status"),
        "target_new_samples": payload.get("target_new_samples"),
        "eligible_symbols": [str(item) for item in _list(payload.get("eligible_symbols"))],
        "repair_preferred_symbols": [
            str(item)
            for item in _list(payload.get("repair_preferred_symbols"))
        ],
        "missing_repair_preferred_symbols": [
            str(item)
            for item in _list(payload.get("missing_repair_preferred_symbols"))
        ],
        "missing_count": payload.get("missing_count"),
        "live_order_authority": payload.get("live_order_authority"),
    }


def _candidate_selection_policy_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "source": payload.get("source") or payload.get("sample_acquisition_plan_source"),
        "sample_acquisition_plan_source": payload.get("sample_acquisition_plan_source"),
        "calibration_repair_plan_source": payload.get("calibration_repair_plan_source"),
        "prefer_calibration_repair_symbols": [
            str(item)
            for item in _list(payload.get("prefer_calibration_repair_symbols"))
        ],
        "selected_symbol_in_sample_acquisition_avoid_list": (
            payload.get("selected_symbol_in_sample_acquisition_avoid_list") is True
        ),
        "selected_symbol_in_calibration_repair_avoid_list": (
            payload.get("selected_symbol_in_calibration_repair_avoid_list") is True
        ),
        "selected_symbol_in_calibration_repair_concentration_limited_list": (
            payload.get("selected_symbol_in_calibration_repair_concentration_limited_list") is True
        ),
        "selected_symbol_preferred_by_calibration_repair": (
            payload.get("selected_symbol_preferred_by_calibration_repair") is True
        ),
        "selected_symbol_calibration_repair_priority_detail": (
            _calibration_repair_symbol_detail_summary(
                _dict(payload.get("selected_symbol_calibration_repair_priority_detail"))
            )
            if _dict(payload.get("selected_symbol_calibration_repair_priority_detail"))
            else {}
        ),
        "sample_acquisition_plan": _sample_acquisition_plan_summary(
            _dict(payload.get("sample_acquisition_plan"))
        ),
        "calibration_repair_plan": _calibration_repair_plan_summary(
            _dict(payload.get("calibration_repair_plan"))
        ),
        "historical_policy_coverage": _historical_policy_coverage_summary(
            _dict(payload.get("historical_policy_coverage"))
        ),
        "live_order_authority": payload.get("live_order_authority"),
    }


def _signal_optimizer_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "promotion_decision": payload.get("promotion_decision"),
        "sample_gap": payload.get("sample_gap") or _dict(payload.get("data_requirements")).get("sample_gap"),
        "recommended_action_ids": [str(item) for item in _list(payload.get("recommended_action_ids"))],
        "blocking_reasons": [str(item) for item in _list(payload.get("blocking_reasons"))],
        "artifact_path": payload.get("artifact_path"),
        "skill_path": payload.get("skill_path"),
        "scan_candidate_supply": _scan_candidate_supply_summary(
            _dict(payload.get("scan_candidate_supply"))
        ),
        "sample_acquisition_plan": _sample_acquisition_plan_summary(
            _dict(payload.get("sample_acquisition_plan"))
        ),
        "calibration_repair_plan": _calibration_repair_plan_summary(
            _dict(payload.get("calibration_repair_plan"))
        ),
        "historical_policy_coverage": _historical_policy_coverage_summary(
            _dict(payload.get("historical_policy_coverage"))
        ),
        "broker_orders_submitted": int(payload.get("broker_orders_submitted") or 0),
    }


def _live_status_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {"present": False}
    status_scope = _dict(payload.get("status_scope"))
    latest_research_candidate = _dict(payload.get("latest_research_candidate"))
    latest_research_ready = payload.get("latest_research_ready")
    if latest_research_ready is None and latest_research_candidate:
        latest_research_ready = latest_research_candidate.get("ready") is True
    return {
        "present": True,
        "requested_signal_id": payload.get("requested_signal_id"),
        "resolved_signal_id": payload.get("resolved_signal_id"),
        "latest_research_signal_id": (
            payload.get("latest_research_signal_id")
            or latest_research_candidate.get("signal_id")
        ),
        "latest_research_ready": latest_research_ready is True,
        "status_scope": {
            "exact_signal_scoped": status_scope.get("exact_signal_scoped") is True,
            "warnings": [str(item) for item in _list(status_scope.get("warnings"))],
        },
        "ready_to_submit": payload.get("ready_to_submit") is True,
        "go_live_blocked": payload.get("go_live_blocked") is True,
        "one_shot_live_submit_available": _dict(_dict(payload.get("command_gates")).get("one_shot_live_submit")).get("available") is True
        or payload.get("one_shot_live_submit_available") is True,
        "blockers": [str(item) for item in _list(payload.get("blockers"))],
    }


def _risk_incident_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "blocking_reasons": [str(item) for item in _list(payload.get("blocking_reasons"))],
        "read_only": payload.get("read_only") is True,
    }


def _trading_loop_text_lines(loop_context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    heartbeat = _dict(loop_context.get("heartbeat"))
    scan_candidate_supply = _dict(loop_context.get("scan_candidate_supply") or heartbeat.get("scan_candidate_supply"))
    stop_condition = _dict(loop_context.get("stop_condition") or heartbeat.get("stop_condition"))
    paper_outcome = _dict(loop_context.get("paper_outcome"))
    sample_collector = _dict(loop_context.get("sample_collector"))
    paper_performance = _dict(loop_context.get("paper_performance"))
    historical_verifier = _dict(loop_context.get("historical_verifier"))
    signal_optimizer = _dict(loop_context.get("signal_optimizer"))
    candidate_selection_policy = _dict(loop_context.get("candidate_selection_policy"))
    experiment_evaluation = _dict(loop_context.get("experiment_evaluation"))
    active_experiment_sample_window = _dict(
        loop_context.get("active_experiment_sample_window")
        or sample_collector.get("active_experiment_sample_window")
        or heartbeat.get("active_experiment_sample_window")
    )
    live_status = _dict(loop_context.get("live_status"))
    risk_incident = _dict(loop_context.get("risk_incident"))
    if heartbeat.get("present"):
        mode = _compact(heartbeat.get("research_mode"), "single")
        candidate_count = _compact(heartbeat.get("research_candidate_count"), "0")
        lines.append(
            "Trading loop heartbeat: "
            f"{_compact(heartbeat.get('status'), 'unknown')} "
            f"({ _compact(heartbeat.get('tick_id'), 'no tick id') }); "
            f"research {mode}, candidates {candidate_count}."
        )
    if scan_candidate_supply.get("present"):
        status = _compact(scan_candidate_supply.get("status"), "unknown")
        markets = _compact(scan_candidate_supply.get("market_count"), "0")
        proposals = _compact(scan_candidate_supply.get("proposal_count"), "0")
        validated = _compact(scan_candidate_supply.get("validated_count"), "0")
        selected = _compact(scan_candidate_supply.get("selected_candidate_count"), "0")
        rejected = _compact(scan_candidate_supply.get("rejected_count"), "0")
        reasons = [str(item) for item in _list(scan_candidate_supply.get("rejection_reasons"))]
        shown = ", ".join(reasons[:4])
        reason_text = f"; {shown}" if shown else ""
        lines.append(
            "Scan supply: "
            f"{status}; markets {markets}, proposals {proposals}, "
            f"validated {validated}, selected {selected}, rejected {rejected}{reason_text}."
        )
    if stop_condition.get("present"):
        status = _compact(stop_condition.get("status"), "unknown")
        next_action = _compact(stop_condition.get("primary_next_action"), "unknown")
        max_new = _compact(stop_condition.get("max_new_samples"), "unknown")
        release_conditions = [str(item) for item in _list(stop_condition.get("release_conditions"))]
        release_text = ", ".join(release_conditions[:2]) or "no release condition"
        lines.append(
            "Loop stop condition: "
            f"{status}; next {next_action}; max new samples {max_new}; release {release_text}."
        )
    if sample_collector.get("present"):
        status = _compact(sample_collector.get("status"), "unknown")
        observed = _compact(sample_collector.get("outcomes_observed"), "0")
        created = _compact(sample_collector.get("canaries_created_count"), "0")
        reconciled = _compact(sample_collector.get("canaries_reconciled_count"), "0")
        sample_gap = _compact(sample_collector.get("sample_gap_after"), "unknown")
        lines.append(
            "Sample collector: "
            f"{status}; created {created}, reconciled {reconciled}, "
            f"observed {observed}; sample gap {sample_gap}."
        )
    repair_preferred_symbols = [
        str(item)
        for item in _list(candidate_selection_policy.get("prefer_calibration_repair_symbols"))
    ]
    if repair_preferred_symbols:
        selected_preferred = (
            "yes"
            if candidate_selection_policy.get("selected_symbol_preferred_by_calibration_repair")
            else "no"
        )
        avoid_hit = (
            "yes"
            if candidate_selection_policy.get("selected_symbol_in_calibration_repair_avoid_list")
            else "no"
        )
        authority = _compact(candidate_selection_policy.get("live_order_authority"), "none")
        lines.append(
            "Candidate repair priority: "
            f"preferred {', '.join(repair_preferred_symbols)}; "
            f"selected preferred {selected_preferred}; avoid hit {avoid_hit}; "
            f"live authority {authority}."
        )
    if active_experiment_sample_window.get("present"):
        status = _compact(active_experiment_sample_window.get("status"), "unknown")
        cap = _compact(active_experiment_sample_window.get("new_sample_cap"), "unknown")
        waiting = _compact(active_experiment_sample_window.get("waiting_loop_count"), "0")
        lines.append(
            "Experiment sample window: "
            f"{status}; new sample cap {cap}; waiting loops {waiting}."
        )
    if paper_outcome.get("present"):
        symbol = _compact(paper_outcome.get("symbol"), "unknown")
        status = _compact(paper_outcome.get("status"), "unknown")
        pnl = _compact(paper_outcome.get("unrealized_pnl"), "unavailable")
        ret = _compact(paper_outcome.get("return_pct"), "unavailable")
        lines.append(f"Paper outcome: {symbol} {status}; unrealized P&L {pnl}, return {ret}.")
    if paper_performance.get("present"):
        status = _compact(paper_performance.get("status"), "unknown")
        samples = _compact(paper_performance.get("sample_count"), "0")
        average_return = _compact(paper_performance.get("average_return"), "unavailable")
        max_drawdown = _compact(paper_performance.get("max_drawdown"), "unavailable")
        blockers = [str(item) for item in _list(paper_performance.get("blocking_reasons"))]
        shown = ", ".join(blockers[:4]) or "no gate blockers"
        lines.append(
            "Paper performance: "
            f"{status}; samples {samples}, average return {average_return}, "
            f"max drawdown {max_drawdown}; {shown}."
        )
    if historical_verifier.get("present"):
        status = _compact(historical_verifier.get("status"), "unknown")
        samples = _compact(historical_verifier.get("sample_count"), "0")
        oos_months = _compact(historical_verifier.get("oos_months"), "unavailable")
        missing = [str(item) for item in _list(historical_verifier.get("missing_symbols"))]
        blockers = [str(item) for item in _list(historical_verifier.get("blocking_reasons"))]
        shown = ", ".join(missing[:4]) if missing else ", ".join(blockers[:4]) or "no gate blockers"
        lines.append(
            "Historical verifier: "
            f"{status}; samples {samples}, OOS months {oos_months}; {shown}."
        )
    if signal_optimizer.get("present"):
        status = _compact(signal_optimizer.get("status"), "unknown")
        decision = _compact(signal_optimizer.get("promotion_decision"), "unknown")
        sample_gap = _compact(signal_optimizer.get("sample_gap"), "unknown")
        actions = [str(item) for item in _list(signal_optimizer.get("recommended_action_ids"))]
        shown = ", ".join(actions[:5]) or "no optimizer actions"
        lines.append(
            "Signal optimizer: "
            f"{status}; promotion {decision}; sample gap {sample_gap}; {shown}."
        )
        sample_plan = _dict(signal_optimizer.get("sample_acquisition_plan"))
        if sample_plan:
            target = _compact(sample_plan.get("target_new_samples"), "unknown")
            non_overrepresented = _compact(
                sample_plan.get("non_overrepresented_sample_target"),
                "unknown",
            )
            avoid = ", ".join([str(item) for item in _list(sample_plan.get("avoid_symbols"))]) or "none"
            lines.append(
                "Sample acquisition plan: "
                f"target new {target}; non-overrepresented {non_overrepresented}; avoid {avoid}."
            )
        repair_plan = _dict(signal_optimizer.get("calibration_repair_plan"))
        if repair_plan:
            target = _compact(repair_plan.get("target_new_samples"), "unknown")
            preferred = ", ".join(
                [str(item) for item in _list(repair_plan.get("preferred_existing_symbols"))]
            ) or "none"
            avoid = ", ".join([str(item) for item in _list(repair_plan.get("avoid_symbols"))]) or "none"
            lines.append(
                "Calibration repair plan: "
                f"target new {target}; preferred {preferred}; avoid {avoid}."
            )
        coverage = _dict(signal_optimizer.get("historical_policy_coverage"))
        if coverage:
            status = _compact(coverage.get("status"), "unknown")
            missing = ", ".join(
                [str(item) for item in _list(coverage.get("missing_repair_preferred_symbols"))]
            ) or "none"
            lines.append(f"Historical policy coverage: {status}; missing {missing}.")
    if experiment_evaluation.get("present"):
        status = _compact(experiment_evaluation.get("status"), "unknown")
        appended = _compact(experiment_evaluation.get("history_appended_count"), "0")
        loops = _dict(experiment_evaluation.get("loops"))
        loop_bits = []
        for loop_name, loop in loops.items():
            if not isinstance(loop, dict):
                continue
            decision = _compact(loop.get("decision"), "unknown")
            remaining = _compact(loop.get("samples_remaining"), "unknown")
            loop_bits.append(f"{loop_name}:{decision}/{remaining} remaining")
        shown = ", ".join(loop_bits[:3]) or "no active loop decisions"
        lines.append(
            "Experiment evaluator: "
            f"{status}; history appended {appended}; {shown}."
        )
    if live_status.get("present"):
        status_scope = _dict(live_status.get("status_scope"))
        scope_text = ""
        if status_scope.get("exact_signal_scoped") is True:
            scope_text = f"exact signal {_compact(live_status.get('resolved_signal_id'), 'unknown')}; "
        else:
            warnings = [str(item) for item in _list(status_scope.get("warnings"))]
            if warnings:
                scope_text = f"scope warnings {', '.join(warnings[:3])}; "
        if live_status.get("ready_to_submit"):
            lines.append(
                "Live readiness: "
                f"{scope_text}ready_to_submit=true, but this Hermes card still does not place orders."
            )
        else:
            blockers = [str(item) for item in _list(live_status.get("blockers"))]
            shown = ", ".join(blockers[:6]) or "unspecified blockers"
            lines.append(f"Live readiness: blocked; {scope_text}{shown}.")
    if risk_incident.get("status") == "blocked":
        shown = ", ".join([str(item) for item in _list(risk_incident.get("blocking_reasons"))][:4])
        lines.append(f"Risk incident: blocked by {shown}.")
    return lines


def _unsafe_mutation_payload(
    *,
    ratatosk_run: dict[str, Any],
    candidates: list[dict[str, Any]],
    counts: dict[str, int],
    min_score: float,
    now: datetime,
    policy_decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    broker_orders = counts["broker_orders_submitted"]
    external_mutations = counts["external_mutations"]
    text = (
        f"Torben / Finance Radar / {now:%Y-%m-%d %H:%M UTC}\n\n"
        "Ratatosk reported a mutation during a stage-only finance run.\n"
        f"Broker orders submitted: {broker_orders}.\n"
        f"External mutations reported: {external_mutations}.\n"
        "I did not stage a FIN review card because stage-only finance must never report a trade as safe.\n"
        "Live trading remains blocked until the finance mandate, consent, kill switch, and guard all pass.\n"
    )
    return {
        "task": "torben_finance_radar",
        "wakeAgent": True,
        "generated_at": _iso(now),
        "status": "fail_closed",
        "reason": "ratatosk_reported_stage_only_mutation",
        "ratatosk_status": ratatosk_run.get("status"),
        "ratatosk_phase": ratatosk_run.get("phase"),
        "ratatosk_run_id": _ratatosk_run_id(ratatosk_run),
        "candidate_count": len(candidates),
        "selected_count": 0,
        "suppressed_duplicate_count": 0,
        "min_score": min_score,
        "scan_window": _scan_window(ratatosk_run, now),
        "scan_windows": _scan_windows(ratatosk_run),
        "scan_windows_count": len(_scan_windows(ratatosk_run)),
        "opportunity_universe_version": _opportunity_universe_version(ratatosk_run),
        "opportunity_universe_scope": _opportunity_universe_scope(ratatosk_run),
        "candidate_class_counts": _candidate_class_counts(candidates),
        "underfollowed_signal_count": _underfollowed_signal_count(candidates),
        "llm_triggered": False,
        "quiet_scan_llm_triggered": False,
        "llm_trigger_reason": None,
        "no_llm_reason": "stage-only mutation report blocked LLM-triggered surfacing",
        "market_regime": _llm_result(ratatosk_run).get("market_regime"),
        "no_trade_reason": _llm_result(ratatosk_run).get("no_trade_reason"),
        "actions": [],
        "llm_judge": _llm_audit(ratatosk_run),
        "automation_policy": policy_decisions or finance_automation_decisions(),
        "public_actions_taken": 0,
        "external_mutations": external_mutations,
        "orders_submitted": broker_orders,
        "broker_orders_submitted": broker_orders,
        "text": text,
    }


def _int_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _llm_audit(ratatosk_run: dict[str, Any]) -> dict[str, Any]:
    llm_run = ratatosk_run.get("llm_run") if isinstance(ratatosk_run.get("llm_run"), dict) else {}
    result = _llm_result(ratatosk_run)
    return {
        "invoked": result != {},
        "status": "completed" if result else str(ratatosk_run.get("status") or "unknown"),
        "phase": ratatosk_run.get("phase"),
        "run_id": llm_run.get("run_id"),
        "cron_tick_id": llm_run.get("cron_tick_id"),
        "token_budget": llm_run.get("token_budget"),
        "order_tools_available": bool(llm_run.get("order_tools_available")),
        "llm_error": ratatosk_run.get("llm_error"),
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "delivered_candidates": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "delivered_candidates": {}}
    return payload if isinstance(payload, dict) else {"version": 1, "delivered_candidates": {}}


def _mark_delivered(
    path: Path,
    state: dict[str, Any],
    *,
    ratatosk_run: dict[str, Any],
    candidates: list[dict[str, Any]],
    now: datetime,
) -> None:
    delivered = state.get("delivered_candidates") if isinstance(state.get("delivered_candidates"), dict) else {}
    for candidate in candidates:
        delivered[_candidate_key(ratatosk_run, candidate)] = {
            "delivered_at": _iso(now),
            "ratatosk_run_id": _ratatosk_run_id(ratatosk_run),
            "phase": ratatosk_run.get("phase"),
            "symbol": candidate.get("symbol"),
            "score": _score(candidate),
        }
    state.update({"version": 1, "delivered_candidates": delivered, "updated_at": _iso(now)})
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
