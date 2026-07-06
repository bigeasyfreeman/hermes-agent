#!/usr/bin/env python3
"""Run Torben's live-disabled Ratatosk repair-window simulator."""

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


PASS_REQUIRED_CHECKS = (
    "active_repair_plan",
    "isolated_state_root",
    "source_state_sample_artifacts_unchanged",
    "tick_completed",
    "research_batch_succeeded",
    "research_selected_requested_samples",
    "sample_collector_collected",
    "sample_budget_open",
    "created_requested_canaries",
    "observed_requested_outcomes",
    "created_symbols_from_repair_plan",
    "live_order_authority_none",
    "zero_mutation_counters",
    "broker_review_not_attempted",
    "broker_place_not_attempted",
)
SKIPPED_SAFE_REASONS = {"no_active_repair_plan", "repair_plan_requested_zero_samples"}


def _zero_mutation_counters() -> dict:
    return {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _ratatosk_repair_window_simulator_command() -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_repair_window_simulator.py",
        "--json",
    ]
    state_root = str(os.getenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_STATE_ROOT") or "").strip()
    if state_root:
        command.extend(["--state-root", state_root])
    simulation_root = str(
        os.getenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_SIMULATION_ROOT")
        or os.getenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_ROOT")
        or ""
    ).strip()
    if simulation_root:
        command.extend(["--simulation-root", simulation_root])
    output_path = str(os.getenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_OUTPUT_PATH") or "").strip()
    if output_path:
        command.extend(["--output-path", output_path])
    max_samples = _env_int("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_MAX_SAMPLES", 0)
    if max_samples > 0:
        command.extend(["--max-samples", str(max_samples)])
    if _truthy(os.getenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_NO_PERSIST")):
        command.append("--no-persist")
    return command


def _run_ratatosk_repair_window_simulator() -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_FIXTURE must contain a JSON object")
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
            },
        )
        payload["torben_source_refresh"] = source_refresh
        return payload, source_refresh

    root = Path(
        os.getenv("TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_REPAIR_WINDOW_SIMULATOR_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    return _run_ratatosk_command(
        _ratatosk_repair_window_simulator_command(),
        root=root,
        timeout_seconds=timeout_seconds,
    )


def _failure_payload(exc: Exception) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    counters = _zero_mutation_counters()
    return {
        "task": "torben_finance_repair_window_simulator",
        "wakeAgent": True,
        "generated_at": now,
        "status": "error",
        "error": {
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        },
        "source_refresh_safe": False,
        "simulation_contract_safe": False,
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
        "text": (
            "Torben / Finance Repair Window Simulator\n\n"
            "Ratatosk repair-window simulation failed before it could persist a useful status packet.\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:180]}\n"
            "Live trading env remained RATATOSK_LIVE_TRADING=0 and ROBINHOOD_LIVE=0.\n"
            "No broker order was placed, cancelled, modified, reviewed, approved, or submitted.\n"
        ),
    }


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "torben-finance-repair-window-simulator-state.json"

    try:
        simulation, source_refresh = _run_ratatosk_repair_window_simulator()
        fingerprint = _fingerprint(simulation)
        previous = _load_json(state_path)
        source_refresh_safe = _source_refresh_safe(source_refresh)
        simulation_contract_safe = _repair_window_simulation_contract_safe(simulation)
        should_alert = (
            str(simulation.get("status") or "") in {"fail", "error"}
            or not source_refresh_safe
            or not simulation_contract_safe
        )
        wake = should_alert and fingerprint != previous.get("fingerprint")
        counters = _zero_mutation_counters()
        payload = simulation | {
            "task": "torben_finance_repair_window_simulator",
            "adapter_task": simulation.get("task"),
            "wakeAgent": wake,
            "source_refresh_safe": source_refresh_safe,
            "simulation_contract_safe": simulation_contract_safe,
            "repair_window_simulation_fingerprint": fingerprint,
            "previous_repair_window_simulation_fingerprint": previous.get("fingerprint"),
            "source_refresh": source_refresh,
            "text": _render_text(simulation) if wake else "",
            "live_order_authority": "none",
            "mutation_counters": counters,
            **counters,
        }
        _write_json(
            state_path,
            {
                "fingerprint": fingerprint,
                "status": simulation.get("status"),
                "reason": simulation.get("reason"),
                "errors": simulation.get("errors") or [],
                "requested_samples": simulation.get("requested_samples"),
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-repair-window-simulator-latest.json",
        text_path=state_dir / "torben-finance-repair-window-simulator-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


def _fingerprint(payload: dict) -> str:
    basis = {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "errors": payload.get("errors") or [],
        "repair_plan_source": payload.get("repair_plan_source"),
        "repair_plan": payload.get("repair_plan") if isinstance(payload.get("repair_plan"), dict) else {},
        "requested_samples": payload.get("requested_samples"),
        "preferred_symbols": payload.get("preferred_symbols") or [],
        "candidate_symbols": payload.get("candidate_symbols") or [],
        "checks": payload.get("checks") if isinstance(payload.get("checks"), dict) else {},
        "broker_review_attempted": payload.get("broker_review_attempted"),
        "broker_place_attempted": payload.get("broker_place_attempted"),
        "live_order_authority": payload.get("live_order_authority"),
        "mutation_counters": _mutation_counters(payload),
        "source_refresh": _source_refresh_fingerprint(payload.get("torben_source_refresh")),
    }
    encoded = json.dumps(basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _source_refresh_fingerprint(payload: object) -> dict:
    refresh = payload if isinstance(payload, dict) else {}
    env = refresh.get("live_safety_env") if isinstance(refresh.get("live_safety_env"), dict) else {}
    return {
        "status": refresh.get("status"),
        "returncode": refresh.get("returncode"),
        "ratatosk_live_trading": env.get("RATATOSK_LIVE_TRADING"),
        "robinhood_live": env.get("ROBINHOOD_LIVE"),
    }


def _source_refresh_safe(payload: dict) -> bool:
    env = payload.get("live_safety_env") if isinstance(payload.get("live_safety_env"), dict) else {}
    return (
        payload.get("status") == "success"
        and int(payload.get("returncode") or 0) == 0
        and env.get("RATATOSK_LIVE_TRADING") == "0"
        and env.get("ROBINHOOD_LIVE") == "0"
    )


def _repair_window_simulation_contract_safe(payload: dict) -> bool:
    if payload.get("live_order_authority") not in {None, "none"}:
        return False
    if payload.get("broker_review_attempted") is not False:
        return False
    if payload.get("broker_place_attempted") is not False:
        return False
    if not _mutation_counters_zero(payload):
        return False

    status = str(payload.get("status") or "")
    reason = str(payload.get("reason") or "")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if status == "pass":
        return all(checks.get(name) is True for name in PASS_REQUIRED_CHECKS)
    if status == "skipped":
        return (
            reason in SKIPPED_SAFE_REASONS
            and checks.get("isolated_state_root") is True
            and checks.get("source_state_sample_artifacts_unchanged") is True
            and checks.get("live_order_authority_none") is True
            and checks.get("zero_mutation_counters") is True
            and checks.get("broker_review_not_attempted") is True
            and checks.get("broker_place_not_attempted") is True
        )
    return False


def _render_text(payload: dict) -> str:
    status = str(payload.get("status") or "unknown")
    reason = str(payload.get("reason") or "unknown")
    errors = [str(item) for item in payload.get("errors") or [] if str(item or "").strip()]
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed_checks = [name for name, passed in sorted(checks.items()) if passed is not True]
    lines = [
        "Torben / Finance Repair Window Simulator",
        "",
        f"Status: {status}.",
        f"Reason: {reason}.",
        f"Repair plan source: {payload.get('repair_plan_source') or 'unknown'}.",
        f"Requested samples: {payload.get('requested_samples') or 0}.",
        f"Candidate symbols: {_display_symbols(payload.get('candidate_symbols'))}.",
        f"Simulation root: {payload.get('simulation_state_root') or 'none'}.",
        (
            "Safety: "
            f"source_unchanged={checks.get('source_state_sample_artifacts_unchanged') is True}; "
            f"isolated_root={checks.get('isolated_state_root') is True}; "
            f"authority={payload.get('live_order_authority') or 'none'}."
        ),
        "No broker order was placed, cancelled, modified, reviewed, approved, or submitted.",
    ]
    if failed_checks:
        lines.extend(["", "Failed simulation checks:", *[f"- {item}" for item in failed_checks[:8]]])
    if errors:
        lines.extend(["", "Errors:", *[f"- {item}" for item in errors[:8]]])
    return "\n".join(lines).rstrip() + "\n"


def _display_symbols(value: object) -> str:
    symbols = [str(item).strip().upper() for item in value or [] if str(item or "").strip()]
    return ",".join(symbols) if symbols else "none"


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


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
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
