#!/usr/bin/env python3
"""Run Torben's live-disabled Ratatosk go-live operator packet."""

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


def _ratatosk_go_live_packet_command() -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "scripts/equity_go_live_packet.py",
    ]
    signal_id = str(os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_SIGNAL_ID") or "").strip()
    if signal_id:
        command.extend(["--signal-id", signal_id])
    elif _truthy(os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_LATEST_RESEARCH_CANDIDATE", "1")):
        command.append("--latest-research-candidate")

    state_root = str(os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_STATE_ROOT") or "").strip()
    if state_root:
        command.extend(["--state-root", state_root])

    output_path = str(os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_OUTPUT") or "").strip()
    if output_path:
        command.extend(["--output", output_path])

    if _truthy(os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_NO_WRITE")):
        command.append("--no-write")
    if not _truthy(os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_MCP_LIVE_PROBE")):
        command.append("--skip-mcp-live-probe")
    command.append("--json")
    return command


def _run_ratatosk_go_live_packet() -> tuple[dict, dict]:
    fixture_path = str(os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_FIXTURE") or "").strip()
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TORBEN_FINANCE_GO_LIVE_PACKET_FIXTURE must contain a JSON object")
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
        os.getenv("TORBEN_FINANCE_GO_LIVE_PACKET_RATATOSK_ROOT")
        or os.getenv("TORBEN_FINANCE_RATATOSK_ROOT")
        or DEFAULT_RATATOSK_ROOT
    )
    timeout_seconds = _env_int(
        "TORBEN_FINANCE_GO_LIVE_PACKET_TIMEOUT_SECONDS",
        _env_int("TORBEN_FINANCE_RATATOSK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    return _run_ratatosk_command(
        _ratatosk_go_live_packet_command(),
        root=root,
        timeout_seconds=timeout_seconds,
    )


def _failure_payload(exc: Exception) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    counters = _zero_mutation_counters()
    return {
        "task": "torben_finance_go_live_packet",
        "wakeAgent": True,
        "generated_at": now,
        "status": "error",
        "ready_to_submit": False,
        "go_live_blocked": True,
        "error": {
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        },
        "source_refresh_safe": False,
        "go_live_packet_contract_safe": False,
        "read_only": True,
        "broker_review_attempted": False,
        "broker_place_attempted": False,
        "approval_created": False,
        "approval_modified": False,
        "halt_or_circuit_cleared": False,
        "live_flags_enabled": False,
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
        "text": (
            "Torben / Finance Go-Live Packet\n\n"
            "Ratatosk go-live operator packet failed before it could persist a useful status packet.\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:180]}\n"
            "Live trading env remained RATATOSK_LIVE_TRADING=0, ROBINHOOD_LIVE=0, "
            "and ROBINHOOD_EQUITY_LIVE=0.\n"
            "No approval was created or modified, no halt was cleared, and no broker order was placed.\n"
        ),
    }


def main() -> int:
    home = get_hermes_home()
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "torben-finance-go-live-packet-state.json"

    try:
        packet, source_refresh = _run_ratatosk_go_live_packet()
        fingerprint = _fingerprint(packet)
        previous = _load_json(state_path)
        source_refresh_safe = _source_refresh_safe(source_refresh)
        packet_contract_safe = _go_live_packet_contract_safe(packet)
        should_alert = (
            packet.get("ready_to_submit") is True
            or packet.get("go_live_blocked") is not True
            or str(packet.get("status") or "") in {"ready_to_submit", "error"}
            or not source_refresh_safe
            or not packet_contract_safe
        )
        wake = should_alert and fingerprint != previous.get("fingerprint")
        counters = _mutation_counters(packet)
        payload = packet | {
            "task": "torben_finance_go_live_packet",
            "adapter_task": packet.get("task"),
            "wakeAgent": wake,
            "source_refresh_safe": source_refresh_safe,
            "go_live_packet_contract_safe": packet_contract_safe,
            "go_live_packet_fingerprint": fingerprint,
            "previous_go_live_packet_fingerprint": previous.get("fingerprint"),
            "source_refresh": source_refresh,
            "text": _render_text(packet) if wake else "",
            "live_order_authority": "none",
            "mutation_counters": counters,
            **counters,
        }
        _write_json(
            state_path,
            {
                "fingerprint": fingerprint,
                "status": packet.get("status"),
                "ready_to_submit": packet.get("ready_to_submit"),
                "go_live_blocked": packet.get("go_live_blocked"),
                "resolved_signal_id": packet.get("resolved_signal_id"),
                "blockers": packet.get("blockers") or [],
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failure_payload(exc)

    write_finance_radar_artifacts(
        payload,
        json_path=state_dir / "torben-finance-go-live-packet-latest.json",
        text_path=state_dir / "torben-finance-go-live-packet-latest.txt",
    )
    if payload.get("wakeAgent") and payload.get("text"):
        print(str(payload["text"]), end="")
    return 0


def _fingerprint(payload: dict) -> str:
    gate = _dict_value(_dict_value(payload.get("command_gates")).get("one_shot_live_submit"))
    mandate = _dict_value(payload.get("operator_mandate"))
    approval = _dict_value(payload.get("approval"))
    evidence_gates = _dict_value(payload.get("evidence_gates"))
    basis = {
        "status": payload.get("status"),
        "ready_to_submit": payload.get("ready_to_submit"),
        "go_live_blocked": payload.get("go_live_blocked"),
        "resolved_signal_id": payload.get("resolved_signal_id"),
        "blockers": payload.get("blockers") or [],
        "command_gate": {
            "available": gate.get("available"),
            "reason": gate.get("reason"),
            "blocked_by": gate.get("blocked_by") or [],
        },
        "operator_mandate": {
            "required_approval_scope": mandate.get("required_approval_scope"),
            "self_approval_allowed": mandate.get("self_approval_allowed"),
        },
        "approval": {
            "approval_scope": approval.get("approval_scope"),
            "approved": approval.get("approved"),
            "approved_by_present": approval.get("approved_by_present"),
            "approved_at_present": approval.get("approved_at_present"),
            "account_number_present": approval.get("account_number_present"),
            "risk_acknowledgement_complete": approval.get("risk_acknowledgement_complete"),
        },
        "evidence_gate_statuses": {
            name: _dict_value(gate_payload).get("passed")
            for name, gate_payload in evidence_gates.items()
        },
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


def _go_live_packet_contract_safe(payload: dict) -> bool:
    gate = _dict_value(_dict_value(payload.get("command_gates")).get("one_shot_live_submit"))
    commands = _dict_value(payload.get("commands"))
    mandate = _dict_value(payload.get("operator_mandate"))
    status = str(payload.get("status") or "").strip()
    ready = payload.get("ready_to_submit") is True
    blocked = payload.get("go_live_blocked") is True
    if payload.get("task") != "equity_go_live_operator_packet":
        return False
    if payload.get("schema_version") != "equity_go_live_operator_packet_v1":
        return False
    if payload.get("read_only") is not True:
        return False
    if payload.get("broker_review_attempted") is not False or payload.get("broker_place_attempted") is not False:
        return False
    if payload.get("approval_created") is not False or payload.get("approval_modified") is not False:
        return False
    if payload.get("halt_or_circuit_cleared") is not False or payload.get("live_flags_enabled") is not False:
        return False
    if mandate.get("human_approval_required") is not True:
        return False
    if mandate.get("self_approval_allowed") is not False:
        return False
    if mandate.get("required_approval_scope") != "one_shot_live_canary":
        return False
    if not _mutation_counters_zero(payload):
        return False
    if status == "blocked":
        return (
            not ready
            and blocked
            and gate.get("available") is False
            and commands.get("one_shot_live_submit") is None
        )
    if status == "ready_to_submit":
        return (
            ready
            and not blocked
            and gate.get("available") is True
            and _one_shot_live_submit_command_safe(commands.get("one_shot_live_submit"))
        )
    return False


def _one_shot_live_submit_command_safe(command: object) -> bool:
    text = str(command or "")
    return (
        "RATATOSK_LIVE_TRADING=true" in text
        and "ROBINHOOD_LIVE=true" in text
        and "ROBINHOOD_EQUITY_LIVE=true" in text
    )


def _render_text(payload: dict) -> str:
    gate = _dict_value(_dict_value(payload.get("command_gates")).get("one_shot_live_submit"))
    mandate = _dict_value(payload.get("operator_mandate"))
    blockers = [str(item) for item in payload.get("blockers") or [] if str(item or "").strip()]
    lines = [
        "Torben / Finance Go-Live Packet",
        "",
        f"Status: {payload.get('status') or 'unknown'}.",
        f"Resolved signal: {payload.get('resolved_signal_id') or 'none'}.",
        (
            "Readiness: "
            f"ready_to_submit={payload.get('ready_to_submit') is True}; "
            f"go_live_blocked={payload.get('go_live_blocked') is True}; "
            f"one_shot_live_submit_available={gate.get('available') is True}."
        ),
        (
            "Operator mandate: "
            f"approval_scope={mandate.get('required_approval_scope') or 'missing'}; "
            f"self_approval_allowed={mandate.get('self_approval_allowed') is True}."
        ),
        (
            "Safety: "
            f"read_only={payload.get('read_only') is True}; "
            f"broker_review_attempted={payload.get('broker_review_attempted') is True}; "
            f"broker_place_attempted={payload.get('broker_place_attempted') is True}; "
            f"approval_created={payload.get('approval_created') is True}; "
            f"approval_modified={payload.get('approval_modified') is True}."
        ),
        "No approval was created or modified, no halt was cleared, and no broker order was placed.",
    ]
    if blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in blockers[:8]]])
    return "\n".join(lines).rstrip() + "\n"


def _mutation_counters(payload: dict) -> dict:
    counters = payload.get("mutation_counters") if isinstance(payload.get("mutation_counters"), dict) else payload
    return {
        key: int(counters.get(key, 0) or 0)
        for key in _zero_mutation_counters()
    }


def _mutation_counters_zero(payload: dict) -> bool:
    return all(value == 0 for value in _mutation_counters(payload).values())


def _dict_value(value: object) -> dict:
    return value if isinstance(value, dict) else {}


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
