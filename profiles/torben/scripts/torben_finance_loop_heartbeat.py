#!/usr/bin/env python3
"""Run Torben's quiet Ratatosk trading-loop heartbeat."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_cli.signal_coo.action_ledger import ActionLedger
from hermes_cli.signal_coo.finance import (
    DEFAULT_FINANCE_MIN_SCORE,
    DEFAULT_MAX_FINANCE_ITEMS,
    build_torben_finance_radar_adapter,
    write_finance_radar_artifacts,
)

DEFAULT_LOOP_HEARTBEAT_MAX_RESEARCH_CANDIDATES = 3
DEFAULT_LOOP_HEARTBEAT_MAX_SAMPLE_CANDIDATES = 3
DEFAULT_LOOP_HEARTBEAT_MAX_SAMPLE_OUTCOMES = 3

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


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_stop_condition(payload: dict) -> dict:
    stop_condition = payload.get("stop_condition")
    if isinstance(stop_condition, dict):
        return stop_condition
    loop_heartbeat = payload.get("loop_heartbeat")
    if isinstance(loop_heartbeat, dict) and isinstance(loop_heartbeat.get("stop_condition"), dict):
        return loop_heartbeat["stop_condition"]
    return {}


def _failure_stop_condition(state_dir: Path | None) -> dict:
    previous = _load_json(state_dir / "torben-finance-loop-heartbeat-latest.json") if state_dir else {}
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
            "primary_next_action": "restore_ratatosk_source_refresh",
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
        _env_float,
        _env_int,
        _extract_json_object,
        _run_ratatosk_command,
        _truthy,
    )
except ImportError:  # Direct script execution from HERMES_HOME/scripts.
    from torben_finance_radar import (  # type: ignore[no-redef]
        DEFAULT_RATATOSK_ROOT,
        DEFAULT_TIMEOUT_SECONDS,
        _env_float,
        _env_int,
        _extract_json_object,
        _run_ratatosk_command,
        _truthy,
    )


def _ratatosk_loop_tick_command() -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_trading_loop_tick.py",
        "--json",
    ]
    state_root = str(os.getenv("TORBEN_FINANCE_LOOP_HEARTBEAT_STATE_ROOT") or "").strip()
    if state_root:
        command.extend(["--state-root", state_root])
    fixture = str(os.getenv("TORBEN_FINANCE_LOOP_HEARTBEAT_RATATOSK_FIXTURE") or "").strip()
    if fixture:
        command.extend(["--fixture", fixture])
    if _truthy(os.getenv("TORBEN_FINANCE_LOOP_HEARTBEAT_SKIP_STATUS")):
        command.append("--skip-status")
    if _truthy(os.getenv("TORBEN_FINANCE_LOOP_HEARTBEAT_SKIP_OUTCOME")):
        command.append("--skip-outcome")
    command.extend(
        [
            "--max-research-candidates",
            str(
                _env_int(
                    "TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_RESEARCH_CANDIDATES",
                    DEFAULT_LOOP_HEARTBEAT_MAX_RESEARCH_CANDIDATES,
                )
            ),
            "--max-sample-candidates",
            str(
                _env_int(
                    "TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_SAMPLE_CANDIDATES",
                    DEFAULT_LOOP_HEARTBEAT_MAX_SAMPLE_CANDIDATES,
                )
            ),
            "--max-sample-outcomes",
            str(
                _env_int(
                    "TORBEN_FINANCE_LOOP_HEARTBEAT_MAX_SAMPLE_OUTCOMES",
                    DEFAULT_LOOP_HEARTBEAT_MAX_SAMPLE_OUTCOMES,
                )
            ),
        ]
    )
    return command


def _run_ratatosk_loop_tick() -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_LOOP_HEARTBEAT_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_LOOP_HEARTBEAT_FIXTURE must contain a JSON object")
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

    root = Path(
        os.getenv("TORBEN_FINANCE_LOOP_HEARTBEAT_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_LOOP_HEARTBEAT_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    return _run_ratatosk_command(
        _ratatosk_loop_tick_command(),
        root=root,
        timeout_seconds=timeout_seconds,
    )


def _failure_payload(exc: Exception, *, state_dir: Path | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    counters = _zero_mutation_counters()
    source_refresh = _failure_source_refresh(exc)
    stop_condition = _failure_stop_condition(state_dir)
    return {
        "task": "torben_finance_loop_heartbeat",
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
        "loop_heartbeat": {"present": False, "stop_condition": stop_condition},
        "paper_outcome": {"present": False},
        "paper_performance": {"present": False},
        "signal_optimizer": {"present": False},
        "live_status": {"present": False, "ready_to_submit": False},
        "risk_incident": {"present": False},
        **counters,
        "text": (
            "Torben / Finance Loop Heartbeat\n\n"
            "Ratatosk trading-loop heartbeat failed before it could persist a useful status packet.\n"
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

    try:
        loop_tick, source_refresh = _run_ratatosk_loop_tick()
        payload = build_torben_finance_radar_adapter(
            loop_tick,
            ledger=ActionLedger(state_dir / "torben-action-ledger.jsonl"),
            state_path=state_dir / "torben-finance-loop-heartbeat-state.json",
            min_score=_env_float("TORBEN_FINANCE_MIN_SCORE", DEFAULT_FINANCE_MIN_SCORE),
            max_items=_env_int("TORBEN_FINANCE_MAX_ITEMS", DEFAULT_MAX_FINANCE_ITEMS),
            mark_delivered=False,
            stage_actions=False,
            force_wake=_truthy(os.getenv("TORBEN_FINANCE_LOOP_HEARTBEAT_FORCE_WAKE")),
        )
        payload["adapter_task"] = payload.get("task")
        payload["task"] = "torben_finance_loop_heartbeat"
        payload["heartbeat_mode"] = "status_only"
        payload["source_refresh"] = source_refresh
        payload["stage_actions"] = False
        payload["mark_delivered"] = False
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc, state_dir=state_dir)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-loop-heartbeat-latest.json",
        text_path=state_dir / "torben-finance-loop-heartbeat-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
