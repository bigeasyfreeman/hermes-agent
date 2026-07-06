#!/usr/bin/env python3
"""Run Torben's live-disabled Ratatosk finance next-wake runner."""

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


def _zero_mutation_counters() -> dict:
    return {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _ratatosk_next_wake_runner_command(execute: bool | None = None) -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_next_wake_runner.py",
        "--json",
    ]
    state_root = str(os.getenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_STATE_ROOT") or "").strip()
    if state_root:
        command.extend(["--state-root", state_root])
    repo_root = str(os.getenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_REPO_ROOT") or "").strip()
    if repo_root:
        command.extend(["--repo-root", repo_root])
    if execute is None:
        execute_value = str(os.getenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_EXECUTE") or "1")
        execute = _truthy(execute_value)
    if execute:
        command.append("--execute")
    return command


def _run_ratatosk_next_wake_runner(execute: bool | None = None) -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_NEXT_WAKE_RUNNER_FIXTURE must contain a JSON object")
        source_refresh = payload.get("torben_source_refresh")
        source_refresh = dict(source_refresh) if isinstance(source_refresh, dict) else {}
        source_refresh.setdefault("status", "success")
        source_refresh.setdefault("profile", "fixture")
        source_refresh.setdefault("root", fixture_path)
        source_refresh.setdefault("command", ["fixture", fixture_path])
        if execute is not None:
            source_refresh["command"] = _ratatosk_next_wake_runner_command(execute=execute)
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
        os.getenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_NEXT_WAKE_RUNNER_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    return _run_ratatosk_command(
        _ratatosk_next_wake_runner_command(execute=execute),
        root=root,
        timeout_seconds=timeout_seconds,
    )


def _run_ratatosk_next_wake_runner_with_policy() -> tuple[dict, dict]:
    if not _truthy(str(os.getenv("TORBEN_FINANCE_NEXT_WAKE_RUNNER_BLOCK_BOUNDED") or "")):
        return _run_ratatosk_next_wake_runner()

    runner, source_refresh = _run_ratatosk_next_wake_runner(execute=False)
    if _bounded_collection_requested(runner):
        return _bounded_collection_held_payload(runner, source_refresh), source_refresh
    if runner.get("due") is True:
        return _run_ratatosk_next_wake_runner(execute=True)
    return runner, source_refresh


def _bounded_collection_requested(payload: dict) -> bool:
    safe_command_ids = {
        str(item)
        for item in payload.get("safe_command_ids") or []
        if str(item or "").strip()
    }
    return (
        payload.get("ready_now") is True
        or (payload.get("due") is True and "bounded_paper_sample_collection" in safe_command_ids)
        or payload.get("required_operator_action") == "collect_bounded_paper_samples"
    )


def _bounded_collection_held_payload(payload: dict, source_refresh: dict) -> dict:
    counters = _zero_mutation_counters()
    held = dict(payload)
    held.update(
        {
            "status": "held_bounded_collection_offhours",
            "errors": [],
            "execute_requested": False,
            "execution_attempted": False,
            "offhours_recheck_mode": True,
            "offhours_bounded_collection_blocked": True,
            "execution_block_reason": "bounded_paper_sample_collection_disabled_for_offhours_recheck",
            "command_results": [],
            "commands_live_disabled": True,
            "broker_submit_allowed": False,
            "human_live_review_allowed": False,
            "live_order_authority": "none",
            "torben_source_refresh": source_refresh,
            "mutation_counters": counters,
            **counters,
        }
    )
    return held


def _failure_payload(exc: Exception) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    counters = _zero_mutation_counters()
    return {
        "task": "torben_finance_next_wake_runner",
        "wakeAgent": True,
        "generated_at": now,
        "status": "error",
        "error": {
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        },
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
        "text": (
            "Torben / Finance Next Wake Runner\n\n"
            "Ratatosk next-wake runner failed before it could persist a useful status packet.\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:180]}\n"
            "Live trading env remained RATATOSK_LIVE_TRADING=0, ROBINHOOD_LIVE=0, and ROBINHOOD_EQUITY_LIVE=0.\n"
            "No broker order was placed, cancelled, modified, reviewed, approved, or submitted.\n"
        ),
    }


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "torben-finance-next-wake-runner-state.json"

    try:
        runner, source_refresh = _run_ratatosk_next_wake_runner_with_policy()
        fingerprint = _fingerprint(runner)
        previous = _load_json(state_path)
        source_refresh_safe = _source_refresh_safe(source_refresh)
        runner_contract_safe = _runner_contract_safe(runner)
        should_alert = (
            str(runner.get("status") or "") in {"blocked", "command_failed", "error"}
            or not source_refresh_safe
            or not runner_contract_safe
        )
        wake = should_alert and fingerprint != previous.get("fingerprint")
        payload = runner | {
            "task": "torben_finance_next_wake_runner",
            "adapter_task": runner.get("task"),
            "wakeAgent": wake,
            "source_refresh_safe": source_refresh_safe,
            "runner_contract_safe": runner_contract_safe,
            "next_wake_runner_fingerprint": fingerprint,
            "previous_next_wake_runner_fingerprint": previous.get("fingerprint"),
            "source_refresh": source_refresh,
            "text": _render_text(runner) if wake else "",
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
            "live_order_authority": "none",
        }
        _write_json(
            state_path,
            {
                "fingerprint": fingerprint,
                "status": runner.get("status"),
                "errors": runner.get("errors") or [],
                "next_recheck_after_utc": runner.get("next_recheck_after_utc"),
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-next-wake-runner-latest.json",
        text_path=state_dir / "torben-finance-next-wake-runner-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


def _fingerprint(payload: dict) -> str:
    basis = {
        "status": payload.get("status"),
        "errors": payload.get("errors") or [],
        "due": payload.get("due"),
        "ready_now": payload.get("ready_now"),
        "next_recheck_after_utc": payload.get("next_recheck_after_utc"),
        "bounded_collection_not_before_utc": payload.get("bounded_collection_not_before_utc"),
        "budget_reopens_after_utc": payload.get("budget_reopens_after_utc"),
        "market_scan_recheck_after_utc": payload.get("market_scan_recheck_after_utc"),
        "required_operator_action": payload.get("required_operator_action"),
        "wake_reason_ids": payload.get("wake_reason_ids") or [],
        "commands_live_disabled": payload.get("commands_live_disabled"),
        "broker_submit_allowed": payload.get("broker_submit_allowed"),
        "human_live_review_allowed": payload.get("human_live_review_allowed"),
        "live_order_authority": payload.get("live_order_authority"),
        "source_refresh": _source_refresh_fingerprint(payload.get("torben_source_refresh")),
        "safe_command_ids": payload.get("safe_command_ids") or [],
        "command_results": [
            {
                "command_id": item.get("command_id"),
                "returncode": item.get("returncode"),
            }
            for item in payload.get("command_results") or []
            if isinstance(item, dict)
        ],
        "offhours_bounded_collection_blocked": payload.get("offhours_bounded_collection_blocked") is True,
        "execution_block_reason": payload.get("execution_block_reason"),
        "mutation_counters": {
            "public_actions_taken": payload.get("public_actions_taken"),
            "external_mutations": payload.get("external_mutations"),
            "orders_submitted": payload.get("orders_submitted"),
            "broker_orders_submitted": payload.get("broker_orders_submitted"),
        },
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


def _runner_contract_safe(payload: dict) -> bool:
    return (
        payload.get("commands_live_disabled") is True
        and payload.get("broker_submit_allowed") is False
        and payload.get("human_live_review_allowed") is False
        and (payload.get("live_order_authority") in {None, "none"})
        and _mutation_counters_zero(payload)
    )


def _render_text(payload: dict) -> str:
    status = str(payload.get("status") or "unknown")
    errors = [str(item) for item in payload.get("errors") or [] if str(item or "").strip()]
    results = [item for item in payload.get("command_results") or [] if isinstance(item, dict)]
    failed_results = [item for item in results if int(item.get("returncode") or 0) != 0]
    lines = [
        "Torben / Finance Next Wake Runner",
        "",
        f"Status: {status}.",
        f"Next recheck: {payload.get('next_recheck_after_utc') or 'unknown'}.",
        f"Market scan recheck: {payload.get('market_scan_recheck_after_utc') or 'unknown'}.",
        f"Bounded collection not before: {payload.get('bounded_collection_not_before_utc') or 'unknown'}.",
        (
            "Execution: "
            f"requested={bool(payload.get('execute_requested'))}; "
            f"attempted={bool(payload.get('execution_attempted'))}; "
            f"failed_commands={len(failed_results)}."
        ),
        (
            "Safety: "
            f"commands_live_disabled={payload.get('commands_live_disabled') is True}; "
            f"broker_submit_allowed={payload.get('broker_submit_allowed') is True}; "
            f"human_live_review_allowed={payload.get('human_live_review_allowed') is True}; "
            f"authority={payload.get('live_order_authority') or 'none'}."
        ),
        "No broker order was placed, cancelled, modified, reviewed, approved, or submitted.",
    ]
    if errors:
        lines.extend(["", "Errors:", *[f"- {item}" for item in errors[:6]]])
    if failed_results:
        lines.extend(
            [
                "",
                "Failed rechecks:",
                *[
                    f"- {item.get('command_id') or 'unknown'}: returncode={item.get('returncode')}"
                    for item in failed_results[:6]
                ],
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _mutation_counters_zero(payload: dict) -> bool:
    counters = payload.get("mutation_counters") if isinstance(payload.get("mutation_counters"), dict) else payload
    return all(int(counters.get(key, 0) or 0) == 0 for key in _zero_mutation_counters())


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
