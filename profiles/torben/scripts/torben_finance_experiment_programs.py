#!/usr/bin/env python3
"""Run Torben's quiet Ratatosk paper experiment-program maintenance."""

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


SAFE_PROGRAM_STATUSES = {"programs_prepared", "awaiting_paper_data", "awaiting_paper_evidence"}
SAFE_LOOP_STATUSES = {"active", "awaiting_paper_data", "awaiting_paper_evidence"}
SAFE_EVALUATION_STATUSES = {"waiting_for_target_samples", "evaluated", "no_active_experiments"}


def _zero_mutation_counters() -> dict:
    return {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _ratatosk_experiment_programs_command() -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_experiment_programs.py",
        "--json",
    ]
    state_root = str(os.getenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_STATE_ROOT") or "").strip()
    if state_root:
        command.extend(["--state-root", state_root])
    output_path = str(os.getenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_OUTPUT_PATH") or "").strip()
    if output_path:
        command.extend(["--output-path", output_path])
    if _truthy(os.getenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_NO_PERSIST")):
        command.append("--no-persist")
    return command


def _ratatosk_experiment_evaluation_command() -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_experiment_evaluator.py",
        "--json",
    ]
    state_root = str(
        os.getenv("TORBEN_FINANCE_EXPERIMENT_EVALUATION_STATE_ROOT")
        or os.getenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_STATE_ROOT")
        or ""
    ).strip()
    if state_root:
        command.extend(["--state-root", state_root])
    output_path = str(os.getenv("TORBEN_FINANCE_EXPERIMENT_EVALUATION_OUTPUT_PATH") or "").strip()
    if output_path:
        command.extend(["--output-path", output_path])
    if _truthy(os.getenv("TORBEN_FINANCE_EXPERIMENT_EVALUATION_NO_PERSIST")):
        command.append("--no-persist")
    if _truthy(os.getenv("TORBEN_FINANCE_EXPERIMENT_EVALUATION_NO_HISTORY")):
        command.append("--no-history")
    return command


def _run_ratatosk_experiment_programs() -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_FIXTURE must contain a JSON object")
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
        os.getenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_EXPERIMENT_PROGRAMS_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    return _run_ratatosk_command(
        _ratatosk_experiment_programs_command(),
        root=root,
        timeout_seconds=timeout_seconds,
    )


def _run_ratatosk_experiment_evaluation() -> tuple[dict, dict]:
    root = Path(
        os.getenv("TORBEN_FINANCE_EXPERIMENT_EVALUATION_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_EXPERIMENT_EVALUATION_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_EXPERIMENT_PROGRAMS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    return _run_ratatosk_command(
        _ratatosk_experiment_evaluation_command(),
        root=root,
        timeout_seconds=timeout_seconds,
    )


def _failure_payload(exc: Exception) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    counters = _zero_mutation_counters()
    return {
        "task": "torben_finance_experiment_programs",
        "wakeAgent": True,
        "generated_at": now,
        "status": "error",
        "error": {
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        },
        "source_refresh_safe": False,
        "experiment_programs_contract_safe": False,
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
        "text": (
            "Torben / Finance Experiment Programs\n\n"
            "Ratatosk experiment-program maintenance failed before it could persist a useful status packet.\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:180]}\n"
            "Live trading env remained RATATOSK_LIVE_TRADING=0, ROBINHOOD_LIVE=0, and ROBINHOOD_EQUITY_LIVE=0.\n"
            "No broker order was placed, cancelled, modified, reviewed, approved, or submitted.\n"
        ),
    }


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "torben-finance-experiment-programs-state.json"

    try:
        programs, source_refresh = _run_ratatosk_experiment_programs()
        evaluation, evaluation_refresh = _run_ratatosk_experiment_evaluation()
        evaluation_contract_safe = _experiment_evaluation_contract_safe(evaluation, programs)
        fingerprint = _fingerprint(programs, evaluation=evaluation)
        programs_with_evaluation = programs | {"experiment_evaluation": evaluation}
        previous = _load_json(state_path)
        source_refresh_safe = _source_refresh_safe(source_refresh)
        evaluation_refresh_safe = _source_refresh_safe(evaluation_refresh)
        contract_safe = _experiment_programs_contract_safe(programs)
        status = str(programs.get("status") or "")
        should_alert = (
            status not in SAFE_PROGRAM_STATUSES
            or not source_refresh_safe
            or not evaluation_refresh_safe
            or not contract_safe
            or not evaluation_contract_safe
        )
        wake = should_alert and fingerprint != previous.get("fingerprint")
        counters = _mutation_counters(programs)
        active_loops = _active_loop_ids(programs)
        payload = programs_with_evaluation | {
            "task": "torben_finance_experiment_programs",
            "adapter_task": programs.get("task"),
            "wakeAgent": wake,
            "source_refresh_safe": source_refresh_safe,
            "experiment_evaluation_refresh_safe": evaluation_refresh_safe,
            "experiment_programs_contract_safe": contract_safe,
            "experiment_evaluation_contract_safe": evaluation_contract_safe,
            "experiment_evaluation_source_refresh": evaluation_refresh,
            "experiment_programs_fingerprint": fingerprint,
            "previous_experiment_programs_fingerprint": previous.get("fingerprint"),
            "source_refresh": source_refresh,
            "active_loop_count": len(active_loops),
            "active_loop_ids": active_loops,
            "text": _render_text(programs_with_evaluation) if wake else "",
            "live_order_authority": programs.get("live_order_authority") or "none",
            "mutation_counters": counters,
            **counters,
        }
        _write_json(
            state_path,
            {
                "fingerprint": fingerprint,
                "status": programs.get("status"),
                "active_loop_count": len(active_loops),
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-experiment-programs-latest.json",
        text_path=state_dir / "torben-finance-experiment-programs-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


def _fingerprint(payload: dict, *, evaluation: dict | None = None) -> str:
    basis = {
        "status": payload.get("status"),
        "generated_at": payload.get("generated_at"),
        "evidence": _evidence_fingerprint(payload.get("evidence")),
        "loops": _loops_fingerprint(payload),
        "evaluation": _experiment_evaluation_fingerprint(evaluation or {}),
        "live_order_authority": payload.get("live_order_authority"),
        "mutation_counters": _mutation_counters(payload),
        "source_refresh": _source_refresh_fingerprint(payload.get("torben_source_refresh")),
    }
    encoded = json.dumps(basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _evidence_fingerprint(payload: object) -> dict:
    evidence = payload if isinstance(payload, dict) else {}
    return {
        "sample_count": evidence.get("sample_count"),
        "calibrated_sample_count": evidence.get("calibrated_sample_count"),
        "repair_plan_status": evidence.get("repair_plan_status"),
        "repair_target_new_samples": evidence.get("repair_target_new_samples"),
        "repair_preferred_symbols": evidence.get("repair_preferred_symbols") or [],
        "historical_policy_coverage_status": evidence.get("historical_policy_coverage_status"),
        "live_order_authority": evidence.get("live_order_authority"),
    }


def _loops_fingerprint(payload: dict) -> dict:
    loops = payload.get("loops") if isinstance(payload.get("loops"), dict) else {}
    return {
        str(name): {
            "experiment_id": loop.get("experiment_id"),
            "status": loop.get("status"),
            "manual_approval_required": loop.get("manual_approval_required"),
            "live_order_authority": loop.get("live_order_authority"),
            "sample_window": loop.get("sample_window") if isinstance(loop.get("sample_window"), dict) else {},
        }
        for name, loop in sorted(loops.items())
        if isinstance(loop, dict)
    }


def _experiment_evaluation_fingerprint(payload: dict) -> dict:
    loops = payload.get("loops") if isinstance(payload.get("loops"), dict) else {}
    return {
        "status": payload.get("status"),
        "generated_at": payload.get("generated_at"),
        "experiment_programs_generated_at": payload.get("experiment_programs_generated_at"),
        "history_appended_count": payload.get("history_appended_count"),
        "loops": {
            str(name): {
                "status": loop.get("status"),
                "decision": loop.get("decision"),
                "experiment_id": loop.get("experiment_id"),
                "samples_remaining": loop.get("samples_remaining"),
                "live_order_authority": loop.get("live_order_authority"),
            }
            for name, loop in sorted(loops.items())
            if isinstance(loop, dict)
        },
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


def _experiment_programs_contract_safe(payload: dict) -> bool:
    if payload.get("task") != "equity_experiment_programs":
        return False
    if payload.get("status") not in SAFE_PROGRAM_STATUSES:
        return False
    if payload.get("optimization_mode") != "paper_feedback_only":
        return False
    if payload.get("read_only_broker") is not True:
        return False
    if payload.get("live_order_authority") not in {None, "none"}:
        return False
    if payload.get("broker_review_attempted") is not False:
        return False
    if payload.get("broker_place_attempted") is not False:
        return False
    if not _mutation_counters_zero(payload):
        return False
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    if evidence.get("live_order_authority") not in {None, "none"}:
        return False
    loops = payload.get("loops") if isinstance(payload.get("loops"), dict) else {}
    if not loops:
        return False
    for loop in loops.values():
        if not isinstance(loop, dict):
            return False
        if loop.get("status") not in SAFE_LOOP_STATUSES:
            return False
        if loop.get("live_order_authority") not in {None, "none"}:
            return False
    if payload.get("status") == "programs_prepared" and not _active_loop_ids(payload):
        return False
    return True


def _experiment_evaluation_contract_safe(payload: dict, programs: dict) -> bool:
    if payload.get("task") != "equity_experiment_evaluator":
        return False
    if payload.get("status") not in SAFE_EVALUATION_STATUSES:
        return False
    if payload.get("optimization_mode") != "paper_feedback_only":
        return False
    if payload.get("read_only_broker") is not True:
        return False
    if payload.get("live_order_authority") not in {None, "none"}:
        return False
    if payload.get("broker_review_attempted") is not False:
        return False
    if payload.get("broker_place_attempted") is not False:
        return False
    if payload.get("experiment_programs_generated_at") != programs.get("generated_at"):
        return False
    if not _mutation_counters_zero(payload):
        return False
    loops = payload.get("loops") if isinstance(payload.get("loops"), dict) else {}
    if not loops:
        return False
    for loop in loops.values():
        if not isinstance(loop, dict):
            return False
        if loop.get("live_order_authority") not in {None, "none"}:
            return False
    return True


def _active_loop_ids(payload: dict) -> list[str]:
    loops = payload.get("loops") if isinstance(payload.get("loops"), dict) else {}
    return [
        str(loop.get("experiment_id"))
        for loop in loops.values()
        if isinstance(loop, dict) and loop.get("status") == "active" and loop.get("experiment_id")
    ]


def _render_text(payload: dict) -> str:
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    evaluation = payload.get("experiment_evaluation") if isinstance(payload.get("experiment_evaluation"), dict) else {}
    active_loop_ids = _active_loop_ids(payload)
    return (
        "Torben / Finance Experiment Programs\n\n"
        f"Status: {payload.get('status') or 'unknown'}.\n"
        f"Evidence: samples={_display(evidence.get('sample_count'))}; "
        f"calibrated={_display(evidence.get('calibrated_sample_count'))}; "
        f"repair_target={_display(evidence.get('repair_target_new_samples'))}.\n"
        f"Active programs: {_display_list(active_loop_ids)}.\n"
        f"Evaluation: status={_display(evaluation.get('status'))}; "
        f"programs_generated_at={_display(evaluation.get('experiment_programs_generated_at'))}.\n"
        f"Safety: contract_safe={_experiment_programs_contract_safe(payload)}; "
        f"evaluation_safe={_experiment_evaluation_contract_safe(evaluation, payload)}; "
        f"authority={payload.get('live_order_authority') or 'none'}.\n"
        "No broker order was placed, cancelled, modified, reviewed, approved, or submitted.\n"
    )


def _mutation_counters(payload: dict) -> dict:
    counters = payload.get("mutation_counters") if isinstance(payload.get("mutation_counters"), dict) else {}
    return {
        name: int(counters.get(name, payload.get(name, 0)) or 0)
        for name in _zero_mutation_counters()
    }


def _mutation_counters_zero(payload: dict) -> bool:
    counters = _mutation_counters(payload)
    return all(value == 0 for value in counters.values())


def _display(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def _display_list(values: list[str]) -> str:
    return ",".join(values) if values else "none"


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
