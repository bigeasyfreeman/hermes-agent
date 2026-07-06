#!/usr/bin/env python3
"""Run Torben's quiet Ratatosk finance risk monitor."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_cli.signal_coo.finance import write_finance_radar_artifacts

DEFAULT_LIVE_DISABLED_ENV = {
    "RATATOSK_LIVE_TRADING": "0",
    "ROBINHOOD_LIVE": "0",
    "ROBINHOOD_EQUITY_LIVE": "0",
}


def _zero_mutation_counters() -> dict:
    return {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _extract_stop_condition(payload: dict) -> dict:
    stop_condition = payload.get("stop_condition")
    if isinstance(stop_condition, dict):
        return stop_condition
    loop_heartbeat = payload.get("loop_heartbeat")
    if isinstance(loop_heartbeat, dict) and isinstance(loop_heartbeat.get("stop_condition"), dict):
        return loop_heartbeat["stop_condition"]
    return {}


def _extract_paper_evidence_runway(payload: dict) -> dict:
    runway = payload.get("paper_evidence_runway")
    if isinstance(runway, dict) and runway:
        return runway
    stop_condition = _extract_stop_condition(payload)
    if not stop_condition:
        return {}
    return {
        "present": stop_condition.get("present", True),
        "status": stop_condition.get("status"),
        "primary_next_action": stop_condition.get("primary_next_action"),
        "safe_operator_action": stop_condition.get("primary_next_action"),
        "paper_optimization": {
            "max_new_samples": stop_condition.get("max_new_samples"),
            "max_iterations": stop_condition.get("max_iterations"),
            "allowed_bounded_command_ids": stop_condition.get("allowed_command_ids") or [],
            "commands_live_disabled": True,
        },
        "recommended_action_ids": stop_condition.get("recommended_action_ids") or [],
        "live_order_authority": stop_condition.get("live_order_authority") or "none",
        "mutation_counters": stop_condition.get("mutation_counters") or _zero_mutation_counters(),
    }


def _extract_loop_readiness_ledger(payload: dict, source_refresh: dict | None = None) -> dict:
    ledger = payload.get("loop_readiness_ledger")
    if isinstance(ledger, dict) and ledger:
        return ledger
    refresh = source_refresh if isinstance(source_refresh, dict) else {}
    state_root = str(refresh.get("state_root") or "").strip()
    if state_root:
        ledger = _load_json(Path(state_root) / "trading-loop" / "readiness-ledger.json")
        if ledger:
            return ledger
    canonical_root = str(refresh.get("canonical_root") or "").strip()
    if canonical_root:
        ledger = _load_json(Path(canonical_root) / "state" / "trading-loop" / "readiness-ledger.json")
        if ledger:
            return ledger
    return {}


def _failure_stop_condition(state_dir: Path | None) -> dict:
    previous = _load_json(state_dir / "torben-finance-risk-monitor-latest.json") if state_dir else {}
    stop_condition = _extract_stop_condition(previous)
    if stop_condition.get("status") or stop_condition.get("primary_next_action"):
        result = dict(stop_condition)
        result.setdefault("present", True)
        result.setdefault("source", "previous_latest_artifact")
        result["stale_after_source_refresh_failure"] = True
    else:
        result = {
            "present": False,
            "status": "source_refresh_failed",
            "primary_next_action": "restore_ratatosk_risk_monitor_source_refresh",
            "release_conditions": [],
        }
    result.setdefault("live_order_authority", "none")
    result.setdefault("broker_orders_submitted", 0)
    result.setdefault("mutation_counters", _zero_mutation_counters())
    return result


def _failure_source_refresh(exc: Exception) -> dict:
    return {
        "status": "failed",
        "profile": "ratatosk",
        "live_safety_env": dict(DEFAULT_LIVE_DISABLED_ENV),
        "live_order_authority": "none",
        "error": {"type": type(exc).__name__, "message": str(exc)[:300]},
    }


try:  # Package import under pytest.
    from .torben_finance_radar import (
        DEFAULT_RATATOSK_ROOT,
        DEFAULT_TIMEOUT_SECONDS,
        _env_int,
        _run_ratatosk_command,
    )
except ImportError:  # Direct script execution from HERMES_HOME/scripts.
    from torben_finance_radar import (  # type: ignore[no-redef]
        DEFAULT_RATATOSK_ROOT,
        DEFAULT_TIMEOUT_SECONDS,
        _env_int,
        _run_ratatosk_command,
    )


def _ratatosk_risk_monitor_command(root: Path, *, state_root: Path) -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_trading_risk_monitor.py",
        "--state-root",
        str(state_root),
        "--json",
    ]
    signal_id = str(os.getenv("TORBEN_FINANCE_RISK_MONITOR_SIGNAL_ID") or "").strip() or _latest_signal_id(root)
    if signal_id:
        command.extend(["--signal-id", signal_id])
    heartbeat_max_age = str(os.getenv("TORBEN_FINANCE_RISK_MONITOR_HEARTBEAT_MAX_AGE_MINUTES") or "").strip()
    if heartbeat_max_age:
        command.extend(["--heartbeat-max-age-minutes", heartbeat_max_age])
    return command


def _default_risk_monitor_worktree(canonical_root: Path) -> Path:
    candidate = canonical_root.with_name(f"{canonical_root.name}-risk-monitor")
    if candidate.is_dir() and (candidate / ".git").exists():
        return candidate
    return canonical_root


def _run_risk_monitor_command(
    command: list[str],
    *,
    canonical_root: Path,
    execution_root: Path,
    state_root: Path,
    timeout_seconds: int,
) -> tuple[dict, dict]:
    role_env = {
        "RATATOSK_SIGNAL_MAKER_WORKTREE": str(canonical_root),
        "RATATOSK_SIGNAL_OPTIMIZER_WORKTREE": str(canonical_root),
        "RATATOSK_SIGNAL_VERIFIER_WORKTREE": str(canonical_root),
        "RATATOSK_VERIFIER_DEBT_WORKTREE": str(canonical_root),
        "RATATOSK_BROKER_CONNECTOR_WORKTREE": str(canonical_root),
        "RATATOSK_RISK_MONITOR_WORKTREE": str(execution_root),
        "RATATOSK_STATE_ROOT": str(state_root),
    }
    previous = {key: os.environ.get(key) for key in role_env}
    try:
        os.environ.update(role_env)
        return _run_ratatosk_command(command, root=execution_root, timeout_seconds=timeout_seconds)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_ratatosk_risk_monitor() -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_RISK_MONITOR_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_RISK_MONITOR_FIXTURE must contain a JSON object")
        payload["torben_source_refresh"] = {
            "status": "success",
            "profile": "fixture",
            "root": fixture_path,
            "command": ["fixture", fixture_path],
            "returncode": 0,
            "elapsed_seconds": 0,
            "stderr_tail": "",
        }
        return payload, payload["torben_source_refresh"]

    canonical_root = Path(
        os.getenv("TORBEN_FINANCE_RISK_MONITOR_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    execution_root = Path(
        os.getenv("TORBEN_FINANCE_RISK_MONITOR_WORKTREE")
        or os.getenv("RATATOSK_RISK_MONITOR_WORKTREE")
        or _default_risk_monitor_worktree(canonical_root)
    )
    state_root = Path(
        os.getenv("TORBEN_FINANCE_RISK_MONITOR_STATE_ROOT")
        or os.getenv("RATATOSK_STATE_ROOT")
        or canonical_root / "state"
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_RISK_MONITOR_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    payload, refresh = _run_risk_monitor_command(
        _ratatosk_risk_monitor_command(canonical_root, state_root=state_root),
        canonical_root=canonical_root,
        execution_root=execution_root,
        state_root=state_root,
        timeout_seconds=timeout_seconds,
    )
    refresh["canonical_root"] = str(canonical_root)
    refresh["state_root"] = str(state_root)
    return payload, refresh


def _failure_payload(exc: Exception, *, state_dir: Path | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    counters = _zero_mutation_counters()
    source_refresh = _failure_source_refresh(exc)
    stop_condition = _failure_stop_condition(state_dir)
    return {
        "task": "torben_finance_risk_monitor",
        "wakeAgent": True,
        "generated_at": now,
        "status": "error",
        "error": {
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        },
        "source_refresh": source_refresh,
        "torben_source_refresh": source_refresh,
        "live_order_authority": "none",
        "stop_condition": stop_condition,
        "mutation_counters": counters,
        **counters,
        "text": (
            "Torben / Finance Risk Monitor\n\n"
            "Ratatosk risk monitor failed before it could persist a useful status packet.\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:180]}\n"
            "Live trading env remained RATATOSK_LIVE_TRADING=0, ROBINHOOD_LIVE=0, "
            "and ROBINHOOD_EQUITY_LIVE=0.\n"
            "No broker order was placed, cancelled, modified, or approved.\n"
        ),
    }


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "torben-finance-risk-monitor-state.json"

    try:
        monitor, source_refresh = _run_ratatosk_risk_monitor()
        loop_readiness_ledger = _extract_loop_readiness_ledger(monitor, source_refresh)
        fingerprint_source = monitor | {"loop_readiness_ledger": loop_readiness_ledger}
        fingerprint = _fingerprint(fingerprint_source)
        previous = _load_json(state_path)
        paper_evidence_runway = _extract_paper_evidence_runway(monitor)
        quiet_wait = _quiet_paper_evidence_wait(
            monitor,
            paper_evidence_runway=paper_evidence_runway,
            loop_readiness_ledger=loop_readiness_ledger,
        )
        wake = (
            str(monitor.get("status") or "") != "clear"
            and fingerprint != previous.get("fingerprint")
            and not quiet_wait
        )
        payload = monitor | {
            "task": "torben_finance_risk_monitor",
            "adapter_task": monitor.get("task"),
            "wakeAgent": wake,
            "active_experiment_sample_window": _active_experiment_sample_window(monitor),
            "paper_evidence_runway": paper_evidence_runway,
            "loop_readiness_ledger": loop_readiness_ledger,
            "quiet_paper_evidence_wait": quiet_wait,
            "risk_fingerprint": fingerprint,
            "previous_risk_fingerprint": previous.get("fingerprint"),
            "source_refresh": source_refresh,
            "text": _render_text(fingerprint_source) if wake else "",
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        }
        _write_json(
            state_path,
            {
                "fingerprint": fingerprint,
                "status": monitor.get("status"),
                "blocking_reasons": monitor.get("blocking_reasons") or [],
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc, state_dir=state_dir)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-risk-monitor-latest.json",
        text_path=state_dir / "torben-finance-risk-monitor-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


def _fingerprint(payload: dict) -> str:
    basis = {
        "status": payload.get("status"),
        "blocking_reasons": payload.get("blocking_reasons") or [],
        "warning_reasons": payload.get("warning_reasons") or [],
        "live_ready": (payload.get("live_status") or {}).get("ready_to_submit"),
        "heartbeat": _heartbeat_fingerprint(payload),
        "experiment_evaluation": _experiment_evaluation_fingerprint(payload),
        "active_experiment_sample_window": _active_experiment_sample_window_fingerprint(payload),
        "optimizer_repair": _optimizer_repair_fingerprint(payload),
        "verifier_debt_audit": _verifier_debt_audit_fingerprint(payload),
        "role_separation_audit": _role_separation_audit_fingerprint(payload),
        "stop_condition": _stop_condition_fingerprint(payload),
        "paper_evidence_runway": _paper_evidence_runway_fingerprint(payload),
        "evidence_wait_packet": _evidence_wait_packet_fingerprint(payload),
        "loop_readiness_ledger": _loop_readiness_ledger_fingerprint(payload),
        "research_candidate_supply": _research_candidate_supply_fingerprint(payload),
        "upstream_mutations": (payload.get("upstream_mutations") or {}).get("nonzero") or [],
    }
    encoded = json.dumps(basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _quiet_paper_evidence_wait(
    payload: dict,
    *,
    paper_evidence_runway: dict,
    loop_readiness_ledger: dict,
) -> bool:
    allowed_blockers = {
        "circuit_breaker_active",
        "live_status_blocked",
        "paper_calibration_insufficient",
        "paper_experiment_evaluation_waiting",
        "paper_performance_insufficient",
        "signal_optimizer_blocked",
        "trading_halt_active",
    }
    blockers = {str(item) for item in payload.get("blocking_reasons") or [] if str(item or "").strip()}
    stop_condition = _extract_stop_condition(payload)
    paper = (
        paper_evidence_runway.get("paper_optimization")
        if isinstance(paper_evidence_runway.get("paper_optimization"), dict)
        else {}
    )
    role_audit = payload.get("role_separation_audit") if isinstance(payload.get("role_separation_audit"), dict) else {}
    evidence_wait = (
        payload.get("evidence_wait_packet")
        if isinstance(payload.get("evidence_wait_packet"), dict)
        else {}
    )
    ledger_current = (
        loop_readiness_ledger.get("current_state")
        if isinstance(loop_readiness_ledger.get("current_state"), dict)
        else {}
    )
    return (
        payload.get("status") == "blocked"
        and stop_condition.get("status") == "wait_for_paper_evidence"
        and stop_condition.get("primary_next_action") == "wait_for_oos_or_market_data"
        and "wait_for_oos_or_market_data" in (stop_condition.get("recommended_action_ids") or [])
        and (_nonnegative_int(stop_condition.get("max_new_samples")) or 0) == 0
        and (_nonnegative_int(stop_condition.get("max_iterations")) or 0) == 0
        and paper_evidence_runway.get("status") == "wait_for_paper_evidence"
        and paper_evidence_runway.get("safe_operator_action") == "wait_for_oos_or_market_data"
        and paper_evidence_runway.get("live_order_authority") == "none"
        and (_nonnegative_int(paper.get("max_new_samples")) or 0) == 0
        and (_nonnegative_int(paper.get("max_iterations")) or 0) == 0
        and paper.get("commands_live_disabled") is True
        and not (blockers - allowed_blockers)
        and role_audit.get("live_order_authority") == "none"
        and not role_audit.get("blocking_reasons")
        and _evidence_wait_packet_safe_to_wait(evidence_wait)
        and (not loop_readiness_ledger or ledger_current.get("safe_operator_action") == "wait_for_oos_or_market_data")
        and _mutation_counters_zero(payload)
        and _mutation_counters_zero(stop_condition)
        and _mutation_counters_zero(paper_evidence_runway)
    )


def _evidence_wait_packet_safe_to_wait(payload: dict) -> bool:
    if not payload:
        return False
    release = payload.get("release_evaluation") if isinstance(payload.get("release_evaluation"), dict) else {}
    wait_contract = payload.get("wait_contract") if isinstance(payload.get("wait_contract"), dict) else {}
    next_wake = payload.get("next_wake_contract") if isinstance(payload.get("next_wake_contract"), dict) else {}
    return (
        payload.get("status") == "pass"
        and release.get("status") in {"hold_wait", "market_open_scan_supply_wait"}
        and release.get("live_order_authority") == "none"
        and wait_contract.get("live_order_authority") == "none"
        and next_wake.get("status") == "scheduled_recheck"
        and next_wake.get("required_operator_action") == "continue_wait"
        and next_wake.get("commands_live_disabled") is True
        and next_wake.get("broker_submit_allowed") is False
        and next_wake.get("human_live_review_allowed") is False
        and next_wake.get("live_order_authority") == "none"
        and _mutation_counters_zero(payload)
        and _mutation_counters_zero(next_wake)
    )


def _mutation_counters_zero(payload: dict) -> bool:
    counters = payload.get("mutation_counters") if isinstance(payload.get("mutation_counters"), dict) else payload
    return all(int(counters.get(key, 0) or 0) == 0 for key in _zero_mutation_counters())


def _render_text(payload: dict) -> str:
    blockers = [str(item) for item in payload.get("blocking_reasons") or []]
    warnings = [str(item) for item in payload.get("warning_reasons") or []]
    actions = [str(item) for item in payload.get("next_actions") or []]
    heartbeat = payload.get("heartbeat") if isinstance(payload.get("heartbeat"), dict) else {}
    active_experiment_sample_window = _active_experiment_sample_window(payload)
    optimizer = payload.get("signal_optimizer") if isinstance(payload.get("signal_optimizer"), dict) else {}
    verifier_debt = payload.get("verifier_debt_audit") if isinstance(payload.get("verifier_debt_audit"), dict) else {}
    role_separation = payload.get("role_separation_audit") if isinstance(payload.get("role_separation_audit"), dict) else {}
    stop_condition = payload.get("stop_condition") if isinstance(payload.get("stop_condition"), dict) else {}
    paper_runway = _extract_paper_evidence_runway(payload)
    evidence_wait = (
        payload.get("evidence_wait_packet")
        if isinstance(payload.get("evidence_wait_packet"), dict)
        else {}
    )
    loop_readiness_ledger = _extract_loop_readiness_ledger(payload)
    research_supply = (
        payload.get("research_candidate_supply")
        if isinstance(payload.get("research_candidate_supply"), dict)
        else {}
    )
    lines = [
        "Torben / Finance Risk Monitor",
        "",
        f"Status: {payload.get('status') or 'unknown'}.",
        (
            f"Heartbeat: {heartbeat.get('tick_id') or 'missing'}; "
            f"stale={heartbeat.get('stale') is True}; "
            f"blocking={heartbeat.get('stale_blocking', heartbeat.get('stale')) is True}; "
            f"class={heartbeat.get('staleness_classification') or 'unknown'}."
        ),
        "No broker order was placed, cancelled, modified, reviewed, or approved.",
    ]
    if active_experiment_sample_window:
        lines.append(
            "Experiment sample window: "
            f"{active_experiment_sample_window.get('status') or 'unknown'}; "
            f"new_sample_cap={_display(active_experiment_sample_window.get('new_sample_cap'))}; "
            f"waiting_loops={_display(active_experiment_sample_window.get('waiting_loop_count'))}."
        )
    repair_plan = (
        optimizer.get("calibration_repair_plan")
        if isinstance(optimizer.get("calibration_repair_plan"), dict)
        else {}
    )
    if repair_plan:
        preferred = [str(item) for item in repair_plan.get("preferred_existing_symbols") or []]
        avoid = [str(item) for item in repair_plan.get("avoid_symbols") or []]
        lines.append(
            "Calibration repair plan: "
            f"target_new={_display(repair_plan.get('target_new_samples'))}; "
            f"preferred={','.join(preferred) if preferred else 'none'}; "
            f"avoid={','.join(avoid) if avoid else 'none'}."
        )
    coverage = (
        optimizer.get("historical_policy_coverage")
        if isinstance(optimizer.get("historical_policy_coverage"), dict)
        else {}
    )
    if coverage:
        missing = [str(item) for item in coverage.get("missing_repair_preferred_symbols") or []]
        lines.append(
            "Historical policy coverage: "
            f"{coverage.get('status') or 'unknown'}; "
            f"missing={','.join(missing) if missing else 'none'}."
        )
    verifier_policy = (
        optimizer.get("verifier_rejection_policy")
        if isinstance(optimizer.get("verifier_rejection_policy"), dict)
        else {}
    )
    if verifier_policy:
        lines.append(
            "Verifier rejection policy: "
            f"{verifier_policy.get('status') or 'unknown'}; "
            f"min_score={_display(verifier_policy.get('minimum_candidate_score'))}; "
            f"rank_multiplier={_display(verifier_policy.get('paper_candidate_rank_multiplier'))}; "
            f"authority={verifier_policy.get('live_order_authority') or 'none'}."
        )
    if verifier_debt:
        rejection_rate = (
            verifier_debt.get("rejection_rate_audit")
            if isinstance(verifier_debt.get("rejection_rate_audit"), dict)
            else {}
        )
        audit_actions = [
            str(item)
            for item in verifier_debt.get("recommended_action_ids") or []
            if str(item).strip()
        ]
        lines.append(
            "Verifier debt audit: "
            f"{verifier_debt.get('status') or 'unknown'}; "
            f"score={_display(verifier_debt.get('verifier_debt_score'))}; "
            f"actions={','.join(audit_actions[:4]) if audit_actions else 'none'}."
        )
        if rejection_rate:
            lines.append(
                "Verifier rejection rate: "
                f"{rejection_rate.get('status') or 'unknown'}; "
                f"rate={_display(rejection_rate.get('rejection_rate'))}; "
                f"proposals={_display(rejection_rate.get('proposal_count'))}; "
                f"rejected={_display(rejection_rate.get('rejected_candidate_count'))}; "
                f"min={_display(rejection_rate.get('min_rejection_rate'))}."
            )
    if role_separation:
        role_plan = (
            role_separation.get("remediation_plan")
            if isinstance(role_separation.get("remediation_plan"), dict)
            else {}
        )
        audit_actions = [
            str(item)
            for item in role_separation.get("recommended_action_ids") or []
            if str(item).strip()
        ]
        lines.append(
            "Role separation audit: "
            f"{role_separation.get('status') or 'unknown'}; "
            f"score={_display(role_separation.get('role_separation_debt_score'))}; "
            f"actions={','.join(audit_actions[:4]) if audit_actions else 'none'}."
        )
        if role_plan:
            shared_roles = [str(item) for item in role_plan.get("currently_shared_role_ids") or []]
            lines.append(
                "Role separation plan: "
                f"{role_plan.get('status') or 'unknown'}; "
                f"target={role_plan.get('target_risk_monitor_worktree') or 'missing'}; "
                f"shared={','.join(shared_roles[:6]) if shared_roles else 'none'}; "
                f"authority={role_plan.get('live_order_authority') or 'none'}."
            )
    if stop_condition:
        stop_actions = [
            str(item)
            for item in stop_condition.get("recommended_action_ids") or []
            if str(item).strip()
        ]
        lines.append(
            "Stop condition: "
            f"{stop_condition.get('status') or 'unknown'}; "
            f"max_new={_display(stop_condition.get('max_new_samples'))}; "
            f"action={','.join(stop_actions[:3]) if stop_actions else _display(stop_condition.get('primary_next_action'))}."
        )
    if paper_runway and paper_runway.get("present") is not False:
        paper = (
            paper_runway.get("paper_optimization")
            if isinstance(paper_runway.get("paper_optimization"), dict)
            else {}
        )
        action = paper_runway.get("safe_operator_action") or paper_runway.get("primary_next_action")
        lines.append(
            "Paper evidence runway: "
            f"{paper_runway.get('status') or 'unknown'}; "
            f"action={_display(action)}; "
            f"max_new={_display(paper.get('max_new_samples'))}; "
            f"commands_live_disabled={paper.get('commands_live_disabled') is True}; "
            f"authority={paper_runway.get('live_order_authority') or 'none'}."
        )
    if evidence_wait:
        release = (
            evidence_wait.get("release_evaluation")
            if isinstance(evidence_wait.get("release_evaluation"), dict)
            else {}
        )
        wait_contract = (
            evidence_wait.get("wait_contract")
            if isinstance(evidence_wait.get("wait_contract"), dict)
            else {}
        )
        next_wake = (
            evidence_wait.get("next_wake_contract")
            if isinstance(evidence_wait.get("next_wake_contract"), dict)
            else {}
        )
        wake_reasons = [str(item) for item in next_wake.get("wake_reason_ids") or [] if str(item).strip()]
        lines.append(
            "Evidence wait packet: "
            f"{evidence_wait.get('status') or 'unknown'}; "
            f"release={release.get('status') or 'unknown'}; "
            f"next={_display(next_wake.get('next_recheck_after_utc') or wait_contract.get('next_recheck_after_utc'))}; "
            f"market_scan={_display(next_wake.get('market_scan_recheck_after_utc'))}; "
            f"bounded_not_before={_display(next_wake.get('bounded_collection_not_before_utc') or wait_contract.get('bounded_collection_not_before_utc'))}; "
            f"reasons={','.join(wake_reasons[:5]) if wake_reasons else 'none'}; "
            f"commands_live_disabled={next_wake.get('commands_live_disabled') is True}; "
            f"authority={next_wake.get('live_order_authority') or evidence_wait.get('live_order_authority') or 'none'}."
        )
    if loop_readiness_ledger:
        current = (
            loop_readiness_ledger.get("current_state")
            if isinstance(loop_readiness_ledger.get("current_state"), dict)
            else {}
        )
        go_live = current.get("go_live") if isinstance(current.get("go_live"), dict) else {}
        halt_and_circuit = (
            current.get("halt_and_circuit_breaker")
            if isinstance(current.get("halt_and_circuit_breaker"), dict)
            else {}
        )
        promotion_controls = (
            current.get("live_promotion_controls")
            if isinstance(current.get("live_promotion_controls"), dict)
            else {}
        )
        operator_approval = (
            promotion_controls.get("operator_approval")
            if isinstance(promotion_controls.get("operator_approval"), dict)
            else {}
        )
        live_flags = (
            promotion_controls.get("live_flags")
            if isinstance(promotion_controls.get("live_flags"), dict)
            else {}
        )
        optimizer_evidence = (
            current.get("optimizer_evidence")
            if isinstance(current.get("optimizer_evidence"), dict)
            else {}
        )
        paper_gates = (
            current.get("paper_verifier_gates")
            if isinstance(current.get("paper_verifier_gates"), dict)
            else {}
        )
        gap_ids = [
            str(item.get("id"))
            for item in loop_readiness_ledger.get("blocking_gaps") or []
            if isinstance(item, dict) and item.get("id")
        ]
        lines.append(
            "Loop readiness ledger: "
            f"{loop_readiness_ledger.get('implementation_status') or 'unknown'}; "
            f"live={go_live.get('status') or loop_readiness_ledger.get('status') or 'unknown'}; "
            f"action={_display(current.get('safe_operator_action'))}; "
            f"halt={halt_and_circuit.get('status') or 'unknown'}; "
            f"approval={operator_approval.get('status') or 'unknown'}; "
            f"flags={live_flags.get('status') or 'unknown'}; "
            f"optimizer={optimizer_evidence.get('status') or 'unknown'}; "
            f"paper={paper_gates.get('status') or 'unknown'}; "
            f"gaps={','.join(gap_ids[:6]) if gap_ids else 'none'}; "
            "authority=none."
        )
    if research_supply and research_supply.get("present") is not False:
        latest_research = (
            research_supply.get("latest_research")
            if isinstance(research_supply.get("latest_research"), dict)
            else {}
        )
        scan_supply = (
            research_supply.get("scan_candidate_supply")
            if isinstance(research_supply.get("scan_candidate_supply"), dict)
            else {}
        )
        lines.append(
            "Research supply: "
            f"{research_supply.get('status') or 'unknown'}; "
            f"latest={latest_research.get('status') or 'unknown'}; "
            f"candidates={_display(latest_research.get('candidate_count'))}; "
            f"scan={scan_supply.get('status') or 'unknown'}; "
            f"action={research_supply.get('primary_next_action') or 'unknown'}."
        )
    if blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in blockers[:8]]])
    if warnings:
        lines.extend(["", "Warnings:", *[f"- {item}" for item in warnings[:8]]])
    if actions:
        lines.extend(["", "Next actions:", *[f"- {item}" for item in actions[:5]]])
    return "\n".join(lines) + "\n"


def _optimizer_repair_fingerprint(payload: dict) -> dict:
    optimizer = payload.get("signal_optimizer") if isinstance(payload.get("signal_optimizer"), dict) else {}
    repair_plan = (
        optimizer.get("calibration_repair_plan")
        if isinstance(optimizer.get("calibration_repair_plan"), dict)
        else {}
    )
    coverage = (
        optimizer.get("historical_policy_coverage")
        if isinstance(optimizer.get("historical_policy_coverage"), dict)
        else {}
    )
    verifier_policy = (
        optimizer.get("verifier_rejection_policy")
        if isinstance(optimizer.get("verifier_rejection_policy"), dict)
        else {}
    )
    return {
        "repair_status": repair_plan.get("status"),
        "target_new_samples": repair_plan.get("target_new_samples"),
        "preferred_existing_symbols": repair_plan.get("preferred_existing_symbols") or [],
        "avoid_symbols": repair_plan.get("avoid_symbols") or [],
        "repair_live_order_authority": repair_plan.get("live_order_authority"),
        "coverage_status": coverage.get("status"),
        "coverage_missing": coverage.get("missing_repair_preferred_symbols") or [],
        "coverage_live_order_authority": coverage.get("live_order_authority"),
        "verifier_rejection_policy_status": verifier_policy.get("status"),
        "verifier_rejection_minimum_candidate_score": verifier_policy.get("minimum_candidate_score"),
        "verifier_rejection_rank_multiplier": verifier_policy.get("paper_candidate_rank_multiplier"),
        "verifier_rejection_live_order_authority": verifier_policy.get("live_order_authority"),
    }


def _heartbeat_fingerprint(payload: dict) -> dict:
    heartbeat = payload.get("heartbeat") if isinstance(payload.get("heartbeat"), dict) else {}
    return {
        "tick_id": heartbeat.get("tick_id"),
        "generated_at": heartbeat.get("generated_at"),
        "stale": heartbeat.get("stale"),
        "stale_blocking": heartbeat.get("stale_blocking"),
        "expected_market_closed_idle": heartbeat.get("expected_market_closed_idle"),
        "market_open_now": heartbeat.get("market_open_now"),
        "market_closed_wait_context": heartbeat.get("market_closed_wait_context"),
        "staleness_classification": heartbeat.get("staleness_classification"),
    }


def _verifier_debt_audit_fingerprint(payload: dict) -> dict:
    audit = payload.get("verifier_debt_audit") if isinstance(payload.get("verifier_debt_audit"), dict) else {}
    rejection_rate = audit.get("rejection_rate_audit") if isinstance(audit.get("rejection_rate_audit"), dict) else {}
    return {
        "status": audit.get("status"),
        "score": audit.get("verifier_debt_score"),
        "blocking_reasons": audit.get("blocking_reasons") or [],
        "warning_reasons": audit.get("warning_reasons") or [],
        "recommended_action_ids": audit.get("recommended_action_ids") or [],
        "rejection_rate_status": rejection_rate.get("status"),
        "rejection_rate": rejection_rate.get("rejection_rate"),
        "rejection_rate_basis": rejection_rate.get("evaluation_basis"),
        "rejection_proposal_count": rejection_rate.get("proposal_count"),
        "rejection_rejected_count": rejection_rate.get("rejected_candidate_count"),
        "min_rejection_rate": rejection_rate.get("min_rejection_rate"),
        "live_order_authority": audit.get("live_order_authority"),
    }


def _role_separation_audit_fingerprint(payload: dict) -> dict:
    audit = payload.get("role_separation_audit") if isinstance(payload.get("role_separation_audit"), dict) else {}
    plan = audit.get("remediation_plan") if isinstance(audit.get("remediation_plan"), dict) else {}
    return {
        "status": audit.get("status"),
        "score": audit.get("role_separation_debt_score"),
        "blocking_reasons": audit.get("blocking_reasons") or [],
        "warning_reasons": audit.get("warning_reasons") or [],
        "recommended_action_ids": audit.get("recommended_action_ids") or [],
        "risk_monitor_worktree": audit.get("risk_monitor_worktree"),
        "remediation_plan": {
            "plan_id": plan.get("plan_id"),
            "status": plan.get("status"),
            "target_risk_monitor_worktree": plan.get("target_risk_monitor_worktree"),
            "currently_shared_role_ids": plan.get("currently_shared_role_ids") or [],
            "live_order_authority": plan.get("live_order_authority"),
        },
        "live_order_authority": audit.get("live_order_authority"),
    }


def _stop_condition_fingerprint(payload: dict) -> dict:
    stop = payload.get("stop_condition") if isinstance(payload.get("stop_condition"), dict) else {}
    return {
        "status": stop.get("status"),
        "primary_next_action": stop.get("primary_next_action"),
        "max_new_samples": stop.get("max_new_samples"),
        "max_iterations": stop.get("max_iterations"),
        "recommended_action_ids": stop.get("recommended_action_ids") or [],
        "live_review_status": stop.get("live_review_status"),
        "live_order_authority": stop.get("live_order_authority"),
    }


def _paper_evidence_runway_fingerprint(payload: dict) -> dict:
    runway = _extract_paper_evidence_runway(payload)
    paper = runway.get("paper_optimization") if isinstance(runway.get("paper_optimization"), dict) else {}
    repair = runway.get("calibration_repair_plan") if isinstance(runway.get("calibration_repair_plan"), dict) else {}
    return {
        "present": runway.get("present"),
        "status": runway.get("status"),
        "primary_next_action": runway.get("primary_next_action"),
        "safe_operator_action": runway.get("safe_operator_action"),
        "max_new_samples": paper.get("max_new_samples"),
        "max_iterations": paper.get("max_iterations"),
        "commands_live_disabled": paper.get("commands_live_disabled"),
        "repair_status": repair.get("status"),
        "repair_target_new_samples": repair.get("target_new_samples"),
        "recommended_action_ids": runway.get("recommended_action_ids") or [],
        "live_order_authority": runway.get("live_order_authority"),
    }


def _evidence_wait_packet_fingerprint(payload: dict) -> dict:
    packet = payload.get("evidence_wait_packet") if isinstance(payload.get("evidence_wait_packet"), dict) else {}
    release = packet.get("release_evaluation") if isinstance(packet.get("release_evaluation"), dict) else {}
    wait_contract = packet.get("wait_contract") if isinstance(packet.get("wait_contract"), dict) else {}
    next_wake = packet.get("next_wake_contract") if isinstance(packet.get("next_wake_contract"), dict) else {}
    return {
        "present": bool(packet),
        "status": packet.get("status"),
        "generated_at": packet.get("generated_at"),
        "release_status": release.get("status"),
        "release_signal_count": release.get("release_signal_count"),
        "required_operator_action": release.get("required_operator_action") or next_wake.get("required_operator_action"),
        "wait_status": wait_contract.get("status"),
        "wait_primary_next_action": wait_contract.get("primary_next_action"),
        "next_recheck_after_utc": next_wake.get("next_recheck_after_utc") or wait_contract.get("next_recheck_after_utc"),
        "budget_reopens_after_utc": next_wake.get("budget_reopens_after_utc"),
        "market_scan_recheck_after_utc": next_wake.get("market_scan_recheck_after_utc"),
        "bounded_collection_not_before_utc": next_wake.get("bounded_collection_not_before_utc")
        or wait_contract.get("bounded_collection_not_before_utc"),
        "wake_reason_ids": next_wake.get("wake_reason_ids") or [],
        "commands_live_disabled": next_wake.get("commands_live_disabled"),
        "broker_submit_allowed": next_wake.get("broker_submit_allowed"),
        "human_live_review_allowed": next_wake.get("human_live_review_allowed"),
        "live_order_authority": next_wake.get("live_order_authority") or packet.get("live_order_authority"),
    }


def _loop_readiness_ledger_fingerprint(payload: dict) -> dict:
    ledger = _extract_loop_readiness_ledger(payload)
    current = ledger.get("current_state") if isinstance(ledger.get("current_state"), dict) else {}
    go_live = current.get("go_live") if isinstance(current.get("go_live"), dict) else {}
    halt_and_circuit = (
        current.get("halt_and_circuit_breaker")
        if isinstance(current.get("halt_and_circuit_breaker"), dict)
        else {}
    )
    promotion_controls = (
        current.get("live_promotion_controls")
        if isinstance(current.get("live_promotion_controls"), dict)
        else {}
    )
    operator_approval = (
        promotion_controls.get("operator_approval")
        if isinstance(promotion_controls.get("operator_approval"), dict)
        else {}
    )
    live_flags = (
        promotion_controls.get("live_flags")
        if isinstance(promotion_controls.get("live_flags"), dict)
        else {}
    )
    optimizer_evidence = (
        current.get("optimizer_evidence")
        if isinstance(current.get("optimizer_evidence"), dict)
        else {}
    )
    paper_gates = (
        current.get("paper_verifier_gates")
        if isinstance(current.get("paper_verifier_gates"), dict)
        else {}
    )
    repair = (
        optimizer_evidence.get("calibration_repair_plan")
        if isinstance(optimizer_evidence.get("calibration_repair_plan"), dict)
        else {}
    )
    return {
        "status": ledger.get("status"),
        "ledger_status": ledger.get("ledger_status"),
        "implementation_status": ledger.get("implementation_status"),
        "safe_operator_action": current.get("safe_operator_action"),
        "go_live_status": go_live.get("status"),
        "go_live_blocked": go_live.get("go_live_blocked"),
        "ready_to_submit": go_live.get("ready_to_submit"),
        "halt_and_circuit_breaker_status": halt_and_circuit.get("status"),
        "trading_halt_active": halt_and_circuit.get("trading_halt_active"),
        "circuit_breaker_active": halt_and_circuit.get("circuit_breaker_active"),
        "operator_approval_status": operator_approval.get("status"),
        "operator_approval_required_scope": operator_approval.get("required_scope"),
        "live_flags_status": live_flags.get("status"),
        "live_flags_enabled_now": live_flags.get("enabled_now"),
        "one_shot_live_submit_available": live_flags.get("one_shot_live_submit_available"),
        "optimizer_evidence_status": optimizer_evidence.get("status"),
        "optimizer_status": optimizer_evidence.get("optimizer_status"),
        "optimizer_repair_status": repair.get("status"),
        "optimizer_sample_budget_open": optimizer_evidence.get("sample_budget_open"),
        "paper_verifier_status": paper_gates.get("status"),
        "paper_performance_status": paper_gates.get("performance_status"),
        "paper_calibration_status": paper_gates.get("calibration_status"),
        "paper_blocked_gate_ids": paper_gates.get("blocked_gate_ids") or [],
        "blocking_gap_ids": [
            str(item.get("id"))
            for item in ledger.get("blocking_gaps") or []
            if isinstance(item, dict) and item.get("id")
        ],
        "live_order_authority": "none" if ledger else None,
    }


def _research_candidate_supply_fingerprint(payload: dict) -> dict:
    supply = payload.get("research_candidate_supply") if isinstance(payload.get("research_candidate_supply"), dict) else {}
    latest_research = supply.get("latest_research") if isinstance(supply.get("latest_research"), dict) else {}
    scan_supply = supply.get("scan_candidate_supply") if isinstance(supply.get("scan_candidate_supply"), dict) else {}
    return {
        "present": supply.get("present"),
        "status": supply.get("status"),
        "primary_next_action": supply.get("primary_next_action"),
        "latest_research": {
            "generated_at": latest_research.get("generated_at"),
            "status": latest_research.get("status"),
            "signal_id": latest_research.get("signal_id"),
            "candidate_count": latest_research.get("candidate_count"),
        },
        "scan_candidate_supply": {
            "status": scan_supply.get("status"),
            "market_open": scan_supply.get("market_open"),
            "proposal_count": scan_supply.get("proposal_count"),
            "validated_candidate_count": scan_supply.get("validated_candidate_count"),
            "selected_candidate_count": scan_supply.get("selected_candidate_count"),
            "rejected_candidate_count": scan_supply.get("rejected_candidate_count"),
        },
        "diagnostics": supply.get("diagnostics") or [],
        "release_conditions": supply.get("release_conditions") or [],
        "commands_live_disabled": supply.get("commands_live_disabled"),
        "live_order_authority": supply.get("live_order_authority"),
    }


def _experiment_evaluation_fingerprint(payload: dict) -> dict:
    evaluation = payload.get("experiment_evaluation") if isinstance(payload.get("experiment_evaluation"), dict) else {}
    loops = evaluation.get("loops") if isinstance(evaluation.get("loops"), dict) else {}
    return {
        "status": evaluation.get("status"),
        "history_appended_count": evaluation.get("history_appended_count"),
        "loops": {
            str(loop_name): {
                "decision": loop.get("decision"),
                "samples_remaining": loop.get("samples_remaining"),
                "calibrated_samples_remaining": loop.get("calibrated_samples_remaining"),
                "history_appended": loop.get("history_appended"),
            }
            for loop_name, loop in sorted(loops.items())
            if isinstance(loop, dict)
        },
    }


def _active_experiment_sample_window(payload: dict) -> dict:
    explicit = payload.get("active_experiment_sample_window")
    if isinstance(explicit, dict) and explicit:
        return explicit

    evaluation = payload.get("experiment_evaluation") if isinstance(payload.get("experiment_evaluation"), dict) else {}
    loops = evaluation.get("loops") if isinstance(evaluation.get("loops"), dict) else {}
    waiting_loops: list[dict] = []
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
        return {}
    return {
        "status": "active",
        "source": evaluation.get("source") or "experiment_evaluation",
        "waiting_loop_count": len(waiting_loops),
        "new_sample_cap": min(caps) if caps else None,
        "live_order_authority": evaluation.get("live_order_authority"),
        "waiting_loops": waiting_loops,
    }


def _active_experiment_sample_window_fingerprint(payload: dict) -> dict:
    window = _active_experiment_sample_window(payload)
    waiting_loops = window.get("waiting_loops") if isinstance(window.get("waiting_loops"), list) else []
    return {
        "status": window.get("status"),
        "new_sample_cap": window.get("new_sample_cap"),
        "waiting_loop_count": window.get("waiting_loop_count"),
        "waiting_loops": [
            {
                "loop_name": item.get("loop_name"),
                "samples_remaining": item.get("samples_remaining"),
                "calibrated_samples_remaining": item.get("calibrated_samples_remaining"),
                "new_samples_remaining": item.get("new_samples_remaining"),
            }
            for item in waiting_loops
            if isinstance(item, dict)
        ],
    }


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _display(value: object) -> object:
    return "unknown" if value is None else value


def _latest_signal_id(root: Path) -> str | None:
    for path in (
        root / "state" / "finance-canaries" / "latest.json",
        root / "state" / "paper-outcomes" / "latest.json",
        root / "state" / "equity-research" / "latest.json",
    ):
        payload = _load_json(path)
        signal_id = str(payload.get("signal_id") or "").strip()
        if signal_id:
            return signal_id
    return None


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
