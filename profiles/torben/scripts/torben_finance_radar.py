#!/usr/bin/env python3
"""Run Torben's stage-only Ratatosk finance radar."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_cli.signal_coo.action_ledger import ActionLedger
from hermes_cli.signal_coo.automation_policy import finance_automation_decisions
from hermes_cli.signal_coo.finance import (
    DEFAULT_FINANCE_MIN_SCORE,
    DEFAULT_MAX_FINANCE_ITEMS,
    DEFAULT_FINANCE_SCAN_WINDOWS,
    DEFAULT_OPPORTUNITY_UNIVERSE_SCOPE,
    DEFAULT_OPPORTUNITY_UNIVERSE_VERSION,
    build_torben_finance_radar_adapter,
    write_finance_radar_artifacts,
)

DEFAULT_RATATOSK_ROOT = Path("/Users/ericfreeman/ratatosk")
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_RATATOSK_LIVE_TRADING = "0"
DEFAULT_ROBINHOOD_LIVE = "0"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except ValueError:
        return default


def _env_list(name: str, default: tuple[str, ...]) -> list[str]:
    value = str(os.getenv(name) or "").strip()
    if not value:
        return list(default)
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or list(default)


def _default_scan_window() -> str:
    override = str(os.getenv("TORBEN_FINANCE_SCAN_WINDOW") or "").strip()
    if override:
        return override
    phase = str(os.getenv("TORBEN_FINANCE_PHASE") or "").strip()
    if phase:
        return phase
    now = datetime.now(timezone.utc)
    if 13 <= now.hour < 15:
        return "market_open"
    if 15 <= now.hour < 18:
        return "midday"
    if 18 <= now.hour < 21:
        return "late_afternoon"
    return "off_hours"


def _attach_radar_contract_metadata(ratatosk_run: dict) -> None:
    ratatosk_run.setdefault(
        "opportunity_universe_version",
        str(os.getenv("TORBEN_FINANCE_OPPORTUNITY_UNIVERSE_VERSION") or DEFAULT_OPPORTUNITY_UNIVERSE_VERSION),
    )
    ratatosk_run.setdefault(
        "opportunity_universe_scope",
        _env_list("TORBEN_FINANCE_OPPORTUNITY_UNIVERSE_SCOPE", DEFAULT_OPPORTUNITY_UNIVERSE_SCOPE),
    )
    ratatosk_run.setdefault("scan_window", _default_scan_window())
    ratatosk_run.setdefault("scan_windows", _env_list("TORBEN_FINANCE_SCAN_WINDOWS", DEFAULT_FINANCE_SCAN_WINDOWS))


def _ratatosk_legacy_command(*, phase: str | None, dry_run: bool, run_llm: bool, token_budget: int) -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/robinhood_v01_cron_tick.py",
        "--token-budget",
        str(token_budget),
    ]
    if phase:
        command.extend(["--phase", phase])
    if run_llm:
        command.append("--run-llm")
    if dry_run:
        command.append("--dry-run")
    return command


def _ratatosk_equity_packet_command(*, watchlist_path: str) -> list[str]:
    return [
        "uv",
        "run",
        "python",
        "scripts/equity_scan_packet.py",
        "--json",
        "--watchlist",
        watchlist_path,
    ]


def _ratatosk_research_packet_command(*, fixture: str | None = None) -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_research_signal_cron.py",
        "--json",
    ]
    if fixture:
        command.extend(["--fixture", fixture])
    return command


def _extract_json_object(text: str) -> dict:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Ratatosk Robinhood v0.1 tick did not return JSON") from None
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Ratatosk Robinhood v0.1 tick JSON was not an object")
    return payload


def _run_ratatosk_command(command: list[str], *, root: Path, timeout_seconds: int) -> tuple[dict, dict]:
    env = os.environ.copy()
    env.setdefault("UV_PROJECT_ENVIRONMENT", "venv")
    env.setdefault("RATATOSK_LIVE_TRADING", DEFAULT_RATATOSK_LIVE_TRADING)
    env.setdefault("ROBINHOOD_LIVE", DEFAULT_ROBINHOOD_LIVE)
    env.setdefault("ROBINHOOD_EQUITY_LIVE", "0")
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    env["RATATOSK_ROOT"] = str(root)
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    if result.returncode != 0:
        raise RuntimeError(
            "Ratatosk finance evidence command failed "
            f"(returncode={result.returncode}): {(result.stderr or result.stdout)[-500:]}"
        )
    payload = _extract_json_object(result.stdout or "")
    payload["torben_source_refresh"] = {
        "status": "success",
        "profile": "ratatosk",
        "root": str(root),
        "command": command,
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": env.get("RATATOSK_LIVE_TRADING"),
            "ROBINHOOD_LIVE": env.get("ROBINHOOD_LIVE"),
            "ROBINHOOD_EQUITY_LIVE": env.get("ROBINHOOD_EQUITY_LIVE"),
        },
        "stderr_tail": (result.stderr or "")[-500:],
    }
    return payload, payload["torben_source_refresh"]


def _run_ratatosk_tick() -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_RADAR_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_RADAR_FIXTURE must contain a JSON object")
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

    root = Path(os.getenv("TORBEN_FINANCE_RATATOSK_ROOT") or DEFAULT_RATATOSK_ROOT)
    timeout_seconds = _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    if not _truthy(os.getenv("TORBEN_FINANCE_USE_LEGACY_ROBINHOOD_V01")):
        watchlist_path = str(os.getenv("TORBEN_FINANCE_EQUITY_WATCHLIST") or "state/equity-watchlist.json")
        if not _truthy(os.getenv("TORBEN_FINANCE_DISABLE_RESEARCH_CRON")):
            research_fixture = str(os.getenv("TORBEN_FINANCE_RESEARCH_FIXTURE") or "").strip() or None
            try:
                payload, refresh = _run_ratatosk_command(
                    _ratatosk_research_packet_command(fixture=research_fixture),
                    root=root,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                fallback_payload, fallback_refresh = _run_ratatosk_command(
                    _ratatosk_equity_packet_command(watchlist_path=watchlist_path),
                    root=root,
                    timeout_seconds=timeout_seconds,
                )
                fallback_refresh["preferred_source"] = "ratatosk_equity_research_agent_v1"
                fallback_refresh["fallback_reason"] = f"research_cron_unavailable:{type(exc).__name__}"
                fallback_refresh["research_error"] = str(exc)[:300]
                return fallback_payload, fallback_refresh
            if str(payload.get("status") or "") == "data_source_degraded" and not research_fixture:
                fallback_payload, fallback_refresh = _run_ratatosk_command(
                    _ratatosk_equity_packet_command(watchlist_path=watchlist_path),
                    root=root,
                    timeout_seconds=timeout_seconds,
                )
                fallback_refresh["preferred_source"] = "ratatosk_equity_research_agent_v1"
                fallback_refresh["fallback_reason"] = "research_cron_degraded"
                fallback_refresh["research_attempt"] = refresh
                fallback_refresh["research_status"] = payload.get("status")
                return fallback_payload, fallback_refresh
            return payload, refresh

        return _run_ratatosk_command(
            _ratatosk_equity_packet_command(watchlist_path=watchlist_path),
            root=root,
            timeout_seconds=timeout_seconds,
        )

    # Legacy Robinhood v0.1 is retained as a bounded scheduler/control canary,
    # not the default production source for visible FIN candidates.
    phase = str(os.getenv("TORBEN_FINANCE_PHASE") or "").strip() or None
    preview = _truthy(os.getenv("TORBEN_FINANCE_RADAR_PREVIEW"))
    dry_run = preview or _truthy(os.getenv("TORBEN_FINANCE_RATATOSK_DRY_RUN"))
    run_llm = not _truthy(os.getenv("TORBEN_FINANCE_DISABLE_LLM"))
    token_budget = _env_int("TORBEN_FINANCE_TOKEN_BUDGET", 2500)
    payload, refresh = _run_ratatosk_command(
        _ratatosk_legacy_command(phase=phase, dry_run=dry_run, run_llm=run_llm, token_budget=token_budget),
        root=root,
        timeout_seconds=timeout_seconds,
    )
    refresh["dry_run"] = dry_run
    refresh["run_llm"] = run_llm
    refresh["legacy_control_canary"] = True
    return payload, refresh


def _failure_payload(exc: Exception) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "task": "torben_finance_radar",
        "wakeAgent": True,
        "generated_at": now,
        "error": {
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        },
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
        "scan_window": _default_scan_window(),
        "scan_windows": _env_list("TORBEN_FINANCE_SCAN_WINDOWS", DEFAULT_FINANCE_SCAN_WINDOWS),
        "scan_windows_count": len(_env_list("TORBEN_FINANCE_SCAN_WINDOWS", DEFAULT_FINANCE_SCAN_WINDOWS)),
        "opportunity_universe_version": str(
            os.getenv("TORBEN_FINANCE_OPPORTUNITY_UNIVERSE_VERSION") or DEFAULT_OPPORTUNITY_UNIVERSE_VERSION
        ),
        "opportunity_universe_scope": _env_list(
            "TORBEN_FINANCE_OPPORTUNITY_UNIVERSE_SCOPE",
            DEFAULT_OPPORTUNITY_UNIVERSE_SCOPE,
        ),
        "candidate_class_counts": {},
        "underfollowed_signal_count": 0,
        "llm_triggered": False,
        "quiet_scan_llm_triggered": False,
        "llm_trigger_reason": None,
        "no_llm_reason": "source refresh failed before LLM-trigger evaluation",
        "automation_policy": finance_automation_decisions(),
        "auto_invoke_allowed": True,
        "recommendation_status": "auto_surface_allowed",
        "text": (
            "Torben / Finance Radar\n\n"
            "Ratatosk equity evidence refresh failed before it could produce a useful finance review.\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:180]}\n"
            "No broker order was placed, cancelled, modified, or approved.\n"
        ),
    }


def _ensure_preview_canary_candidate(ratatosk_run: dict, *, min_score: float) -> None:
    """Add a synthetic candidate only for explicit preview canaries.

    This validates Torben's Signal/action shape when the live market analysis
    correctly returns no actionable candidate. It must never run in production
    mode because it is not market evidence.
    """

    llm_result = ratatosk_run.get("llm_result")
    if not isinstance(llm_result, dict):
        llm_result = {}
        ratatosk_run["llm_result"] = llm_result
    if isinstance(llm_result.get("candidates"), list) and llm_result["candidates"]:
        return
    llm_result["market_regime"] = llm_result.get("market_regime") or "preview_canary_no_live_market_data"
    llm_result["no_trade_reason"] = (
        llm_result.get("no_trade_reason")
        or "Preview canary candidate only; no live market evidence and no broker tools."
    )
    llm_result["candidates"] = [
        {
            "symbol": "SPY",
            "score": round(max(min_score + 0.01, 0.71), 2),
            "direction": "long",
            "instrument_type": "equity",
            "candidate_type": "preview_canary_fixture",
            "can_place_order_directly": False,
            "eligible_for_pretrade_guard": False,
            "research_note": (
                "Preview canary fixture to verify Torben FIN output shape; "
                "not a real trade recommendation."
            ),
            "constraints": [
                "preview-only",
                "no-broker-order",
                "requires-live-finance-decision",
            ],
        }
    ]


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    preview = _truthy(os.getenv("TORBEN_FINANCE_RADAR_PREVIEW"))
    force_wake = _truthy(os.getenv("TORBEN_FINANCE_RADAR_FORCE_WAKE"))

    try:
        ratatosk_run, source_refresh = _run_ratatosk_tick()
        _attach_radar_contract_metadata(ratatosk_run)
        min_score = _env_float("TORBEN_FINANCE_MIN_SCORE", DEFAULT_FINANCE_MIN_SCORE)
        if preview and force_wake and _truthy(os.getenv("TORBEN_FINANCE_ALLOW_SYNTHETIC_PREVIEW_CANDIDATE")):
            _ensure_preview_canary_candidate(ratatosk_run, min_score=min_score)
        payload = build_torben_finance_radar_adapter(
            ratatosk_run,
            ledger=ActionLedger(state_dir / "torben-action-ledger.jsonl"),
            state_path=state_dir / "torben-finance-radar-state.json",
            min_score=min_score,
            max_items=_env_int("TORBEN_FINANCE_MAX_ITEMS", DEFAULT_MAX_FINANCE_ITEMS),
            mark_delivered=not preview,
            stage_actions=not preview,
            force_wake=force_wake,
        )
        payload["source_refresh"] = source_refresh
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-radar-latest.json",
        text_path=state_dir / "torben-finance-radar-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
