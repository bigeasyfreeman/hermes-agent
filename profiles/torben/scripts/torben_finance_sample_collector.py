#!/usr/bin/env python3
"""Run Torben's quiet Ratatosk finance paper-sample collector."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_cli.signal_coo.finance import write_finance_radar_artifacts

try:  # Package import under pytest.
    from .torben_finance_radar import (
        DEFAULT_RATATOSK_ROOT,
        DEFAULT_TIMEOUT_SECONDS,
        _env_int,
        _run_ratatosk_command,
        _truthy,
    )
except ImportError:  # Direct script execution from HERMES_HOME/scripts.
    from torben_finance_radar import (  # type: ignore[no-redef]
        DEFAULT_RATATOSK_ROOT,
        DEFAULT_TIMEOUT_SECONDS,
        _env_int,
        _run_ratatosk_command,
        _truthy,
    )


DEFAULT_SAMPLE_COLLECTOR_MAX_CANDIDATES = 3
DEFAULT_SAMPLE_COLLECTOR_MAX_OUTCOMES = 3


def _zero_mutation_counters() -> dict:
    return {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _ratatosk_sample_collector_command() -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_paper_sample_collector.py",
        "--json",
    ]
    state_root = str(os.getenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_STATE_ROOT") or "").strip()
    if state_root:
        command.extend(["--state-root", state_root])
    command.extend(
        [
            "--max-candidates",
            str(
                _env_int(
                    "TORBEN_FINANCE_SAMPLE_COLLECTOR_MAX_CANDIDATES",
                    DEFAULT_SAMPLE_COLLECTOR_MAX_CANDIDATES,
                )
            ),
        ]
    )
    command.extend(
        [
            "--max-outcomes",
            str(
                _env_int(
                    "TORBEN_FINANCE_SAMPLE_COLLECTOR_MAX_OUTCOMES",
                    DEFAULT_SAMPLE_COLLECTOR_MAX_OUTCOMES,
                )
            ),
        ]
    )
    if _truthy(os.getenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_REFRESH_EXISTING")):
        command.append("--refresh-existing")
    if _truthy(os.getenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_NO_CREATE_MISSING_CANARIES")):
        command.append("--no-create-missing-canaries")
    if _truthy(os.getenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_NO_ENSURE_CANARY_POSITIONS")):
        command.append("--no-ensure-canary-positions")
    return command


def _run_ratatosk_sample_collector() -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_SAMPLE_COLLECTOR_FIXTURE must contain a JSON object")
        source_refresh = payload.get("torben_source_refresh")
        source_refresh = dict(source_refresh) if isinstance(source_refresh, dict) else {}
        source_refresh.setdefault("status", "success")
        source_refresh.setdefault("profile", "fixture")
        source_refresh.setdefault("root", fixture_path)
        source_refresh.setdefault("command", ["fixture", fixture_path])
        source_refresh.setdefault("returncode", 0)
        source_refresh.setdefault("elapsed_seconds", 0)
        source_refresh.setdefault("stderr_tail", "")
        source_refresh.setdefault(
            "live_safety_env",
            {
                "RATATOSK_LIVE_TRADING": "0",
                "ROBINHOOD_LIVE": "0",
                "ROBINHOOD_EQUITY_LIVE": "0",
            },
        )
        payload["torben_source_refresh"] = source_refresh
        return payload, source_refresh

    root = Path(
        os.getenv("TORBEN_FINANCE_SAMPLE_COLLECTOR_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_SAMPLE_COLLECTOR_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    return _run_ratatosk_command(
        _ratatosk_sample_collector_command(),
        root=root,
        timeout_seconds=timeout_seconds,
    )


def _failure_payload(exc: Exception) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    counters = _zero_mutation_counters()
    return {
        "task": "torben_finance_sample_collector",
        "wakeAgent": True,
        "generated_at": now,
        "status": "error",
        "error": {
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        },
        "source_refresh_safe": False,
        "sample_collector_contract_safe": False,
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
        "text": (
            "Torben / Finance Sample Collector\n\n"
            "Ratatosk paper-sample collection failed before it could persist a useful status packet.\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:180]}\n"
            "Live trading env remained RATATOSK_LIVE_TRADING=0, ROBINHOOD_LIVE=0, and ROBINHOOD_EQUITY_LIVE=0.\n"
            "No broker order was placed, cancelled, modified, reviewed, approved, or submitted.\n"
        ),
    }


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "torben-finance-sample-collector-state.json"

    try:
        collector, source_refresh = _run_ratatosk_sample_collector()
        fingerprint = _fingerprint(collector)
        previous = _load_json(state_path)
        source_refresh_safe = _source_refresh_safe(source_refresh)
        sample_collector_contract_safe = _sample_collector_contract_safe(collector)
        should_alert = (
            str(collector.get("status") or "") != "idle"
            or not source_refresh_safe
            or not sample_collector_contract_safe
        )
        wake = should_alert and fingerprint != previous.get("fingerprint")
        sample_before = _sample_count(collector, "before")
        sample_after = _sample_count(collector, "after")
        sample_gap_before = _sample_gap(collector, "before")
        sample_gap_after = _sample_gap(collector, "after")
        optimizer = collector.get("signal_optimizer") if isinstance(collector.get("signal_optimizer"), dict) else {}
        experiment_evaluation = (
            collector.get("experiment_evaluation")
            if isinstance(collector.get("experiment_evaluation"), dict)
            else {}
        )
        active_experiment_sample_window = _active_experiment_sample_window(collector)
        counters = _mutation_counters(collector)
        live_order_authority = collector.get("live_order_authority") or "none"
        text_payload = collector | {
            "source_refresh_safe": source_refresh_safe,
            "sample_collector_contract_safe": sample_collector_contract_safe,
            "live_order_authority": live_order_authority,
        }
        payload = collector | {
            "task": "torben_finance_sample_collector",
            "adapter_task": collector.get("task"),
            "wakeAgent": wake,
            "source_refresh_safe": source_refresh_safe,
            "sample_collector_contract_safe": sample_collector_contract_safe,
            "sample_before": sample_before,
            "sample_after": sample_after,
            "sample_gap_before": sample_gap_before,
            "sample_gap_after": sample_gap_after,
            "optimizer": optimizer,
            "experiment_evaluation": experiment_evaluation,
            "active_experiment_sample_window": active_experiment_sample_window,
            "sample_collection_fingerprint": fingerprint,
            "previous_sample_collection_fingerprint": previous.get("fingerprint"),
            "source_refresh": source_refresh,
            "text": _render_text(text_payload) if wake else "",
            "live_order_authority": live_order_authority,
            "mutation_counters": counters,
            **counters,
        }
        _write_json(
            state_path,
            {
                "fingerprint": fingerprint,
                "status": collector.get("status"),
                "sample_count": sample_after,
                "sample_gap": sample_gap_after,
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-sample-collector-latest.json",
        text_path=state_dir / "torben-finance-sample-collector-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


def _fingerprint(payload: dict) -> str:
    basis = {
        "status": payload.get("status"),
        "outcomes_observed": payload.get("outcomes_observed"),
        "outcomes_blocked": payload.get("outcomes_blocked"),
        "sample_count": _sample_count(payload, "after"),
        "sample_gap": _sample_gap(payload, "after"),
        "calibrated_sample_count": payload.get("calibrated_sample_count_after"),
        "calibration_sample_gap": payload.get("calibration_sample_gap_after"),
        "optimizer_status": _nested(payload, ("signal_optimizer", "status")),
        "promotion_decision": _nested(payload, ("signal_optimizer", "promotion_decision")),
        "sample_acquisition_plan": _nested(payload, ("signal_optimizer", "sample_acquisition_plan")),
        "calibration_repair_plan": _nested(payload, ("signal_optimizer", "calibration_repair_plan")),
        "historical_policy_coverage": _nested(payload, ("signal_optimizer", "historical_policy_coverage")),
        "experiment_evaluation": _experiment_evaluation_fingerprint(payload),
        "active_experiment_sample_window": _active_experiment_sample_window_fingerprint(payload),
        "live_order_authority": payload.get("live_order_authority"),
        "read_only_broker": payload.get("read_only_broker"),
        "broker_review_attempted": payload.get("broker_review_attempted"),
        "broker_place_attempted": payload.get("broker_place_attempted"),
        "source_refresh": _source_refresh_fingerprint(payload.get("torben_source_refresh")),
        "created_signal_ids": [
            item.get("signal_id")
            for item in payload.get("canaries_created") or []
            if isinstance(item, dict)
        ],
        "reconciled_signal_ids": [
            item.get("signal_id")
            for item in payload.get("canaries_reconciled") or []
            if isinstance(item, dict)
        ],
        "outcome_signal_ids": [
            item.get("signal_id")
            for item in payload.get("outcomes") or []
            if isinstance(item, dict)
        ],
        "mutation_counters": {
            "public_actions_taken": payload.get("public_actions_taken"),
            "external_mutations": payload.get("external_mutations"),
            "orders_submitted": payload.get("orders_submitted"),
            "broker_orders_submitted": payload.get("broker_orders_submitted"),
        },
    }
    encoded = json.dumps(basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _render_text(payload: dict) -> str:
    after = payload.get("paper_performance_after") if isinstance(payload.get("paper_performance_after"), dict) else {}
    optimizer = payload.get("signal_optimizer") if isinstance(payload.get("signal_optimizer"), dict) else {}
    experiment_evaluation = (
        payload.get("experiment_evaluation")
        if isinstance(payload.get("experiment_evaluation"), dict)
        else {}
    )
    active_experiment_sample_window = _active_experiment_sample_window(payload)
    created = [item for item in payload.get("canaries_created") or [] if isinstance(item, dict)]
    reconciled = [item for item in payload.get("canaries_reconciled") or [] if isinstance(item, dict)]
    outcomes = [item for item in payload.get("outcomes") or [] if isinstance(item, dict)]
    lines = [
        "Torben / Finance Sample Collector",
        "",
        f"Status: {payload.get('status') or 'unknown'}.",
        (
            f"Paper samples: {_display(_sample_count(payload, 'after'))} observed; "
            f"gap={_display(_sample_gap(payload, 'after'))}."
        ),
        (
            f"Observed outcomes: {payload.get('outcomes_observed', 0)}; "
            f"blocked outcomes: {payload.get('outcomes_blocked', 0)}."
        ),
        (
            f"Canaries: created={len(created)}; reconciled={len(reconciled)}; "
            f"selected_outcomes={len(outcomes)}."
        ),
        (
            f"Optimizer: {optimizer.get('status') or 'unknown'}; "
            f"promotion={optimizer.get('promotion_decision') or 'unknown'}."
        ),
        (
            "Safety: "
            f"source_refresh_safe={payload.get('source_refresh_safe') is True}; "
            f"sample_collector_contract_safe={payload.get('sample_collector_contract_safe') is True}; "
            f"authority={payload.get('live_order_authority') or 'none'}."
        ),
    ]
    if experiment_evaluation:
        lines.append(
            "Experiment evaluator: "
            f"{experiment_evaluation.get('status') or 'unknown'}; "
            f"history_appended={_display(experiment_evaluation.get('history_appended_count'))}."
        )
    if active_experiment_sample_window:
        lines.append(
            "Experiment sample window: "
            f"{active_experiment_sample_window.get('status') or 'unknown'}; "
            f"new_sample_cap={_display(active_experiment_sample_window.get('new_sample_cap'))}; "
            f"waiting_loops={_display(active_experiment_sample_window.get('waiting_loop_count'))}."
        )
    sample_plan = optimizer.get("sample_acquisition_plan") if isinstance(optimizer.get("sample_acquisition_plan"), dict) else {}
    if sample_plan:
        avoid_symbols = [str(item) for item in sample_plan.get("avoid_symbols") or []]
        lines.append(
            "Sample plan: "
            f"target_new={_display(sample_plan.get('target_new_samples'))}; "
            f"non_overrepresented={_display(sample_plan.get('non_overrepresented_sample_target'))}; "
            f"avoid={','.join(avoid_symbols) if avoid_symbols else 'none'}."
        )
    repair_plan = (
        optimizer.get("calibration_repair_plan")
        if isinstance(optimizer.get("calibration_repair_plan"), dict)
        else {}
    )
    if repair_plan:
        preferred_symbols = [str(item) for item in repair_plan.get("preferred_existing_symbols") or []]
        avoid_symbols = [str(item) for item in repair_plan.get("avoid_symbols") or []]
        lines.append(
            "Calibration repair plan: "
            f"target_new={_display(repair_plan.get('target_new_samples'))}; "
            f"preferred={','.join(preferred_symbols) if preferred_symbols else 'none'}; "
            f"avoid={','.join(avoid_symbols) if avoid_symbols else 'none'}."
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
    lines.append("No broker order was placed, cancelled, modified, reviewed, approved, or submitted.")
    blockers = [str(item) for item in after.get("blocking_reasons") or []]
    actions = [str(item) for item in optimizer.get("recommended_action_ids") or []]
    if blockers:
        lines.extend(["", "Performance blockers:", *[f"- {item}" for item in blockers[:8]]])
    if actions:
        lines.extend(["", "Optimizer actions:", *[f"- {item}" for item in actions[:5]]])
    return "\n".join(lines) + "\n"


def _sample_count(payload: dict, phase: str) -> object:
    explicit = payload.get(f"paper_sample_count_{phase}")
    if explicit is not None:
        return explicit
    return _nested(payload, (f"paper_performance_{phase}", "sample_count"))


def _sample_gap(payload: dict, phase: str) -> object:
    explicit = payload.get(f"sample_gap_{phase}")
    if explicit is not None:
        return explicit
    return _nested(payload, (f"paper_performance_{phase}", "sample_gap"))


def _display(value: object) -> object:
    return "unknown" if value is None else value


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


def _source_refresh_fingerprint(payload: object) -> dict:
    refresh = payload if isinstance(payload, dict) else {}
    env = refresh.get("live_safety_env") if isinstance(refresh.get("live_safety_env"), dict) else {}
    return {
        "status": refresh.get("status"),
        "returncode": refresh.get("returncode"),
        "ratatosk_live_trading": env.get("RATATOSK_LIVE_TRADING"),
        "robinhood_live": env.get("ROBINHOOD_LIVE"),
        "robinhood_equity_live": env.get("ROBINHOOD_EQUITY_LIVE"),
    }


def _source_refresh_safe(payload: dict) -> bool:
    env = payload.get("live_safety_env") if isinstance(payload.get("live_safety_env"), dict) else {}
    return (
        payload.get("status") == "success"
        and int(payload.get("returncode") or 0) == 0
        and env.get("RATATOSK_LIVE_TRADING") == "0"
        and env.get("ROBINHOOD_LIVE") == "0"
        and env.get("ROBINHOOD_EQUITY_LIVE") == "0"
    )


def _sample_collector_contract_safe(payload: dict) -> bool:
    return (
        payload.get("live_order_authority") in {None, "none"}
        and payload.get("read_only_broker") is True
        and payload.get("broker_review_attempted") is False
        and payload.get("broker_place_attempted") is False
        and _mutation_counters_zero(payload)
    )


def _mutation_counters(payload: dict) -> dict:
    nested = payload.get("mutation_counters") if isinstance(payload.get("mutation_counters"), dict) else {}
    return {
        key: _safe_int(payload.get(key, nested.get(key, 0)))
        for key in _zero_mutation_counters()
    }


def _mutation_counters_zero(payload: dict) -> bool:
    try:
        return all(value == 0 for value in _mutation_counters(payload).values())
    except (TypeError, ValueError):
        return False


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _nested(payload: dict, path: tuple[str, ...]) -> object:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


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


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return -1


if __name__ == "__main__":
    raise SystemExit(main())
