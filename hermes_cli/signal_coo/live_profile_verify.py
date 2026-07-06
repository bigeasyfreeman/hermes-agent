"""Live Torben profile verification helpers."""

from __future__ import annotations

import hashlib
import json
import py_compile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .submanager_contracts import validate_torben_submanager_contracts

GMAIL_WATCH_RENEWAL_FLOOR = timedelta(hours=48)
GMAIL_PUBSUB_PULL_FRESHNESS = timedelta(minutes=10)
HYGIENE_REVIEW_MAX_AGE = timedelta(days=8)
BACKEND_ARTIFACT_JOB_ALIGNMENT_TOLERANCE = timedelta(minutes=5)
SOURCE_PROFILE_ALIGNMENT_TOLERANCE = timedelta(minutes=5)
SOURCE_PROFILE_FUTURE_TOLERANCE = timedelta(seconds=5)
ALERT_STATE_VERSION = 1
INVESTIGATION_REQUEST_VERSION = 1
WAIT_FOR_EVIDENCE_ACTION_ID = "wait_for_oos_or_market_data"
BOUNDED_PAPER_ACTION_ID = "run_bounded_paper_optimization_window"
BOUNDED_PAPER_PRIMARY_ACTION_ID = "run_bounded_paper_sample_collection"
REQUIRED_MUTATION_COUNTERS = (
    "public_actions_taken",
    "external_mutations",
    "orders_submitted",
    "broker_orders_submitted",
)
REQUIRED_FINANCE_CRON_SNAPSHOT_JOBS = {
    "torben-finance-radar": "torben_finance_radar.py",
    "torben-finance-loop-heartbeat": "torben_finance_loop_heartbeat.py",
    "torben-finance-next-wake-runner": "torben_finance_next_wake_runner.py",
    "torben-finance-next-wake-offhours-recheck": "torben_finance_next_wake_offhours_recheck.py",
    "torben-finance-go-live-packet": "torben_finance_go_live_packet.py",
    "torben-finance-repair-window-simulator": "torben_finance_repair_window_simulator.py",
    "torben-finance-market-open-sample-acquisition": "torben_finance_loop_heartbeat.py",
    "torben-finance-sample-collector": "torben_finance_sample_collector.py",
    "torben-finance-experiment-programs": "torben_finance_experiment_programs.py",
    "torben-finance-risk-monitor": "torben_finance_risk_monitor.py",
}
BACKEND_ARTIFACT_HEALTH = [
    {"script": "torben_gtm_radar.py", "artifact": "torben-gtm-radar-latest.json"},
    {"script": "torben_gtm_engagement_radar.py", "artifact": "torben-gtm-engagement-radar-latest.json"},
    {
        "script": "torben_finance_radar.py",
        "artifact": "torben-finance-radar-latest.json",
        "job_artifact_alignment": True,
        "ratatosk_live_safety": True,
        "required_mutation_counters": True,
        "radar_source_alignment": True,
    },
    {
        "script": "torben_finance_loop_heartbeat.py",
        "artifact": "torben-finance-loop-heartbeat-latest.json",
        "ratatosk_live_safety": True,
        "loop_stop_condition": True,
        "job_artifact_alignment": True,
        "required_mutation_counters": True,
        "loop_heartbeat_source_alignment": True,
    },
    {
        "script": "torben_finance_sample_collector.py",
        "artifact": "torben-finance-sample-collector-latest.json",
        "ratatosk_live_safety": True,
        "job_artifact_alignment": True,
        "required_mutation_counters": True,
        "sample_collector_contract": True,
    },
    {
        "script": "torben_finance_experiment_programs.py",
        "artifact": "torben-finance-experiment-programs-latest.json",
        "ratatosk_live_safety": True,
        "job_artifact_alignment": True,
        "required_mutation_counters": True,
        "experiment_programs_contract": True,
    },
    {
        "script": "torben_finance_risk_monitor.py",
        "artifact": "torben-finance-risk-monitor-latest.json",
        "ratatosk_live_safety": True,
        "loop_stop_condition": True,
        "loop_readiness_ledger": True,
        "job_artifact_alignment": True,
        "required_mutation_counters": True,
    },
    {
        "script": "torben_finance_next_wake_runner.py",
        "artifact": "torben-finance-next-wake-runner-latest.json",
        "ratatosk_live_safety": True,
        "job_artifact_alignment": True,
        "required_mutation_counters": True,
        "next_wake_runner_contract": True,
    },
    {
        "script": "torben_finance_go_live_packet.py",
        "artifact": "torben-finance-go-live-packet-latest.json",
        "ratatosk_live_safety": True,
        "job_artifact_alignment": True,
        "required_mutation_counters": True,
        "go_live_packet_contract": True,
    },
    {
        "script": "torben_finance_repair_window_simulator.py",
        "artifact": "torben-finance-repair-window-simulator-latest.json",
        "ratatosk_live_safety": True,
        "job_artifact_alignment": True,
        "required_mutation_counters": True,
        "repair_window_simulation_contract": True,
    },
    {
        "script": "torben_monarch_savings_daily.py",
        "artifact": "torben-monarch-savings-daily-latest.json",
        "monarch_savings": True,
    },
    {
        "script": "torben_monarch_savings_weekly.py",
        "artifact": "torben-monarch-savings-weekly-latest.json",
        "monarch_savings": True,
    },
]
HYGIENE_REVIEW_ARTIFACT_HEALTH = [
    {
        "script": "torben_email_hygiene_review.py",
        "artifact": "torben-email-hygiene-review-actions-latest.json",
        "task": "torben_email_hygiene_weekly_review",
        "max_age": HYGIENE_REVIEW_MAX_AGE,
    }
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def live_profile_failure_fingerprint(payload: dict[str, Any]) -> str:
    """Stable fingerprint for one unresolved verifier failure."""

    material = {
        "status": payload.get("status"),
        "errors": list(payload.get("errors") or []),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def update_live_profile_alert_state(
    *,
    payload: dict[str, Any],
    state_path: str | Path,
    now: datetime | None = None,
) -> bool:
    """Persist verifier alert state and return True when this failure is duplicate.

    A verifier failure is an operational alert, not a script crash. The first
    occurrence of a fingerprint should alert. Repeated occurrences of the same
    unresolved fingerprint should stay silent until the verifier passes or the
    failure changes.
    """

    path = Path(state_path)
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_text = now_utc.isoformat().replace("+00:00", "Z")
    existing = _load_json(path) or {}

    if payload.get("status") == "pass":
        state = {
            "version": ALERT_STATE_VERSION,
            "status": "pass",
            "active_fingerprint": None,
            "cleared_at": now_text,
            "previous_fingerprint": existing.get("active_fingerprint"),
        }
        payload["alert_dedupe"] = {
            "suppressed": False,
            "status": "cleared",
            "state_path": str(path),
        }
        _write_json(path, state)
        return False

    fingerprint = live_profile_failure_fingerprint(payload)
    same_unresolved = (
        existing.get("status") == "fail"
        and existing.get("active_fingerprint") == fingerprint
    )
    duplicate_count = int(existing.get("duplicate_count") or 0)
    if same_unresolved:
        duplicate_count += 1
        state = {
            **existing,
            "version": ALERT_STATE_VERSION,
            "status": "fail",
            "active_fingerprint": fingerprint,
            "last_seen_at": now_text,
            "duplicate_count": duplicate_count,
            "errors": list(payload.get("errors") or []),
        }
        payload["alert_dedupe"] = {
            "suppressed": True,
            "status": "duplicate_failure_suppressed",
            "fingerprint": fingerprint,
            "duplicate_count": duplicate_count,
            "state_path": str(path),
        }
        _write_json(path, state)
        return True

    state = {
        "version": ALERT_STATE_VERSION,
        "status": "fail",
        "active_fingerprint": fingerprint,
        "first_alerted_at": now_text,
        "last_seen_at": now_text,
        "duplicate_count": 0,
        "errors": list(payload.get("errors") or []),
    }
    payload["alert_dedupe"] = {
        "suppressed": False,
        "status": "new_failure",
        "fingerprint": fingerprint,
        "state_path": str(path),
    }
    _write_json(path, state)
    return False


def stage_live_profile_investigation_request(
    *,
    payload: dict[str, Any],
    request_path: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Stage a bounded LLM investigation request for a new verifier failure."""

    path = Path(request_path)
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    fingerprint = live_profile_failure_fingerprint(payload)
    failing_checks = [
        check
        for check in payload.get("script_checks") or []
        if isinstance(check, dict) and (check.get("errors") or check.get("last_error") or check.get("last_delivery_error"))
    ]
    request = {
        "version": INVESTIGATION_REQUEST_VERSION,
        "task": "torben_live_profile_investigation_request",
        "wakeAgent": True,
        "status": "pending",
        "created_at": now_utc.isoformat().replace("+00:00", "Z"),
        "failure_fingerprint": fingerprint,
        "failure_generated_at": payload.get("generated_at"),
        "profile_home": payload.get("profile_home"),
        "jobs_path": payload.get("jobs_path"),
        "repo_snapshot_home": payload.get("repo_snapshot_home"),
        "errors": list(payload.get("errors") or []),
        "warnings": list(payload.get("warnings") or []),
        "failing_script_checks": failing_checks,
        "gmail_realtime_health": payload.get("gmail_realtime_health"),
        "investigation_contract": {
            "mode": "read_only_root_cause_and_qa_plan",
            "must_identify": [
                "likely_root_cause",
                "operational_risk",
                "affected_jobs_or_sources",
                "read_only_verification_commands",
                "candidate_fix_plan",
                "tests_to_run",
            ],
            "must_not": [
                "patch_files",
                "change_cron_jobs",
                "mutate_email_or_calendar",
                "send_email",
                "post_publicly",
                "trade",
                "delete_or_archive_data",
            ],
            "approval_required_before_fix": True,
        },
    }
    _write_json(path, request)
    payload["investigation_request"] = {
        "status": "staged",
        "path": str(path),
        "failure_fingerprint": fingerprint,
    }
    return request


def clear_live_profile_investigation_request(
    *,
    request_path: str | Path,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Clear any pending investigation request once the live verifier passes."""

    path = Path(request_path)
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    request = {
        "version": INVESTIGATION_REQUEST_VERSION,
        "task": "torben_live_profile_investigation_request",
        "wakeAgent": False,
        "status": "cleared",
        "cleared_at": now_utc.isoformat().replace("+00:00", "Z"),
    }
    _write_json(path, request)
    if payload is not None:
        payload["investigation_request"] = {
            "status": "cleared",
            "path": str(path),
        }
    return request


def consume_live_profile_investigation_request(
    *,
    request_path: str | Path,
    state_path: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the next LLM investigation handoff, suppressing duplicates."""

    request_file = Path(request_path)
    state_file = Path(state_path)
    request = _load_json(request_file)
    if not request or request.get("status") != "pending" or not request.get("failure_fingerprint"):
        return {
            "task": "torben_live_profile_investigate",
            "wakeAgent": False,
            "status": "idle",
            "reason": "no pending live-profile investigation request",
            "request_path": str(request_file),
        }

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_text = now_utc.isoformat().replace("+00:00", "Z")
    existing = _load_json(state_file) or {}
    fingerprint = str(request.get("failure_fingerprint"))
    if existing.get("last_handed_to_llm_fingerprint") == fingerprint:
        duplicate_count = int(existing.get("duplicate_count") or 0) + 1
        _write_json(
            state_file,
            {
                **existing,
                "version": INVESTIGATION_REQUEST_VERSION,
                "status": "duplicate_suppressed",
                "last_seen_at": now_text,
                "duplicate_count": duplicate_count,
            },
        )
        return {
            "task": "torben_live_profile_investigate",
            "wakeAgent": False,
            "status": "duplicate_investigation_suppressed",
            "reason": "same live-profile failure fingerprint already handed to LLM",
            "failure_fingerprint": fingerprint,
            "duplicate_count": duplicate_count,
            "request_path": str(request_file),
        }

    state = {
        "version": INVESTIGATION_REQUEST_VERSION,
        "status": "handed_to_llm",
        "last_handed_to_llm_at": now_text,
        "last_handed_to_llm_fingerprint": fingerprint,
        "duplicate_count": 0,
        "request_path": str(request_file),
    }
    _write_json(state_file, state)
    return {
        "task": "torben_live_profile_investigate",
        "wakeAgent": True,
        "status": "investigation_requested",
        "generated_at": now_text,
        "failure_fingerprint": fingerprint,
        "request_path": str(request_file),
        "state_path": str(state_file),
        "request": request,
        "operator_boundary": {
            "llm_may": [
                "inspect supplied evidence",
                "run read-only verification commands if tools are available",
                "propose root cause and tests",
                "ask Eric to approve any patch",
            ],
            "llm_must_not": [
                "edit files",
                "change cron config",
                "restart services",
                "mutate external systems",
                "claim a fix was applied",
            ],
        },
    }


@dataclass
class ScriptCheck:
    name: str
    enabled: bool
    script: str | None
    live_path: str | None
    exists: bool = False
    compiles: bool | None = None
    snapshot_in_sync: bool | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_delivery_error: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "script": self.script,
            "live_path": self.live_path,
            "exists": self.exists,
            "compiles": self.compiles,
            "snapshot_in_sync": self.snapshot_in_sync,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_delivery_error": self.last_delivery_error,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _load_jobs(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise ValueError(f"Cron jobs file must contain a jobs list: {path}")
    return [job for job in jobs if isinstance(job, dict)]


def _enabled_scripts(jobs: list[dict[str, Any]]) -> set[str]:
    scripts: set[str] = set()
    for job in jobs:
        if not bool(job.get("enabled", True)):
            continue
        script = str(job.get("script") or "").strip()
        if script:
            scripts.add(Path(script).name)
    return scripts


def _enabled_job_by_name(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not bool(job.get("enabled", True)):
            continue
        name = str(job.get("name") or "").strip()
        if name:
            result[name] = job
    return result


def _job_schedule_display(job: dict[str, Any]) -> str:
    value = str(job.get("schedule_display") or "").strip()
    if value:
        return value
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("display") or schedule.get("expr") or "").strip()
    return str(schedule or "").strip()


def _verify_finance_cron_snapshot(profile: Path, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify the portable cron snapshot covers the live finance schedule."""

    required = REQUIRED_FINANCE_CRON_SNAPSHOT_JOBS
    live_by_name = _enabled_job_by_name(jobs)
    enabled_required_names = sorted(name for name in required if name in live_by_name)
    snapshot_path = profile / "cron" / "jobs.snapshot.json"
    summary: dict[str, Any] = {
        "snapshot_path": str(snapshot_path),
        "required_job_count": len(required),
        "enabled_required_job_count": len(enabled_required_names),
        "required_jobs": sorted(required),
        "status": "not_applicable",
        "errors": [],
        "warnings": [],
    }
    if len(enabled_required_names) != len(required):
        missing_live = sorted(set(required) - set(enabled_required_names))
        summary["missing_live_required_jobs"] = missing_live
        return summary
    if not snapshot_path.exists():
        summary["status"] = "fail"
        summary["errors"] = [f"finance cron snapshot missing: {snapshot_path}"]
        return summary

    try:
        snapshot_jobs = _load_jobs(snapshot_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        summary["status"] = "fail"
        summary["errors"] = [f"finance cron snapshot unreadable: {type(exc).__name__}: {str(exc)[:180]}"]
        return summary

    snapshot_by_name = _enabled_job_by_name(snapshot_jobs)
    checked: list[dict[str, Any]] = []
    errors: list[str] = []
    for name, expected_script in sorted(required.items()):
        live_job = live_by_name[name]
        snapshot_job = snapshot_by_name.get(name)
        if snapshot_job is None:
            errors.append(f"finance cron snapshot missing enabled job: {name}")
            continue
        live_schedule = _job_schedule_display(live_job)
        snapshot_schedule = _job_schedule_display(snapshot_job)
        snapshot_script = Path(str(snapshot_job.get("script") or "")).name
        checked.append({
            "name": name,
            "script": snapshot_script,
            "schedule_display": snapshot_schedule,
            "no_agent": bool(snapshot_job.get("no_agent")),
        })
        if snapshot_script != expected_script:
            errors.append(
                f"finance cron snapshot script mismatch for {name}: "
                f"{snapshot_script or '<missing>'} != {expected_script}"
            )
        if snapshot_schedule != live_schedule:
            errors.append(
                f"finance cron snapshot schedule mismatch for {name}: "
                f"{snapshot_schedule or '<missing>'} != {live_schedule or '<missing>'}"
            )
        if snapshot_job.get("no_agent") is not True:
            errors.append(f"finance cron snapshot job is not no-agent: {name}")

    summary["checked_jobs"] = checked
    summary["snapshot_job_count"] = len(snapshot_jobs)
    summary["status"] = "fail" if errors else "pass"
    summary["errors"] = errors
    return summary


def _verify_gmail_realtime_health(profile: Path, jobs: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Verify Gmail realtime health without reading Gmail or Pub/Sub.

    The check uses only local artifacts from the watch renewer and Pub/Sub
    puller so the live-profile verifier stays cheap and non-mutating.
    """

    enabled = _enabled_scripts(jobs)
    if not {"torben_gmail_pubsub_pull.py", "torben_gmail_watch_register.py"} & enabled:
        return {"enabled": False, "status": "skipped", "errors": [], "warnings": []}

    state_dir = profile / "state"
    watch_state_path = state_dir / "torben-gmail-watch-state.json"
    watch_state = _load_json(watch_state_path)
    errors: list[str] = []
    warnings: list[str] = []
    accounts_checked = 0
    soonest_expiration_at: str | None = None

    if not watch_state:
        errors.append(f"gmail realtime watch state missing or unreadable: {watch_state_path}")
    else:
        if watch_state.get("last_watch_registration_status") != "pass":
            errors.append(
                "gmail watch registration status is not pass: "
                f"{watch_state.get('last_watch_registration_status') or 'missing'}"
            )
        accounts = watch_state.get("accounts") if isinstance(watch_state.get("accounts"), dict) else {}
        if not accounts:
            errors.append("gmail realtime watch state has no registered accounts")
        for alias, account_state in sorted(accounts.items()):
            if not isinstance(account_state, dict):
                errors.append(f"{alias}: gmail watch state is malformed")
                continue
            accounts_checked += 1
            expires_at = _parse_timestamp(account_state.get("watch_expiration_at"))
            if expires_at is None:
                errors.append(f"{alias}: gmail watch expiration missing or invalid")
                continue
            if soonest_expiration_at is None or expires_at.isoformat() < soonest_expiration_at:
                soonest_expiration_at = expires_at.isoformat().replace("+00:00", "Z")
            remaining = expires_at - now
            if remaining <= timedelta(0):
                errors.append(f"{alias}: gmail watch is expired")
            elif remaining <= GMAIL_WATCH_RENEWAL_FLOOR:
                errors.append(
                    f"{alias}: gmail watch expires within {int(GMAIL_WATCH_RENEWAL_FLOOR.total_seconds() // 3600)}h"
                )

    pull_latest_path = state_dir / "torben-gmail-pubsub-pull-latest.json"
    pull_latest = _load_json(pull_latest_path)
    pubsub_latest_at: str | None = None
    if "torben_gmail_pubsub_pull.py" in enabled:
        if not pull_latest:
            errors.append(f"gmail Pub/Sub pull latest artifact missing or unreadable: {pull_latest_path}")
        else:
            generated_at = _parse_timestamp(pull_latest.get("generated_at"))
            if generated_at is None:
                errors.append("gmail Pub/Sub pull latest artifact has missing or invalid generated_at")
            else:
                pubsub_latest_at = generated_at.isoformat().replace("+00:00", "Z")
                if now - generated_at > GMAIL_PUBSUB_PULL_FRESHNESS:
                    errors.append(
                        "gmail Pub/Sub pull latest artifact is stale: "
                        f"{pubsub_latest_at}"
                    )
            if pull_latest.get("wakeAgent") and pull_latest.get("reason"):
                warnings.append(f"gmail Pub/Sub pull latest wake reason: {pull_latest.get('reason')}")

    status = "pass" if not errors else "fail"
    return {
        "enabled": True,
        "status": status,
        "accounts_checked": accounts_checked,
        "soonest_watch_expiration_at": soonest_expiration_at,
        "watch_renewal_floor_seconds": int(GMAIL_WATCH_RENEWAL_FLOOR.total_seconds()),
        "pubsub_latest_at": pubsub_latest_at,
        "pubsub_freshness_seconds": int(GMAIL_PUBSUB_PULL_FRESHNESS.total_seconds()),
        "errors": errors,
        "warnings": warnings,
    }


def _int_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _strict_int_count(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _artifact_stop_condition(payload: dict[str, Any]) -> dict[str, Any]:
    stop_condition = payload.get("stop_condition")
    if isinstance(stop_condition, dict):
        return stop_condition
    heartbeat = payload.get("loop_heartbeat")
    if isinstance(heartbeat, dict) and isinstance(heartbeat.get("stop_condition"), dict):
        return heartbeat["stop_condition"]
    return {}


def _enabled_jobs_for_script(jobs: list[dict[str, Any]], script: str) -> list[dict[str, Any]]:
    script_name = Path(script).name
    matches: list[dict[str, Any]] = []
    for job in jobs:
        if not bool(job.get("enabled", True)):
            continue
        job_script = str(job.get("script") or "").strip()
        if job_script and Path(job_script).name == script_name:
            matches.append(job)
    return matches


def _job_artifact_alignment_summary(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    latest_successful_run: tuple[datetime, str] | None = None
    next_run: tuple[datetime, str] | None = None
    for job in jobs:
        name = str(job.get("name") or job.get("id") or "unnamed")
        last_run_text = str(job.get("last_run_at") or "").strip() or None
        next_run_text = str(job.get("next_run_at") or "").strip() or None
        summary = {
            "name": name,
            "last_status": job.get("last_status"),
            "last_run_at": last_run_text,
            "next_run_at": next_run_text,
            "schedule_display": job.get("schedule_display"),
        }
        summaries.append(summary)
        last_run = _parse_timestamp(last_run_text)
        if last_run is not None and str(job.get("last_status") or "").lower() == "ok":
            if latest_successful_run is None or last_run > latest_successful_run[0]:
                latest_successful_run = (last_run, name)
        parsed_next = _parse_timestamp(next_run_text)
        if parsed_next is not None:
            if next_run is None or parsed_next < next_run[0]:
                next_run = (parsed_next, name)

    return {
        "jobs": summaries,
        "latest_successful_job_run_at": (
            latest_successful_run[0].isoformat().replace("+00:00", "Z")
            if latest_successful_run
            else None
        ),
        "latest_successful_job_name": latest_successful_run[1] if latest_successful_run else None,
        "next_job_run_at": next_run[0].isoformat().replace("+00:00", "Z") if next_run else None,
        "next_job_name": next_run[1] if next_run else None,
        "alignment_tolerance_seconds": int(BACKEND_ARTIFACT_JOB_ALIGNMENT_TOLERANCE.total_seconds()),
    }


def _verify_backend_artifact_health(profile: Path, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify latest stage-only backend artifacts do not hide error payloads."""

    enabled = _enabled_scripts(jobs)
    state_dir = profile / "state"
    errors: list[str] = []
    warnings: list[str] = []
    artifacts: list[dict[str, Any]] = []

    for spec in sorted(BACKEND_ARTIFACT_HEALTH, key=lambda item: str(item.get("script") or "")):
        script = str(spec.get("script") or "")
        artifact_name = str(spec.get("artifact") or "")
        if script not in enabled:
            continue
        path = state_dir / artifact_name
        payload = _load_json(path)
        artifact: dict[str, Any] = {
            "script": script,
            "path": str(path),
            "exists": path.exists(),
        }
        if not payload:
            artifact["status"] = "missing"
            warnings.append(f"{script}: latest artifact missing or unreadable: {path}")
            artifacts.append(artifact)
            continue

        artifact_jobs = _enabled_jobs_for_script(jobs, script)
        alignment = _job_artifact_alignment_summary(artifact_jobs)
        public_actions = _int_count(payload.get("public_actions_taken"))
        external_mutations = _int_count(payload.get("external_mutations"))
        orders_submitted = _int_count(payload.get("orders_submitted"))
        broker_orders = _int_count(payload.get("broker_orders_submitted"))
        monarch_writes = _int_count(payload.get("monarch_write_calls"))
        artifact.update(
            {
                "status": "pass",
                "generated_at": payload.get("generated_at"),
                "wakeAgent": payload.get("wakeAgent"),
                "public_actions_taken": public_actions,
                "external_mutations": external_mutations,
                "orders_submitted": orders_submitted,
                "broker_orders_submitted": broker_orders,
                "monarch_write_calls": monarch_writes,
            }
        )
        if alignment["jobs"]:
            artifact["job_artifact_alignment"] = alignment

        if bool(spec.get("required_mutation_counters")):
            for counter_name in REQUIRED_MUTATION_COUNTERS:
                if counter_name not in payload:
                    artifact["status"] = "fail"
                    errors.append(f"{script}: latest artifact missing mutation counter: {counter_name}")
                    continue
                if _strict_int_count(payload.get(counter_name)) is None:
                    artifact["status"] = "fail"
                    errors.append(f"{script}: latest artifact mutation counter is not an integer: {counter_name}")

        payload_error = payload.get("error")
        if payload_error:
            artifact["status"] = "fail"
            if isinstance(payload_error, dict):
                error_type = str(payload_error.get("type") or "error")
                message = str(payload_error.get("message") or "")[:180]
                errors.append(f"{script}: latest artifact has error: {error_type}: {message}")
            else:
                errors.append(f"{script}: latest artifact has error: {str(payload_error)[:180]}")

        source_refresh = payload.get("source_refresh")
        if isinstance(source_refresh, dict) and str(source_refresh.get("status") or "").lower() == "failed":
            artifact["status"] = "fail"
            errors.append(f"{script}: source refresh failed")

        llm_judge = payload.get("llm_judge")
        if isinstance(llm_judge, dict) and str(llm_judge.get("status") or "").lower() == "failed":
            artifact["status"] = "fail"
            message = str(llm_judge.get("error") or "")[:180]
            errors.append(f"{script}: LLM judge failed: {message}")

        if public_actions:
            artifact["status"] = "fail"
            errors.append(f"{script}: public_actions_taken is nonzero: {public_actions}")
        if external_mutations:
            artifact["status"] = "fail"
            errors.append(f"{script}: external_mutations is nonzero: {external_mutations}")
        if orders_submitted:
            artifact["status"] = "fail"
            errors.append(f"{script}: orders_submitted is nonzero: {orders_submitted}")
        if broker_orders:
            artifact["status"] = "fail"
            errors.append(f"{script}: broker_orders_submitted is nonzero: {broker_orders}")
        if monarch_writes:
            artifact["status"] = "fail"
            errors.append(f"{script}: monarch_write_calls is nonzero: {monarch_writes}")
        if bool(spec.get("monarch_savings")):
            artifact["monarch_read_calls"] = _int_count(payload.get("monarch_read_calls"))
            artifact["redaction_status"] = payload.get("redaction_status")
            artifact["policy_decision_present"] = bool(payload.get("policy_decision_present"))
            if payload.get("redaction_status") != "pass":
                artifact["status"] = "fail"
                errors.append(f"{script}: redaction_status is not pass")
            if not bool(payload.get("policy_decision_present")):
                artifact["status"] = "fail"
                errors.append(f"{script}: policy_decision_present is false")
            raw_keys = {"tool_results", "transactions", "recurring", "budget", "cash_flow"} & set(payload)
            if raw_keys:
                artifact["status"] = "fail"
                errors.append(f"{script}: raw Monarch payload keys leaked: {','.join(sorted(raw_keys))}")

        if bool(spec.get("ratatosk_live_safety")):
            source_refresh = _dict_value(payload.get("source_refresh") or payload.get("torben_source_refresh"))
            live_safety_env = _dict_value(source_refresh.get("live_safety_env"))
            artifact["live_safety_env"] = live_safety_env
            for env_name in ("RATATOSK_LIVE_TRADING", "ROBINHOOD_LIVE", "ROBINHOOD_EQUITY_LIVE"):
                if str(live_safety_env.get(env_name) or "") != "0":
                    artifact["status"] = "fail"
                    errors.append(f"{script}: {env_name} is not live-disabled in latest artifact")

        if bool(spec.get("loop_stop_condition")):
            stop_condition = _artifact_stop_condition(payload)
            release_conditions = _string_list(stop_condition.get("release_conditions"))
            artifact["stop_condition_status"] = stop_condition.get("status")
            artifact["primary_next_action"] = stop_condition.get("primary_next_action")
            artifact["release_conditions"] = release_conditions
            if not stop_condition.get("status"):
                artifact["status"] = "fail"
                errors.append(f"{script}: latest artifact missing stop_condition.status")
            if not stop_condition.get("primary_next_action"):
                artifact["status"] = "fail"
                errors.append(f"{script}: latest artifact missing stop_condition.primary_next_action")
            if (
                stop_condition.get("status") == "wait_for_market_open_scan_supply"
                and "scan_candidate_supply.market_open == true" not in release_conditions
            ):
                artifact["status"] = "fail"
                errors.append(f"{script}: market-open stop condition missing scan supply release condition")

        if bool(spec.get("radar_source_alignment")):
            source_alignment, source_errors = _verify_finance_radar_source_alignment(payload)
            artifact["source_artifact_alignment"] = source_alignment
            for error in source_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")

        if bool(spec.get("loop_heartbeat_source_alignment")):
            source_alignment, source_errors = _verify_finance_loop_heartbeat_source_alignment(payload)
            artifact["source_artifact_alignment"] = source_alignment
            for error in source_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")

        if bool(spec.get("loop_readiness_ledger")):
            ledger_summary, ledger_errors = _verify_loop_readiness_ledger(payload)
            artifact["loop_readiness_ledger"] = ledger_summary
            for error in ledger_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")

        if bool(spec.get("sample_collector_contract")):
            collector_summary, collector_errors = _verify_sample_collector_contract(payload)
            artifact["sample_collector_contract"] = collector_summary
            for error in collector_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")

        if bool(spec.get("experiment_programs_contract")):
            programs_summary, programs_errors = _verify_experiment_programs_contract(payload)
            artifact["experiment_programs_contract"] = programs_summary
            artifact["source_refresh_safe"] = payload.get("source_refresh_safe")
            artifact["experiment_programs_contract_safe"] = payload.get("experiment_programs_contract_safe")
            for error in programs_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")

        if bool(spec.get("next_wake_runner_contract")):
            source_alignment, source_errors = _verify_next_wake_runner_source_alignment(payload)
            artifact["source_refresh_safe"] = payload.get("source_refresh_safe")
            artifact["runner_contract_safe"] = payload.get("runner_contract_safe")
            artifact["commands_live_disabled"] = payload.get("commands_live_disabled")
            artifact["broker_submit_allowed"] = payload.get("broker_submit_allowed")
            artifact["human_live_review_allowed"] = payload.get("human_live_review_allowed")
            artifact["live_order_authority"] = payload.get("live_order_authority")
            artifact["next_wake_runner_contract"] = {
                "status": payload.get("status"),
                "required_operator_action": payload.get("required_operator_action"),
                "next_recheck_after_utc": payload.get("next_recheck_after_utc"),
                "bounded_collection_not_before_utc": payload.get("bounded_collection_not_before_utc"),
                "source_artifact_alignment": source_alignment,
            }
            for error in source_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")
            if payload.get("source_refresh_safe") is not True:
                artifact["status"] = "fail"
                errors.append(f"{script}: source_refresh_safe is not true")
            if payload.get("runner_contract_safe") is not True:
                artifact["status"] = "fail"
                errors.append(f"{script}: runner_contract_safe is not true")
            if payload.get("commands_live_disabled") is not True:
                artifact["status"] = "fail"
                errors.append(f"{script}: commands_live_disabled is not true")
            if payload.get("broker_submit_allowed") is not False:
                artifact["status"] = "fail"
                errors.append(f"{script}: broker_submit_allowed is not false")
            if payload.get("human_live_review_allowed") is not False:
                artifact["status"] = "fail"
                errors.append(f"{script}: human_live_review_allowed is not false")
            if payload.get("live_order_authority") not in {None, "none"}:
                artifact["status"] = "fail"
                errors.append(
                    f"{script}: live_order_authority is not none: {payload.get('live_order_authority')}"
                )

        if bool(spec.get("go_live_packet_contract")):
            packet_summary, packet_errors = _verify_go_live_packet_contract(payload)
            artifact["go_live_packet_contract"] = packet_summary
            artifact["source_refresh_safe"] = payload.get("source_refresh_safe")
            artifact["go_live_packet_contract_safe"] = payload.get("go_live_packet_contract_safe")
            for error in packet_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")

        if bool(spec.get("repair_window_simulation_contract")):
            simulation_summary, simulation_errors = _verify_repair_window_simulation_contract(payload)
            artifact["repair_window_simulation_contract"] = simulation_summary
            artifact["source_refresh_safe"] = payload.get("source_refresh_safe")
            artifact["simulation_contract_safe"] = payload.get("simulation_contract_safe")
            for error in simulation_errors:
                artifact["status"] = "fail"
                errors.append(f"{script}: {error}")

        if bool(spec.get("job_artifact_alignment")):
            generated_at = _parse_timestamp(payload.get("generated_at"))
            if generated_at is None:
                artifact["status"] = "fail"
                errors.append(f"{script}: latest artifact has missing or invalid generated_at")
            latest_successful_text = alignment.get("latest_successful_job_run_at")
            latest_successful = _parse_timestamp(latest_successful_text)
            if latest_successful is not None and generated_at is not None:
                if generated_at + BACKEND_ARTIFACT_JOB_ALIGNMENT_TOLERANCE < latest_successful:
                    artifact["status"] = "fail"
                    errors.append(
                        f"{script}: latest artifact generated_at {payload.get('generated_at')} "
                        f"is older than latest successful job run {latest_successful_text}"
                    )

        artifacts.append(artifact)

    return {
        "enabled": bool(artifacts),
        "status": "pass" if not errors else "fail",
        "artifacts": artifacts,
        "errors": errors,
        "warnings": warnings,
    }


def _verify_hygiene_review_artifact_health(
    profile: Path,
    jobs: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Verify weekly Gmail hygiene review completed recently and stayed non-mutating."""

    enabled = _enabled_scripts(jobs)
    state_dir = profile / "state"
    artifacts: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    for spec in HYGIENE_REVIEW_ARTIFACT_HEALTH:
        script = str(spec.get("script") or "")
        if script not in enabled:
            continue

        artifact_name = str(spec.get("artifact") or "")
        path = state_dir / artifact_name
        payload = _load_json(path)
        max_age = spec.get("max_age") if isinstance(spec.get("max_age"), timedelta) else HYGIENE_REVIEW_MAX_AGE
        artifact_errors: list[str] = []
        artifact_warnings: list[str] = []
        artifact: dict[str, Any] = {
            "script": script,
            "path": str(path),
            "exists": path.exists(),
            "max_age_seconds": int(max_age.total_seconds()),
        }

        if not payload:
            artifact["status"] = "missing"
            artifact_errors.append(f"latest review artifact missing or unreadable: {path}")
            artifacts.append(artifact)
            errors.extend(f"{script}: {error}" for error in artifact_errors)
            continue

        diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
        recommendations = payload.get("recommendations")
        generated_at = _parse_timestamp(payload.get("generated_at"))
        recommendation_count = _int_count(diagnostics.get("recommendation_count"))
        messages_scanned = _int_count(diagnostics.get("messages_scanned"))
        gmail_reads = _int_count(diagnostics.get("gmail_reads"))
        gmail_writes = _int_count(diagnostics.get("gmail_writes"))
        external_mutations = _int_count(diagnostics.get("external_mutations"))
        llm_review = diagnostics.get("llm_review") if isinstance(diagnostics.get("llm_review"), dict) else {}
        llm_review_status = str(llm_review.get("status") or "").strip() or None

        artifact.update(
            {
                "generated_at": payload.get("generated_at"),
                "wakeAgent": payload.get("wakeAgent"),
                "task": payload.get("task"),
                "messages_scanned": messages_scanned,
                "recommendation_count": recommendation_count,
                "gmail_reads": gmail_reads,
                "gmail_writes": gmail_writes,
                "external_mutations": external_mutations,
                "llm_review_status": llm_review_status,
            }
        )

        expected_task = str(spec.get("task") or "")
        if expected_task and payload.get("task") != expected_task:
            artifact_errors.append(f"latest artifact task mismatch: {payload.get('task') or 'missing'}")

        payload_error = payload.get("error")
        if payload_error:
            if isinstance(payload_error, dict):
                error_type = str(payload_error.get("type") or "error")
                message = str(payload_error.get("message") or "")[:180]
                artifact_errors.append(f"latest artifact has error: {error_type}: {message}")
            else:
                artifact_errors.append(f"latest artifact has error: {str(payload_error)[:180]}")

        if generated_at is None:
            artifact_errors.append("generated_at missing or invalid")
        else:
            age_seconds = int((now - generated_at).total_seconds())
            artifact["age_seconds"] = age_seconds
            if generated_at - now > timedelta(minutes=5):
                artifact_errors.append(f"generated_at is in the future: {payload.get('generated_at')}")
            elif now - generated_at > max_age:
                artifact_errors.append(
                    "latest review artifact is stale: "
                    f"{payload.get('generated_at')} older than {int(max_age.total_seconds())}s"
                )

        if not isinstance(recommendations, list):
            artifact_errors.append("recommendations missing or not a list")
        elif recommendation_count != len(recommendations):
            artifact_errors.append(
                f"recommendation_count mismatch: diagnostics={recommendation_count} actual={len(recommendations)}"
            )

        if gmail_writes:
            artifact_errors.append(f"gmail_writes is nonzero: {gmail_writes}")
        if external_mutations:
            artifact_errors.append(f"external_mutations is nonzero: {external_mutations}")
        if messages_scanned == 0:
            artifact_warnings.append("messages_scanned is zero")
        if llm_review_status and llm_review_status.startswith("failed"):
            artifact_warnings.append(f"LLM hygiene review degraded: {llm_review_status}")

        artifact["status"] = "fail" if artifact_errors else "pass"
        if artifact_errors:
            artifact["errors"] = artifact_errors
        if artifact_warnings:
            artifact["warnings"] = artifact_warnings
        artifacts.append(artifact)
        errors.extend(f"{script}: {error}" for error in artifact_errors)
        warnings.extend(f"{script}: {warning}" for warning in artifact_warnings)

    return {
        "enabled": bool(artifacts),
        "status": "pass" if not errors else "fail",
        "artifacts": artifacts,
        "errors": errors,
        "warnings": warnings,
    }



def _source_refresh_artifact_path(payload: dict[str, Any], artifact_name: str) -> Path | None:
    state_root = _source_refresh_state_root(payload)
    if state_root is None:
        return None
    return state_root / "trading-loop" / artifact_name


def _source_refresh_equity_research_artifact_path(payload: dict[str, Any], artifact_name: str) -> Path | None:
    state_root = _source_refresh_state_root(payload)
    if state_root is None:
        return None
    return state_root / "equity-research" / artifact_name


def _source_refresh_state_root(payload: dict[str, Any]) -> Path | None:
    source_refresh = _dict_value(payload.get("source_refresh") or payload.get("torben_source_refresh"))
    command = source_refresh.get("command") if isinstance(source_refresh.get("command"), list) else []
    state_root = _command_option_value(command, "--state-root") or str(source_refresh.get("state_root") or "").strip()
    if state_root:
        return Path(state_root)

    root_text = str(source_refresh.get("root") or "").strip()
    if not root_text:
        return None
    root = Path(root_text)
    if not root.is_dir():
        return None
    return root / "state"


def _command_option_value(command: list[Any], option: str) -> str | None:
    for index, item in enumerate(command):
        if str(item) != option:
            continue
        if index + 1 >= len(command):
            return None
        value = str(command[index + 1]).strip()
        return value or None
    return None


def _source_rejection_reasons(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            f"{reason}:{count}"
            for reason, count in sorted(
                value.items(),
                key=lambda item: (-_int_count(item[1]), str(item[0])),
            )
        ]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _append_source_profile_timing_checks(
    *,
    label: str,
    payload: dict[str, Any],
    source: dict[str, Any],
    summary: dict[str, Any],
    errors: list[str],
    mismatches: list[str],
) -> None:
    profile_generated = _parse_timestamp(payload.get("generated_at"))
    source_generated = _parse_timestamp(source.get("generated_at"))
    summary["profile_generated_at"] = payload.get("generated_at")
    summary["source_generated_at"] = source.get("generated_at")
    if profile_generated is None:
        mismatches.append("profile_generated_at")
        errors.append(f"source {label} profile generated_at missing or invalid: {payload.get('generated_at')}")
        return
    if source_generated is None:
        mismatches.append("source_generated_at")
        errors.append(f"source {label} generated_at missing or invalid: {source.get('generated_at')}")
        return
    if source_generated > profile_generated + SOURCE_PROFILE_FUTURE_TOLERANCE:
        mismatches.append("generated_at_window")
        errors.append(
            f"source {label} generated_at is newer than profile artifact: "
            f"source={source.get('generated_at')} profile={payload.get('generated_at')}"
        )
    if profile_generated - source_generated > SOURCE_PROFILE_ALIGNMENT_TOLERANCE:
        mismatches.append("generated_at_window")
        errors.append(
            f"source {label} generated_at is older than profile artifact by more than "
            f"{int(SOURCE_PROFILE_ALIGNMENT_TOLERANCE.total_seconds())}s: "
            f"source={source.get('generated_at')} profile={payload.get('generated_at')}"
        )


def _append_source_alignment_comparisons(
    *,
    label: str,
    comparisons: list[tuple[str, Any, Any]],
    summary: dict[str, Any],
    errors: list[str],
    mismatches: list[str],
) -> None:
    for name, profile_value, source_value in comparisons:
        summary[f"profile_{name}"] = profile_value
        summary[f"source_{name}"] = source_value
        if profile_value != source_value:
            mismatches.append(name)
            errors.append(
                f"source {label} {name} differs from profile artifact: "
                f"profile={profile_value!r} source={source_value!r}"
            )


def _verify_finance_radar_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_equity_research_artifact_path(payload, "latest.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source finance radar artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source finance radar artifact unreadable: {path}")
        return summary, errors

    source_supply = _dict_value(source.get("scan_candidate_supply"))
    profile_supply = _dict_value(payload.get("scan_candidate_supply"))
    mismatches: list[str] = []
    _append_source_profile_timing_checks(
        label="finance radar",
        payload=payload,
        source=source,
        summary=summary,
        errors=errors,
        mismatches=mismatches,
    )
    _append_source_alignment_comparisons(
        label="finance radar",
        summary=summary,
        errors=errors,
        mismatches=mismatches,
        comparisons=[
            ("ratatosk_status", payload.get("ratatosk_status"), source.get("status")),
            ("candidate_count", payload.get("candidate_count"), source.get("candidate_count")),
            ("primary_next_action", payload.get("primary_next_action"), source.get("primary_next_action")),
            ("scan_candidate_supply.status", profile_supply.get("status"), source_supply.get("status")),
            ("scan_candidate_supply.market_count", profile_supply.get("market_count"), source_supply.get("market_count")),
            ("scan_candidate_supply.proposal_count", profile_supply.get("proposal_count"), source_supply.get("proposal_count")),
            (
                "scan_candidate_supply.selected_candidate_count",
                profile_supply.get("selected_candidate_count"),
                source_supply.get("selected_candidate_count"),
            ),
            (
                "scan_candidate_supply.rejection_reasons",
                _source_rejection_reasons(profile_supply.get("rejection_reasons")),
                _source_rejection_reasons(source_supply.get("rejection_reasons")),
            ),
            ("public_actions_taken", payload.get("public_actions_taken"), source.get("public_actions_taken")),
            ("external_mutations", payload.get("external_mutations"), source.get("external_mutations")),
            ("orders_submitted", payload.get("orders_submitted"), source.get("orders_submitted")),
            ("broker_orders_submitted", payload.get("broker_orders_submitted"), source.get("broker_orders_submitted")),
        ],
    )
    if source.get("live_order_authority") not in {None, "none"}:
        mismatches.append("live_order_authority")
        errors.append(f"source finance radar live_order_authority is not none: {source.get('live_order_authority')}")

    summary["source_task"] = source.get("task")
    summary["mismatches"] = sorted(dict.fromkeys(mismatches))
    summary["status"] = "fail" if errors else "pass"
    return summary, errors


def _verify_finance_loop_heartbeat_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_artifact_path(payload, "ticks/latest.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source finance loop heartbeat artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source finance loop heartbeat artifact unreadable: {path}")
        return summary, errors

    heartbeat = _dict_value(payload.get("loop_heartbeat"))
    research = _dict_value(source.get("research"))
    profile_stop = _dict_value(payload.get("stop_condition"))
    source_stop = _dict_value(source.get("stop_condition"))
    profile_outcome = _dict_value(payload.get("paper_outcome"))
    source_outcome = _dict_value(source.get("paper_outcome"))
    profile_performance = _dict_value(payload.get("paper_performance"))
    source_performance = _dict_value(source.get("paper_performance"))
    profile_optimizer = _dict_value(payload.get("signal_optimizer"))
    source_optimizer = _dict_value(source.get("signal_optimizer"))
    profile_experiment = _dict_value(payload.get("experiment_evaluation"))
    source_experiment = _dict_value(source.get("experiment_evaluation"))
    profile_risk = _dict_value(payload.get("risk_incident"))
    source_risk = _dict_value(source.get("risk_incident"))
    mismatches: list[str] = []

    _append_source_profile_timing_checks(
        label="finance loop heartbeat",
        payload=payload,
        source=source,
        summary=summary,
        errors=errors,
        mismatches=mismatches,
    )
    _append_source_alignment_comparisons(
        label="finance loop heartbeat",
        summary=summary,
        errors=errors,
        mismatches=mismatches,
        comparisons=[
            ("ratatosk_status", payload.get("ratatosk_status"), source.get("status")),
            ("loop_heartbeat.tick_id", heartbeat.get("tick_id"), source.get("tick_id")),
            ("loop_heartbeat.status", heartbeat.get("status"), source.get("status")),
            ("loop_heartbeat.research_mode", heartbeat.get("research_mode"), source.get("research_mode")),
            ("loop_heartbeat.research_status", heartbeat.get("research_status"), research.get("status")),
            (
                "loop_heartbeat.research_candidate_count",
                heartbeat.get("research_candidate_count"),
                research.get("candidate_count"),
            ),
            ("loop_heartbeat.research_symbols", _string_list(heartbeat.get("research_symbols")), _string_list(research.get("symbols"))),
            ("loop_heartbeat.paper_canary_status", heartbeat.get("paper_canary_status"), _dict_value(source.get("paper_canary")).get("status")),
            ("loop_heartbeat.paper_canary_reason", heartbeat.get("paper_canary_reason"), _dict_value(source.get("paper_canary")).get("reason")),
            ("primary_next_action", payload.get("primary_next_action"), source.get("primary_next_action")),
            ("stop_condition.status", profile_stop.get("status"), source_stop.get("status")),
            ("stop_condition.primary_next_action", profile_stop.get("primary_next_action"), source_stop.get("primary_next_action")),
            ("stop_condition.release_conditions", _string_list(profile_stop.get("release_conditions")), _string_list(source_stop.get("release_conditions"))),
            ("stop_condition.live_order_authority", profile_stop.get("live_order_authority"), source_stop.get("live_order_authority")),
            ("stop_condition.max_new_samples", profile_stop.get("max_new_samples"), source_stop.get("max_new_samples")),
            ("stop_condition.max_iterations", profile_stop.get("max_iterations"), source_stop.get("max_iterations")),
            ("deterministic_stop_condition", _dict_value(payload.get("deterministic_stop_condition")), _dict_value(source.get("deterministic_stop_condition"))),
            ("paper_outcome.status", profile_outcome.get("status"), source_outcome.get("status")),
            ("paper_outcome.signal_id", profile_outcome.get("signal_id"), source_outcome.get("signal_id")),
            ("paper_outcome.symbol", profile_outcome.get("symbol"), source_outcome.get("symbol")),
            ("paper_outcome.failures", _string_list(profile_outcome.get("failures")), _string_list(source_outcome.get("failures"))),
            ("paper_performance.status", profile_performance.get("status"), source_performance.get("status")),
            ("paper_performance.sample_count", profile_performance.get("sample_count"), source_performance.get("sample_count")),
            ("paper_performance.hit_rate", profile_performance.get("hit_rate"), source_performance.get("hit_rate")),
            ("paper_performance.average_return", profile_performance.get("average_return"), source_performance.get("average_return")),
            ("paper_performance.cumulative_return", profile_performance.get("cumulative_return"), source_performance.get("cumulative_return")),
            ("paper_performance.sharpe_ratio", profile_performance.get("sharpe_ratio"), source_performance.get("sharpe_ratio")),
            ("paper_performance.max_drawdown", profile_performance.get("max_drawdown"), source_performance.get("max_drawdown")),
            (
                "paper_performance.newey_west_tstat_proxy",
                profile_performance.get("newey_west_tstat_proxy"),
                source_performance.get("newey_west_tstat_proxy"),
            ),
            ("paper_performance.oos_months", profile_performance.get("oos_months"), source_performance.get("oos_months")),
            (
                "paper_performance.max_symbol_concentration",
                profile_performance.get("max_symbol_concentration"),
                source_performance.get("max_symbol_concentration"),
            ),
            (
                "paper_performance.blocking_reasons",
                _string_list(profile_performance.get("blocking_reasons")),
                _string_list(source_performance.get("blocking_reasons")),
            ),
            ("signal_optimizer.status", profile_optimizer.get("status"), source_optimizer.get("status")),
            ("signal_optimizer.promotion_decision", profile_optimizer.get("promotion_decision"), source_optimizer.get("promotion_decision")),
            ("signal_optimizer.recommended_action_ids", _string_list(profile_optimizer.get("recommended_action_ids")), _string_list(source_optimizer.get("recommended_action_ids"))),
            ("signal_optimizer.blocking_reasons", _string_list(profile_optimizer.get("blocking_reasons")), _string_list(source_optimizer.get("blocking_reasons"))),
            ("experiment_evaluation.status", profile_experiment.get("status"), source_experiment.get("status")),
            ("experiment_evaluation.decisions", _string_list(profile_experiment.get("decisions")), _string_list(source_experiment.get("decisions"))),
            ("risk_incident.status", profile_risk.get("status"), source_risk.get("status")),
            ("risk_incident.blocking_reasons", _string_list(profile_risk.get("blocking_reasons")), _string_list(source_risk.get("blocking_reasons"))),
            ("public_actions_taken", payload.get("public_actions_taken"), source.get("public_actions_taken")),
            ("external_mutations", payload.get("external_mutations"), source.get("external_mutations")),
            ("orders_submitted", payload.get("orders_submitted"), source.get("orders_submitted")),
            ("broker_orders_submitted", payload.get("broker_orders_submitted"), source.get("broker_orders_submitted")),
        ],
    )
    if source.get("read_only_broker") is not True:
        mismatches.append("read_only_broker")
        errors.append(f"source finance loop heartbeat read_only_broker is not true: {source.get('read_only_broker')}")

    summary["source_task"] = source.get("task")
    summary["mismatches"] = sorted(dict.fromkeys(mismatches))
    summary["status"] = "fail" if errors else "pass"
    return summary, errors


def _verify_sample_collector_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_artifact_path(payload, "sample-collector.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source sample collector artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source sample collector artifact unreadable: {path}")
        return summary, errors

    source_budget = _dict_value(source.get("sample_budget"))
    source_guard = _dict_value(source.get("sample_budget_guard"))
    profile_budget = _dict_value(payload.get("sample_budget"))
    profile_guard = _dict_value(payload.get("sample_budget_guard"))
    comparisons = (
        ("generated_at", payload.get("generated_at"), source.get("generated_at")),
        ("status", payload.get("status"), source.get("status")),
        ("sample_budget.budget_date", profile_budget.get("budget_date"), source_budget.get("budget_date")),
        (
            "sample_budget.observed_sample_count_today",
            profile_budget.get("observed_sample_count_today"),
            source_budget.get("observed_sample_count_today"),
        ),
        (
            "sample_budget.remaining_samples_today",
            profile_budget.get("remaining_samples_today"),
            source_budget.get("remaining_samples_today"),
        ),
        ("sample_budget.budget_exhausted", profile_budget.get("budget_exhausted"), source_budget.get("budget_exhausted")),
        (
            "sample_budget.requested_new_samples_this_window",
            profile_budget.get("requested_new_samples_this_window"),
            source_budget.get("requested_new_samples_this_window"),
        ),
        (
            "sample_budget.approved_new_samples_this_window",
            profile_budget.get("approved_new_samples_this_window"),
            source_budget.get("approved_new_samples_this_window"),
        ),
        ("sample_budget_guard.status", profile_guard.get("status"), source_guard.get("status")),
        (
            "sample_budget_guard.remaining_samples_today",
            profile_guard.get("remaining_samples_today"),
            source_guard.get("remaining_samples_today"),
        ),
        (
            "sample_budget_guard.budget_exhausted",
            profile_guard.get("budget_exhausted"),
            source_guard.get("budget_exhausted"),
        ),
        (
            "sample_budget_guard.approved_new_samples_this_window",
            profile_guard.get("approved_new_samples_this_window"),
            source_guard.get("approved_new_samples_this_window"),
        ),
    )
    mismatches: list[str] = []
    for label, profile_value, source_value in comparisons:
        summary[f"profile_{label}"] = profile_value
        summary[f"source_{label}"] = source_value
        if profile_value != source_value:
            mismatches.append(label)
            errors.append(
                "source sample collector "
                f"{label} differs from profile artifact: profile={profile_value!r} source={source_value!r}"
            )

    summary["mismatches"] = mismatches
    summary["status"] = "fail" if mismatches else "pass"
    return summary, errors

def _verify_sample_collector_contract(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    sample_budget = _dict_value(payload.get("sample_budget"))
    sample_budget_guard = _dict_value(payload.get("sample_budget_guard"))
    optimizer = _dict_value(payload.get("signal_optimizer") or payload.get("optimizer"))
    repair_plan = _dict_value(
        optimizer.get("calibration_repair_plan") or payload.get("calibration_repair_plan_before")
    )
    coverage = _dict_value(optimizer.get("historical_policy_coverage"))
    created_count = _strict_int_count(payload.get("canaries_created_count"))
    if created_count is None:
        created_count = len([item for item in payload.get("canaries_created") or [] if isinstance(item, dict)])
    reconciled_count = _strict_int_count(payload.get("canaries_reconciled_count"))
    if reconciled_count is None:
        reconciled_count = len([item for item in payload.get("canaries_reconciled") or [] if isinstance(item, dict)])
    outcomes_observed = _strict_int_count(payload.get("outcomes_observed"))
    requested = _strict_int_count(sample_budget.get("requested_new_samples_this_window"))
    approved = _strict_int_count(sample_budget.get("approved_new_samples_this_window"))
    remaining = _strict_int_count(sample_budget.get("remaining_samples_today"))
    daily_cap = _strict_int_count(sample_budget.get("daily_sample_cap"))
    observed_today = _strict_int_count(sample_budget.get("observed_sample_count_today"))
    guard_requested = _strict_int_count(sample_budget_guard.get("requested_new_samples"))
    guard_approved = _strict_int_count(sample_budget_guard.get("approved_new_samples_this_window"))
    repair_target = _strict_int_count(repair_plan.get("target_new_samples"))
    repair_remaining = _strict_int_count(repair_plan.get("repair_samples_remaining"))
    budget_exhausted = sample_budget.get("budget_exhausted") is True or sample_budget_guard.get("budget_exhausted") is True
    summary = {
        "sample_budget_present": bool(sample_budget),
        "sample_budget_guard_present": bool(sample_budget_guard),
        "sample_budget_policy_id": sample_budget.get("policy_id"),
        "sample_budget_guard_policy_id": sample_budget_guard.get("policy_id"),
        "sample_budget_guard_status": sample_budget_guard.get("status"),
        "budget_exhausted": budget_exhausted,
        "requested_new_samples_this_window": requested,
        "approved_new_samples_this_window": approved,
        "remaining_samples_today": remaining,
        "daily_sample_cap": daily_cap,
        "observed_sample_count_today": observed_today,
        "canaries_created_count": created_count,
        "canaries_reconciled_count": reconciled_count,
        "outcomes_observed": outcomes_observed,
        "calibration_repair_plan_present": bool(repair_plan),
        "calibration_repair_plan_status": repair_plan.get("status"),
        "repair_target_new_samples": repair_target,
        "repair_samples_remaining": repair_remaining,
        "repair_preferred_existing_symbols": _string_list(repair_plan.get("preferred_existing_symbols")),
        "repair_live_order_authority": repair_plan.get("live_order_authority"),
        "historical_policy_coverage_status": coverage.get("status"),
        "historical_policy_coverage_live_order_authority": coverage.get("live_order_authority"),
    }
    source_alignment, source_errors = _verify_sample_collector_source_alignment(payload)
    summary["source_artifact_alignment"] = source_alignment
    errors: list[str] = list(source_errors)
    if not sample_budget:
        errors.append("latest artifact missing sample_budget")
    if not sample_budget_guard:
        errors.append("latest artifact missing sample_budget_guard")
    for label, budget in (("sample_budget", sample_budget), ("sample_budget_guard", sample_budget_guard)):
        if budget and budget.get("policy_id") != "daily_bounded_paper_sample_budget_v1":
            errors.append(f"{label} policy_id is not daily_bounded_paper_sample_budget_v1: {budget.get('policy_id')}")
        if budget and budget.get("live_order_authority") not in {None, "none"}:
            errors.append(f"{label} live_order_authority is not none: {budget.get('live_order_authority')}")
    for label, value in (
        ("requested_new_samples_this_window", requested),
        ("approved_new_samples_this_window", approved),
        ("remaining_samples_today", remaining),
        ("daily_sample_cap", daily_cap),
        ("observed_sample_count_today", observed_today),
    ):
        if value is None:
            errors.append(f"sample_budget {label} missing or not an integer")
        elif value < 0:
            errors.append(f"sample_budget {label} is negative: {value}")
    for label, value in (
        ("requested_new_samples", guard_requested),
        ("approved_new_samples_this_window", guard_approved),
    ):
        if sample_budget_guard and value is None:
            errors.append(f"sample_budget_guard {label} missing or not an integer")
        elif value is not None and value < 0:
            errors.append(f"sample_budget_guard {label} is negative: {value}")
    if requested is not None and approved is not None and approved > requested:
        errors.append("sample_budget approved_new_samples_this_window exceeds requested_new_samples_this_window")
    if daily_cap is not None and approved is not None and approved > daily_cap:
        errors.append("sample_budget approved_new_samples_this_window exceeds daily_sample_cap")
    if remaining is not None and daily_cap is not None and remaining > daily_cap:
        errors.append("sample_budget remaining_samples_today exceeds daily_sample_cap")
    if budget_exhausted:
        if remaining not in {0, None}:
            errors.append(f"sample_budget budget_exhausted but remaining_samples_today is {remaining}")
        if approved not in {0, None}:
            errors.append(f"sample_budget budget_exhausted but approved_new_samples_this_window is {approved}")
        if guard_approved not in {0, None}:
            errors.append(f"sample_budget_guard budget_exhausted but approved_new_samples_this_window is {guard_approved}")
        if created_count != 0:
            errors.append(f"budget exhausted but canaries_created_count is nonzero: {created_count}")
    elif created_count > 0 and approved is not None and created_count > approved:
        errors.append(
            f"canaries_created_count {created_count} exceeds approved_new_samples_this_window {approved}"
        )
    if not repair_plan:
        errors.append("latest artifact missing calibration repair plan")
    if repair_plan and repair_plan.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "calibration_repair_plan live_order_authority is not none: "
            f"{repair_plan.get('live_order_authority')}"
        )
    if repair_target is not None and repair_target < 0:
        errors.append(f"calibration_repair_plan target_new_samples is negative: {repair_target}")
    if repair_remaining is not None and repair_remaining < 0:
        errors.append(f"calibration_repair_plan repair_samples_remaining is negative: {repair_remaining}")
    if repair_target and requested is not None and requested == 0 and not budget_exhausted:
        errors.append("repair samples are needed but sample_budget requested zero new samples")
    if coverage and coverage.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "historical_policy_coverage live_order_authority is not none: "
            f"{coverage.get('live_order_authority')}"
        )
    return summary, errors



def _verify_experiment_programs_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_artifact_path(payload, "experiment-programs.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source experiment-programs artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source experiment-programs artifact unreadable: {path}")
        return summary, errors

    comparisons = (
        ("generated_at", payload.get("generated_at"), source.get("generated_at")),
        ("status", payload.get("status"), source.get("status")),
        ("optimization_mode", payload.get("optimization_mode"), source.get("optimization_mode")),
        ("state_root", payload.get("state_root"), source.get("state_root")),
        ("evidence", _dict_value(payload.get("evidence")), _dict_value(source.get("evidence"))),
        ("loops", _dict_value(payload.get("loops")), _dict_value(source.get("loops"))),
        ("read_only_broker", payload.get("read_only_broker"), source.get("read_only_broker")),
        ("broker_review_attempted", payload.get("broker_review_attempted"), source.get("broker_review_attempted")),
        ("broker_place_attempted", payload.get("broker_place_attempted"), source.get("broker_place_attempted")),
        ("live_order_authority", payload.get("live_order_authority"), source.get("live_order_authority")),
        ("public_actions_taken", payload.get("public_actions_taken"), source.get("public_actions_taken")),
        ("external_mutations", payload.get("external_mutations"), source.get("external_mutations")),
        ("orders_submitted", payload.get("orders_submitted"), source.get("orders_submitted")),
        ("broker_orders_submitted", payload.get("broker_orders_submitted"), source.get("broker_orders_submitted")),
    )
    mismatches: list[str] = []
    for label, profile_value, source_value in comparisons:
        summary[f"profile_{label}"] = profile_value
        summary[f"source_{label}"] = source_value
        if profile_value != source_value:
            mismatches.append(label)
            errors.append(
                "source experiment-programs "
                f"{label} differs from profile artifact: profile={profile_value!r} source={source_value!r}"
            )

    summary["mismatches"] = mismatches
    summary["status"] = "fail" if mismatches else "pass"
    return summary, errors

def _verify_experiment_programs_contract(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    safe_statuses = {"programs_prepared", "awaiting_paper_data", "awaiting_paper_evidence"}
    safe_loop_statuses = {"active", "awaiting_paper_data", "awaiting_paper_evidence"}
    evidence = _dict_value(payload.get("evidence"))
    loops = _dict_value(payload.get("loops"))
    mutation_counters = _dict_value(payload.get("mutation_counters"))
    status = str(payload.get("status") or "").strip()
    active_loop_ids = [
        str(loop.get("experiment_id"))
        for loop in loops.values()
        if isinstance(loop, dict)
        and loop.get("status") == "active"
        and loop.get("experiment_id")
    ]
    loop_statuses = {
        str(name): loop.get("status")
        for name, loop in loops.items()
        if isinstance(loop, dict)
    }
    source_alignment, source_errors = _verify_experiment_programs_source_alignment(payload)
    summary = {
        "status": status or None,
        "source_refresh_safe": payload.get("source_refresh_safe"),
        "experiment_programs_contract_safe": payload.get("experiment_programs_contract_safe"),
        "optimization_mode": payload.get("optimization_mode"),
        "live_order_authority": payload.get("live_order_authority"),
        "read_only_broker": payload.get("read_only_broker"),
        "broker_review_attempted": payload.get("broker_review_attempted"),
        "broker_place_attempted": payload.get("broker_place_attempted"),
        "sample_count": _strict_int_count(evidence.get("sample_count")),
        "calibrated_sample_count": _strict_int_count(evidence.get("calibrated_sample_count")),
        "repair_plan_status": evidence.get("repair_plan_status"),
        "repair_target_new_samples": _strict_int_count(evidence.get("repair_target_new_samples")),
        "repair_preferred_symbols": _string_list(evidence.get("repair_preferred_symbols")),
        "historical_policy_coverage_status": evidence.get("historical_policy_coverage_status"),
        "loop_statuses": loop_statuses,
        "active_loop_count": len(active_loop_ids),
        "active_loop_ids": active_loop_ids,
        "source_artifact_alignment": source_alignment,
    }
    errors: list[str] = list(source_errors)
    if payload.get("source_refresh_safe") is not True:
        errors.append("source_refresh_safe is not true")
    if payload.get("experiment_programs_contract_safe") is not True:
        errors.append("experiment_programs_contract_safe is not true")
    if payload.get("adapter_task") != "equity_experiment_programs":
        errors.append(f"adapter_task is not equity_experiment_programs: {payload.get('adapter_task')}")
    if status not in safe_statuses:
        errors.append(f"experiment-program status is not safe: {status or 'missing'}")
    if payload.get("optimization_mode") != "paper_feedback_only":
        errors.append(f"optimization_mode is not paper_feedback_only: {payload.get('optimization_mode')}")
    if payload.get("read_only_broker") is not True:
        errors.append("read_only_broker is not true")
    if payload.get("live_order_authority") not in {None, "none"}:
        errors.append(f"live_order_authority is not none: {payload.get('live_order_authority')}")
    if payload.get("broker_review_attempted") is not False:
        errors.append("broker_review_attempted is not false")
    if payload.get("broker_place_attempted") is not False:
        errors.append("broker_place_attempted is not false")
    for counter_name in REQUIRED_MUTATION_COUNTERS:
        value = _strict_int_count(mutation_counters.get(counter_name, payload.get(counter_name)))
        if value is None:
            errors.append(f"experiment-program mutation counter missing or not an integer: {counter_name}")
        elif value != 0:
            errors.append(f"experiment-program mutation counter is nonzero: {counter_name}={value}")
    if not evidence:
        errors.append("latest artifact missing experiment-program evidence")
    if evidence and evidence.get("live_order_authority") not in {None, "none"}:
        errors.append(f"experiment evidence live_order_authority is not none: {evidence.get('live_order_authority')}")
    if not loops:
        errors.append("latest artifact missing experiment loops")
    for name, loop in loops.items():
        if not isinstance(loop, dict):
            errors.append(f"experiment loop is not an object: {name}")
            continue
        if loop.get("status") not in safe_loop_statuses:
            errors.append(f"experiment loop {name} has unsafe status: {loop.get('status')}")
        if loop.get("live_order_authority") not in {None, "none"}:
            errors.append(f"experiment loop {name} live_order_authority is not none: {loop.get('live_order_authority')}")
    if status == "programs_prepared" and not active_loop_ids:
        errors.append("programs_prepared without active experiment loops")
    return summary, errors


def _verify_next_wake_runner_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_artifact_path(payload, "next-wake-runner.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source next-wake runner artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source next-wake runner artifact unreadable: {path}")
        return summary, errors

    source_safe_command_ids = _string_list(source.get("safe_command_ids"))
    source_bounded_collection_requested = (
        source.get("ready_now") is True
        or (
            source.get("due") is True
            and "bounded_paper_sample_collection" in set(source_safe_command_ids)
        )
        or source.get("required_operator_action") == "collect_bounded_paper_samples"
    )
    offhours_hold = payload.get("offhours_bounded_collection_blocked") is True
    summary["offhours_bounded_collection_overlay"] = offhours_hold
    summary["source_bounded_collection_requested"] = source_bounded_collection_requested

    comparisons = [
        ("generated_at", payload.get("generated_at"), source.get("generated_at")),
        ("due", payload.get("due"), source.get("due")),
        ("ready_now", payload.get("ready_now"), source.get("ready_now")),
        ("next_recheck_after_utc", payload.get("next_recheck_after_utc"), source.get("next_recheck_after_utc")),
        (
            "bounded_collection_not_before_utc",
            payload.get("bounded_collection_not_before_utc"),
            source.get("bounded_collection_not_before_utc"),
        ),
        ("budget_reopens_after_utc", payload.get("budget_reopens_after_utc"), source.get("budget_reopens_after_utc")),
        (
            "market_scan_recheck_after_utc",
            payload.get("market_scan_recheck_after_utc"),
            source.get("market_scan_recheck_after_utc"),
        ),
        ("required_operator_action", payload.get("required_operator_action"), source.get("required_operator_action")),
        ("wake_reason_ids", _string_list(payload.get("wake_reason_ids")), _string_list(source.get("wake_reason_ids"))),
        ("safe_command_ids", _string_list(payload.get("safe_command_ids")), source_safe_command_ids),
        ("commands_live_disabled", payload.get("commands_live_disabled"), source.get("commands_live_disabled")),
        ("broker_submit_allowed", payload.get("broker_submit_allowed"), source.get("broker_submit_allowed")),
        (
            "human_live_review_allowed",
            payload.get("human_live_review_allowed"),
            source.get("human_live_review_allowed"),
        ),
        ("live_order_authority", payload.get("live_order_authority"), source.get("live_order_authority")),
        ("mutation_counters", _dict_value(payload.get("mutation_counters")), _dict_value(source.get("mutation_counters"))),
        ("public_actions_taken", payload.get("public_actions_taken"), source.get("public_actions_taken")),
        ("external_mutations", payload.get("external_mutations"), source.get("external_mutations")),
        ("orders_submitted", payload.get("orders_submitted"), source.get("orders_submitted")),
        ("broker_orders_submitted", payload.get("broker_orders_submitted"), source.get("broker_orders_submitted")),
    ]
    if offhours_hold:
        expected_overlay = (
            ("status", payload.get("status"), "held_bounded_collection_offhours"),
            ("execute_requested", payload.get("execute_requested"), False),
            ("execution_attempted", payload.get("execution_attempted"), False),
            ("command_results", payload.get("command_results") or [], []),
            ("offhours_recheck_mode", payload.get("offhours_recheck_mode"), True),
            (
                "execution_block_reason",
                payload.get("execution_block_reason"),
                "bounded_paper_sample_collection_disabled_for_offhours_recheck",
            ),
        )
        if not source_bounded_collection_requested:
            errors.append("source next-wake runner did not request bounded collection for offhours hold")
        for label, profile_value, expected_value in expected_overlay:
            summary[f"profile_{label}"] = profile_value
            summary[f"expected_{label}"] = expected_value
            if profile_value != expected_value:
                errors.append(
                    "source next-wake runner offhours hold "
                    f"{label} is unsafe: profile={profile_value!r} expected={expected_value!r}"
                )
    else:
        comparisons.extend(
            [
                ("status", payload.get("status"), source.get("status")),
                ("execute_requested", payload.get("execute_requested"), source.get("execute_requested")),
                ("execution_attempted", payload.get("execution_attempted"), source.get("execution_attempted")),
                ("command_results", payload.get("command_results") or [], source.get("command_results") or []),
            ]
        )

    mismatches: list[str] = []
    for label, profile_value, source_value in comparisons:
        summary[f"profile_{label}"] = profile_value
        summary[f"source_{label}"] = source_value
        if profile_value != source_value:
            mismatches.append(label)
            errors.append(
                "source next-wake runner "
                f"{label} differs from profile artifact: profile={profile_value!r} source={source_value!r}"
            )

    summary["mismatches"] = mismatches
    summary["status"] = "fail" if errors else "pass"
    return summary, errors


def _verify_go_live_packet_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_artifact_path(payload, "go-live-operator-packet.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source go-live packet artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source go-live packet artifact unreadable: {path}")
        return summary, errors

    comparisons = (
        ("generated_at", payload.get("generated_at"), source.get("generated_at")),
        ("schema_version", payload.get("schema_version"), source.get("schema_version")),
        ("status", payload.get("status"), source.get("status")),
        ("status_scope", payload.get("status_scope"), source.get("status_scope")),
        ("ready_to_submit", payload.get("ready_to_submit"), source.get("ready_to_submit")),
        ("go_live_blocked", payload.get("go_live_blocked"), source.get("go_live_blocked")),
        ("resolved_signal_id", payload.get("resolved_signal_id"), source.get("resolved_signal_id")),
        ("requested_signal_id", payload.get("requested_signal_id"), source.get("requested_signal_id")),
        ("state_root", payload.get("state_root"), source.get("state_root")),
        ("artifact_path", payload.get("artifact_path"), source.get("artifact_path")),
        ("latest_research_candidate", payload.get("latest_research_candidate"), source.get("latest_research_candidate")),
        ("blockers", payload.get("blockers") or [], source.get("blockers") or []),
        ("evidence_gates", _dict_value(payload.get("evidence_gates")), _dict_value(source.get("evidence_gates"))),
        ("paper_performance", _dict_value(payload.get("paper_performance")), _dict_value(source.get("paper_performance"))),
        ("paper_calibration", _dict_value(payload.get("paper_calibration")), _dict_value(source.get("paper_calibration"))),
        ("paper_outcome", _dict_value(payload.get("paper_outcome")), _dict_value(source.get("paper_outcome"))),
        (
            "paper_evidence_runway",
            _dict_value(payload.get("paper_evidence_runway")),
            _dict_value(source.get("paper_evidence_runway")),
        ),
        ("risk_incident", _dict_value(payload.get("risk_incident")), _dict_value(source.get("risk_incident"))),
        ("live_status", _dict_value(payload.get("live_status")), _dict_value(source.get("live_status"))),
        ("mcp_readiness", _dict_value(payload.get("mcp_readiness")), _dict_value(source.get("mcp_readiness"))),
        ("research", _dict_value(payload.get("research")), _dict_value(source.get("research"))),
        ("operator_mandate", _dict_value(payload.get("operator_mandate")), _dict_value(source.get("operator_mandate"))),
        ("approval", _dict_value(payload.get("approval")), _dict_value(source.get("approval"))),
        ("command_gates", _dict_value(payload.get("command_gates")), _dict_value(source.get("command_gates"))),
        ("commands", _dict_value(payload.get("commands")), _dict_value(source.get("commands"))),
        ("next_actions", payload.get("next_actions") or [], source.get("next_actions") or []),
        ("promotion", _dict_value(payload.get("promotion")), _dict_value(source.get("promotion"))),
        ("canary", _dict_value(payload.get("canary")), _dict_value(source.get("canary"))),
        ("read_only", payload.get("read_only"), source.get("read_only")),
        ("broker_review_attempted", payload.get("broker_review_attempted"), source.get("broker_review_attempted")),
        ("broker_place_attempted", payload.get("broker_place_attempted"), source.get("broker_place_attempted")),
        ("approval_created", payload.get("approval_created"), source.get("approval_created")),
        ("approval_modified", payload.get("approval_modified"), source.get("approval_modified")),
        (
            "halt_or_circuit_cleared",
            payload.get("halt_or_circuit_cleared"),
            source.get("halt_or_circuit_cleared"),
        ),
        ("live_flags_enabled", payload.get("live_flags_enabled"), source.get("live_flags_enabled")),
        ("local_artifact_written", payload.get("local_artifact_written"), source.get("local_artifact_written")),
        ("mutation_counters", _dict_value(payload.get("mutation_counters")), _dict_value(source.get("mutation_counters"))),
        ("public_actions_taken", payload.get("public_actions_taken"), source.get("public_actions_taken")),
        ("external_mutations", payload.get("external_mutations"), source.get("external_mutations")),
        ("orders_submitted", payload.get("orders_submitted"), source.get("orders_submitted")),
        ("broker_orders_submitted", payload.get("broker_orders_submitted"), source.get("broker_orders_submitted")),
    )
    mismatches: list[str] = []
    for label, profile_value, source_value in comparisons:
        summary[f"profile_{label}"] = profile_value
        summary[f"source_{label}"] = source_value
        if profile_value != source_value:
            mismatches.append(label)
            errors.append(
                "source go-live packet "
                f"{label} differs from profile artifact: profile={profile_value!r} source={source_value!r}"
            )

    summary["mismatches"] = mismatches
    summary["status"] = "fail" if mismatches else "pass"
    return summary, errors


def _verify_go_live_packet_contract(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    gate = _dict_value(_dict_value(payload.get("command_gates")).get("one_shot_live_submit"))
    commands = _dict_value(payload.get("commands"))
    mandate = _dict_value(payload.get("operator_mandate"))
    mutation_counters = _dict_value(payload.get("mutation_counters"))
    status = str(payload.get("status") or "").strip()
    ready_to_submit = payload.get("ready_to_submit") is True
    go_live_blocked = payload.get("go_live_blocked") is True
    source_alignment, source_errors = _verify_go_live_packet_source_alignment(payload)
    summary = {
        "status": status or None,
        "ready_to_submit": ready_to_submit,
        "go_live_blocked": go_live_blocked,
        "resolved_signal_id": payload.get("resolved_signal_id"),
        "source_refresh_safe": payload.get("source_refresh_safe"),
        "go_live_packet_contract_safe": payload.get("go_live_packet_contract_safe"),
        "read_only": payload.get("read_only"),
        "broker_review_attempted": payload.get("broker_review_attempted"),
        "broker_place_attempted": payload.get("broker_place_attempted"),
        "approval_created": payload.get("approval_created"),
        "approval_modified": payload.get("approval_modified"),
        "halt_or_circuit_cleared": payload.get("halt_or_circuit_cleared"),
        "live_flags_enabled": payload.get("live_flags_enabled"),
        "live_order_authority": payload.get("live_order_authority"),
        "operator_approval_scope": mandate.get("required_approval_scope"),
        "self_approval_allowed": mandate.get("self_approval_allowed"),
        "one_shot_live_submit_available": gate.get("available"),
        "one_shot_live_submit_reason": gate.get("reason"),
        "one_shot_live_submit_blocked_by": _string_list(gate.get("blocked_by")),
        "one_shot_live_submit_command_present": bool(commands.get("one_shot_live_submit")),
        "one_shot_live_submit_command_safe": _go_live_submit_command_safe(commands.get("one_shot_live_submit")),
        "source_artifact_alignment": source_alignment,
    }
    errors: list[str] = list(source_errors)
    if payload.get("source_refresh_safe") is not True:
        errors.append("source_refresh_safe is not true")
    if payload.get("go_live_packet_contract_safe") is not True:
        errors.append("go_live_packet_contract_safe is not true")
    if payload.get("adapter_task") != "equity_go_live_operator_packet":
        errors.append(f"adapter_task is not equity_go_live_operator_packet: {payload.get('adapter_task')}")
    if payload.get("schema_version") != "equity_go_live_operator_packet_v1":
        errors.append(f"schema_version is not equity_go_live_operator_packet_v1: {payload.get('schema_version')}")
    if payload.get("read_only") is not True:
        errors.append("read_only is not true")
    if payload.get("broker_review_attempted") is not False:
        errors.append("broker_review_attempted is not false")
    if payload.get("broker_place_attempted") is not False:
        errors.append("broker_place_attempted is not false")
    if payload.get("approval_created") is not False:
        errors.append("approval_created is not false")
    if payload.get("approval_modified") is not False:
        errors.append("approval_modified is not false")
    if payload.get("halt_or_circuit_cleared") is not False:
        errors.append("halt_or_circuit_cleared is not false")
    if payload.get("live_flags_enabled") is not False:
        errors.append("live_flags_enabled is not false")
    if payload.get("live_order_authority") not in {None, "none"}:
        errors.append(f"live_order_authority is not none: {payload.get('live_order_authority')}")
    if mandate.get("human_approval_required") is not True:
        errors.append("operator_mandate human_approval_required is not true")
    if mandate.get("self_approval_allowed") is not False:
        errors.append("operator_mandate self_approval_allowed is not false")
    if mandate.get("required_approval_scope") != "one_shot_live_canary":
        errors.append(
            "operator_mandate required_approval_scope is not one_shot_live_canary: "
            f"{mandate.get('required_approval_scope')}"
        )
    for counter_name in REQUIRED_MUTATION_COUNTERS:
        value = _strict_int_count(mutation_counters.get(counter_name, payload.get(counter_name)))
        if value is None:
            errors.append(f"go-live packet mutation counter missing or not an integer: {counter_name}")
        elif value != 0:
            errors.append(f"go-live packet mutation counter is nonzero: {counter_name}={value}")

    if status == "blocked":
        if ready_to_submit:
            errors.append("blocked go-live packet ready_to_submit is true")
        if not go_live_blocked:
            errors.append("blocked go-live packet go_live_blocked is not true")
        if gate.get("available") is not False:
            errors.append("blocked go-live packet one_shot_live_submit gate is not unavailable")
        if commands.get("one_shot_live_submit") is not None:
            errors.append("blocked go-live packet one_shot_live_submit command is present")
    elif status == "ready_to_submit":
        if not ready_to_submit:
            errors.append("ready go-live packet ready_to_submit is not true")
        if go_live_blocked:
            errors.append("ready go-live packet go_live_blocked is true")
        if gate.get("available") is not True:
            errors.append("ready go-live packet one_shot_live_submit gate is not available")
        if not commands.get("one_shot_live_submit"):
            errors.append("ready go-live packet one_shot_live_submit command missing")
        elif not _go_live_submit_command_safe(commands.get("one_shot_live_submit")):
            errors.append("ready go-live packet one_shot_live_submit command missing scoped live flags")
    else:
        errors.append(f"go-live packet status is not blocked or ready_to_submit: {status or 'missing'}")
    return summary, errors


def _go_live_submit_command_safe(command: object) -> bool:
    text = str(command or "")
    return (
        "RATATOSK_LIVE_TRADING=true" in text
        and "ROBINHOOD_LIVE=true" in text
        and "ROBINHOOD_EQUITY_LIVE=true" in text
    )



def _verify_repair_window_simulation_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_artifact_path(payload, "repair-window-simulation.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source repair-window simulation artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source repair-window simulation artifact unreadable: {path}")
        return summary, errors

    comparisons = (
        ("generated_at", payload.get("generated_at"), source.get("generated_at")),
        ("status", payload.get("status"), source.get("status")),
        ("reason", payload.get("reason"), source.get("reason")),
        ("repair_plan_source", payload.get("repair_plan_source"), source.get("repair_plan_source")),
        ("repair_plan", _dict_value(payload.get("repair_plan")), _dict_value(source.get("repair_plan"))),
        ("requested_samples", payload.get("requested_samples"), source.get("requested_samples")),
        ("preferred_symbols", _string_list(payload.get("preferred_symbols")), _string_list(source.get("preferred_symbols"))),
        ("candidate_symbols", _string_list(payload.get("candidate_symbols")), _string_list(source.get("candidate_symbols"))),
        ("checks", _dict_value(payload.get("checks")), _dict_value(source.get("checks"))),
        ("source_state_root", payload.get("source_state_root"), source.get("source_state_root")),
        ("simulation_state_root", payload.get("simulation_state_root"), source.get("simulation_state_root")),
        ("live_order_authority", payload.get("live_order_authority"), source.get("live_order_authority")),
        ("public_actions_taken", payload.get("public_actions_taken"), source.get("public_actions_taken")),
        ("external_mutations", payload.get("external_mutations"), source.get("external_mutations")),
        ("orders_submitted", payload.get("orders_submitted"), source.get("orders_submitted")),
        ("broker_orders_submitted", payload.get("broker_orders_submitted"), source.get("broker_orders_submitted")),
    )
    mismatches: list[str] = []
    for label, profile_value, source_value in comparisons:
        summary[f"profile_{label}"] = profile_value
        summary[f"source_{label}"] = source_value
        if profile_value != source_value:
            mismatches.append(label)
            errors.append(
                "source repair-window simulation "
                f"{label} differs from profile artifact: profile={profile_value!r} source={source_value!r}"
            )

    summary["mismatches"] = mismatches
    summary["status"] = "fail" if mismatches else "pass"
    return summary, errors

def _verify_repair_window_simulation_contract(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    checks = _dict_value(payload.get("checks"))
    repair_plan = _dict_value(payload.get("repair_plan"))
    mutation_counters = _dict_value(payload.get("mutation_counters"))
    requested_samples = _strict_int_count(payload.get("requested_samples"))
    status = str(payload.get("status") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    candidate_symbols = _string_list(payload.get("candidate_symbols"))
    source_alignment, source_errors = _verify_repair_window_simulation_source_alignment(payload)
    summary = {
        "status": status or None,
        "reason": reason or None,
        "repair_plan_source": payload.get("repair_plan_source"),
        "repair_plan_status": repair_plan.get("status"),
        "repair_target_new_samples": _strict_int_count(repair_plan.get("target_new_samples")),
        "repair_samples_remaining": _strict_int_count(repair_plan.get("repair_samples_remaining")),
        "repair_preferred_existing_symbols": _string_list(repair_plan.get("preferred_existing_symbols")),
        "requested_samples": requested_samples,
        "candidate_symbols": candidate_symbols,
        "simulation_state_root": payload.get("simulation_state_root"),
        "source_refresh_safe": payload.get("source_refresh_safe"),
        "simulation_contract_safe": payload.get("simulation_contract_safe"),
        "live_order_authority": payload.get("live_order_authority"),
        "checks": checks,
        "source_artifact_alignment": source_alignment,
    }
    errors: list[str] = list(source_errors)
    if payload.get("source_refresh_safe") is not True:
        errors.append("source_refresh_safe is not true")
    if payload.get("simulation_contract_safe") is not True:
        errors.append("simulation_contract_safe is not true")
    if payload.get("live_order_authority") not in {None, "none"}:
        errors.append(f"live_order_authority is not none: {payload.get('live_order_authority')}")
    for counter_name in REQUIRED_MUTATION_COUNTERS:
        value = _strict_int_count(mutation_counters.get(counter_name, payload.get(counter_name)))
        if value is None:
            errors.append(f"repair-window mutation counter missing or not an integer: {counter_name}")
        elif value != 0:
            errors.append(f"repair-window mutation counter is nonzero: {counter_name}={value}")

    pass_required_checks = (
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
    skipped_required_checks = (
        "isolated_state_root",
        "source_state_sample_artifacts_unchanged",
        "live_order_authority_none",
        "zero_mutation_counters",
        "broker_review_not_attempted",
        "broker_place_not_attempted",
    )
    if status == "pass":
        if requested_samples is None or requested_samples <= 0:
            errors.append(f"pass status has invalid requested_samples: {payload.get('requested_samples')}")
        if not candidate_symbols:
            errors.append("pass status missing candidate_symbols")
        for check_name in pass_required_checks:
            if checks.get(check_name) is not True:
                errors.append(f"repair-window check {check_name} is not true")
    elif status == "skipped":
        if reason not in {"no_active_repair_plan", "repair_plan_requested_zero_samples"}:
            errors.append(f"skipped repair-window reason is not safe: {reason or 'missing'}")
        for check_name in skipped_required_checks:
            if checks.get(check_name) is not True:
                errors.append(f"repair-window skipped check {check_name} is not true")
    else:
        errors.append(f"repair-window status is not pass or skipped: {status or 'missing'}")
    return summary, errors


def _verify_risk_monitor_source_alignment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path = _source_refresh_artifact_path(payload, "risk-monitor.json")
    summary: dict[str, Any] = {"status": "not_available"}
    errors: list[str] = []
    if path is None:
        return summary, errors

    summary.update(
        {
            "status": "checked",
            "source_artifact_path": str(path),
            "source_artifact_exists": path.exists(),
        }
    )
    if not path.exists():
        summary["status"] = "fail"
        errors.append(f"source risk monitor artifact missing: {path}")
        return summary, errors

    source = _load_json(path)
    if not source:
        summary["status"] = "fail"
        errors.append(f"source risk monitor artifact unreadable: {path}")
        return summary, errors

    comparisons = (
        ("generated_at", payload.get("generated_at"), source.get("generated_at")),
        ("status", payload.get("status"), source.get("status")),
        ("state_root", payload.get("state_root"), source.get("state_root")),
        ("artifact_path", payload.get("artifact_path"), source.get("artifact_path")),
        ("blocking_reasons", payload.get("blocking_reasons") or [], source.get("blocking_reasons") or []),
        ("warning_reasons", payload.get("warning_reasons") or [], source.get("warning_reasons") or []),
        ("stop_condition", _dict_value(payload.get("stop_condition")), _dict_value(source.get("stop_condition"))),
        (
            "paper_evidence_runway",
            _dict_value(payload.get("paper_evidence_runway")),
            _dict_value(source.get("paper_evidence_runway")),
        ),
        ("evidence_wait_packet", _dict_value(payload.get("evidence_wait_packet")), _dict_value(source.get("evidence_wait_packet"))),
        ("live_status", _dict_value(payload.get("live_status")), _dict_value(source.get("live_status"))),
        ("live_order_gate", _dict_value(payload.get("live_order_gate")), _dict_value(source.get("live_order_gate"))),
        ("risk_incident", _dict_value(payload.get("risk_incident")), _dict_value(source.get("risk_incident"))),
        (
            "role_separation_audit",
            _dict_value(payload.get("role_separation_audit")),
            _dict_value(source.get("role_separation_audit")),
        ),
        (
            "verifier_debt_audit",
            _dict_value(payload.get("verifier_debt_audit")),
            _dict_value(source.get("verifier_debt_audit")),
        ),
        (
            "historical_strategy_gate",
            _dict_value(payload.get("historical_strategy_gate")),
            _dict_value(source.get("historical_strategy_gate")),
        ),
        ("historical_verifier", _dict_value(payload.get("historical_verifier")), _dict_value(source.get("historical_verifier"))),
        ("paper_performance", _dict_value(payload.get("paper_performance")), _dict_value(source.get("paper_performance"))),
        ("paper_calibration", _dict_value(payload.get("paper_calibration")), _dict_value(source.get("paper_calibration"))),
        (
            "experiment_evaluation",
            _dict_value(payload.get("experiment_evaluation")),
            _dict_value(source.get("experiment_evaluation")),
        ),
        (
            "active_experiment_sample_window",
            _dict_value(payload.get("active_experiment_sample_window")),
            _dict_value(source.get("active_experiment_sample_window")),
        ),
        ("signal_optimizer", _dict_value(payload.get("signal_optimizer")), _dict_value(source.get("signal_optimizer"))),
        (
            "research_candidate_supply",
            _dict_value(payload.get("research_candidate_supply")),
            _dict_value(source.get("research_candidate_supply")),
        ),
        ("heartbeat", _dict_value(payload.get("heartbeat")), _dict_value(source.get("heartbeat"))),
        ("upstream_mutations", _dict_value(payload.get("upstream_mutations")), _dict_value(source.get("upstream_mutations"))),
        ("next_actions", payload.get("next_actions") or [], source.get("next_actions") or []),
        ("read_only", payload.get("read_only"), source.get("read_only")),
        ("broker_review_attempted", payload.get("broker_review_attempted"), source.get("broker_review_attempted")),
        ("broker_place_attempted", payload.get("broker_place_attempted"), source.get("broker_place_attempted")),
        ("persisted", payload.get("persisted"), source.get("persisted")),
        ("public_actions_taken", payload.get("public_actions_taken"), source.get("public_actions_taken")),
        ("external_mutations", payload.get("external_mutations"), source.get("external_mutations")),
        ("orders_submitted", payload.get("orders_submitted"), source.get("orders_submitted")),
        ("broker_orders_submitted", payload.get("broker_orders_submitted"), source.get("broker_orders_submitted")),
    )
    mismatches: list[str] = []
    for label, profile_value, source_value in comparisons:
        summary[f"profile_{label}"] = profile_value
        summary[f"source_{label}"] = source_value
        if profile_value != source_value:
            mismatches.append(label)
            errors.append(
                "source risk monitor "
                f"{label} differs from profile artifact: profile={profile_value!r} source={source_value!r}"
            )

    summary["mismatches"] = mismatches
    summary["status"] = "fail" if mismatches else "pass"
    return summary, errors


def _verify_loop_readiness_ledger(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    ledger = _dict_value(payload.get("loop_readiness_ledger"))
    current = _dict_value(ledger.get("current_state"))
    stop_condition = _dict_value(current.get("stop_condition"))
    runway = _dict_value(current.get("paper_evidence_runway"))
    go_live = _dict_value(current.get("go_live"))
    halt_and_circuit = _dict_value(current.get("halt_and_circuit_breaker"))
    promotion_controls = _dict_value(current.get("live_promotion_controls"))
    operator_approval = _dict_value(promotion_controls.get("operator_approval"))
    live_flags = _dict_value(promotion_controls.get("live_flags"))
    optimizer_evidence = _dict_value(current.get("optimizer_evidence"))
    optimizer_repair = _dict_value(optimizer_evidence.get("calibration_repair_plan"))
    paper_gates = _dict_value(current.get("paper_verifier_gates"))
    paper_requirements = _dict_value(ledger.get("paper_requirements"))
    self_improvement = _dict_value(paper_requirements.get("self_improvement"))
    raw_gaps = ledger.get("blocking_gaps") if isinstance(ledger.get("blocking_gaps"), list) else []
    gaps = [
        str(item.get("id"))
        for item in raw_gaps
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    gap_actions = _blocking_gap_action_summaries(raw_gaps)
    bounded_paper_optimization = _loop_readiness_bounded_paper_optimization_safe(
        current=current,
        stop_condition=stop_condition,
        runway=runway,
        optimizer_evidence=optimizer_evidence,
        optimizer_repair=optimizer_repair,
    )
    source_alignment, source_errors = _verify_risk_monitor_source_alignment(payload)
    summary = {
        "present": bool(ledger),
        "status": ledger.get("status"),
        "ledger_status": ledger.get("ledger_status"),
        "implementation_status": ledger.get("implementation_status"),
        "bounded_paper_optimization": bounded_paper_optimization,
        "safe_operator_action": current.get("safe_operator_action"),
        "stop_condition_status": stop_condition.get("status"),
        "paper_runway_status": runway.get("status"),
        "commands_live_disabled": runway.get("commands_live_disabled"),
        "go_live_status": go_live.get("status"),
        "ready_to_submit": go_live.get("ready_to_submit"),
        "go_live_blocked": go_live.get("go_live_blocked"),
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
        "optimizer_repair_status": optimizer_repair.get("status"),
        "optimizer_sample_budget_open": optimizer_evidence.get("sample_budget_open"),
        "paper_verifier_status": paper_gates.get("status"),
        "paper_performance_status": paper_gates.get("performance_status"),
        "paper_calibration_status": paper_gates.get("calibration_status"),
        "paper_blocked_gate_ids": [
            str(item)
            for item in paper_gates.get("blocked_gate_ids") or []
            if str(item).strip()
        ],
        "blocking_gap_ids": gaps,
        "blocking_gap_actions": gap_actions,
        "self_improvement_status": self_improvement.get("status"),
        "retrospective_lesson_count": self_improvement.get("lesson_count"),
        "paper_trade_retrospective_count": self_improvement.get("paper_trade_retrospective_count"),
        "retrospective_policy_live_order_authority": self_improvement.get("policy_live_order_authority"),
        "source_artifact_alignment": source_alignment,
    }
    errors: list[str] = list(source_errors)
    if not ledger:
        return summary, ["latest artifact missing loop_readiness_ledger"]
    if ledger.get("task") not in {None, "equity_loop_readiness_ledger"}:
        errors.append(f"loop_readiness_ledger task mismatch: {ledger.get('task')}")
    if ledger.get("ledger_status") != "pass":
        errors.append(f"loop_readiness_ledger ledger_status is not pass: {ledger.get('ledger_status')}")
    if ledger.get("status") != "blocked":
        errors.append(f"loop_readiness_ledger status is not blocked: {ledger.get('status')}")
    if ledger.get("implementation_status") != "stage_only_production_ready_live_blocked":
        errors.append(
            "loop_readiness_ledger implementation_status is not "
            f"stage_only_production_ready_live_blocked: {ledger.get('implementation_status')}"
        )
    if (
        current.get("safe_operator_action") != WAIT_FOR_EVIDENCE_ACTION_ID
        and not bounded_paper_optimization
    ):
        errors.append(
            "loop_readiness_ledger safe_operator_action is not wait_for_oos_or_market_data: "
            f"{current.get('safe_operator_action')}"
        )
    if go_live.get("status") != "blocked" or go_live.get("go_live_blocked") is not True:
        errors.append("loop_readiness_ledger go_live is not blocked")
    if go_live.get("ready_to_submit") is not False:
        errors.append("loop_readiness_ledger ready_to_submit is not false")
    if runway.get("commands_live_disabled") is not True:
        errors.append("loop_readiness_ledger paper runway commands are not live-disabled")
    if stop_condition.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger stop condition live_order_authority is not none: "
            f"{stop_condition.get('live_order_authority')}"
        )
    if runway.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger paper runway live_order_authority is not none: "
            f"{runway.get('live_order_authority')}"
        )
    if halt_and_circuit.get("status") not in {"blocked", "clear"}:
        errors.append(
            "loop_readiness_ledger halt_and_circuit_breaker status is not blocked or clear: "
            f"{halt_and_circuit.get('status')}"
        )
    if halt_and_circuit.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger halt_and_circuit_breaker live_order_authority is not none: "
            f"{halt_and_circuit.get('live_order_authority')}"
        )
    if operator_approval.get("status") not in {"missing_or_invalid", "approved"}:
        errors.append(
            "loop_readiness_ledger operator_approval status is not missing_or_invalid or approved: "
            f"{operator_approval.get('status')}"
        )
    if operator_approval.get("required_scope") not in {None, "one_shot_live_canary"}:
        errors.append(
            "loop_readiness_ledger operator_approval required_scope is not one_shot_live_canary: "
            f"{operator_approval.get('required_scope')}"
        )
    if operator_approval.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger operator_approval live_order_authority is not none: "
            f"{operator_approval.get('live_order_authority')}"
        )
    if live_flags.get("status") not in {"disabled_until_final_gate", "scoped_clear"}:
        errors.append(
            "loop_readiness_ledger live_flags status is not disabled_until_final_gate or scoped_clear: "
            f"{live_flags.get('status')}"
        )
    if live_flags.get("enabled_now") is not False:
        errors.append("loop_readiness_ledger live_flags enabled_now is not false")
    if live_flags.get("one_shot_live_submit_available") is not False:
        errors.append("loop_readiness_ledger one_shot_live_submit_available is not false")
    if live_flags.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger live_flags live_order_authority is not none: "
            f"{live_flags.get('live_order_authority')}"
        )
    if optimizer_evidence.get("status") not in {"blocked", "pass"}:
        errors.append(
            "loop_readiness_ledger optimizer_evidence status is not blocked or pass: "
            f"{optimizer_evidence.get('status')}"
        )
    if optimizer_evidence.get("sample_budget_open") is not False and not bounded_paper_optimization:
        errors.append("loop_readiness_ledger optimizer_evidence sample_budget_open is not false")
    if optimizer_evidence.get("paper_feedback_only") is not True:
        errors.append("loop_readiness_ledger optimizer_evidence paper_feedback_only is not true")
    if optimizer_evidence.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger optimizer_evidence live_order_authority is not none: "
            f"{optimizer_evidence.get('live_order_authority')}"
        )
    if optimizer_repair.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger optimizer repair live_order_authority is not none: "
            f"{optimizer_repair.get('live_order_authority')}"
        )
    if paper_gates.get("status") not in {"blocked", "pass"}:
        errors.append(
            "loop_readiness_ledger paper_verifier_gates status is not blocked or pass: "
            f"{paper_gates.get('status')}"
        )
    if not isinstance(paper_gates.get("blocked_gate_ids"), list):
        errors.append("loop_readiness_ledger paper_verifier_gates blocked_gate_ids is not a list")
    if paper_gates.get("live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger paper_verifier_gates live_order_authority is not none: "
            f"{paper_gates.get('live_order_authority')}"
        )
    for gap in raw_gaps:
        if not isinstance(gap, dict):
            continue
        gap_id = gap.get("id") or "unknown"
        if not str(gap.get("operator_action") or "").strip():
            errors.append(f"loop_readiness_ledger blocking gap missing operator_action: {gap_id}")
        if gap.get("live_order_authority") not in {None, "none"}:
            errors.append(
                "loop_readiness_ledger blocking gap live_order_authority is not none: "
                f"{gap_id}={gap.get('live_order_authority')}"
            )
    if self_improvement.get("status") != "pass":
        errors.append(
            "loop_readiness_ledger self_improvement status is not pass: "
            f"{self_improvement.get('status')}"
        )
    if _int_count(self_improvement.get("lesson_count")) <= 0:
        errors.append("loop_readiness_ledger self_improvement lesson_count is not positive")
    if _int_count(self_improvement.get("paper_trade_retrospective_count")) <= 0:
        errors.append("loop_readiness_ledger self_improvement paper_trade_retrospective_count is not positive")
    if self_improvement.get("policy_live_order_authority") not in {None, "none"}:
        errors.append(
            "loop_readiness_ledger self_improvement policy_live_order_authority is not none: "
            f"{self_improvement.get('policy_live_order_authority')}"
        )
    for counter_name in REQUIRED_MUTATION_COUNTERS:
        if counter_name not in ledger:
            errors.append(f"loop_readiness_ledger missing mutation counter: {counter_name}")
            continue
        count = _strict_int_count(ledger.get(counter_name))
        if count is None:
            errors.append(f"loop_readiness_ledger mutation counter is not an integer: {counter_name}")
        elif count != 0:
            errors.append(f"loop_readiness_ledger {counter_name} is nonzero: {count}")
    return summary, errors


def _loop_readiness_bounded_paper_optimization_safe(
    *,
    current: dict[str, Any],
    stop_condition: dict[str, Any],
    runway: dict[str, Any],
    optimizer_evidence: dict[str, Any],
    optimizer_repair: dict[str, Any],
) -> bool:
    return (
        current.get("safe_operator_action") == BOUNDED_PAPER_ACTION_ID
        and stop_condition.get("status") == "continue_paper_optimization"
        and stop_condition.get("primary_next_action") == BOUNDED_PAPER_PRIMARY_ACTION_ID
        and BOUNDED_PAPER_ACTION_ID in _string_list(stop_condition.get("recommended_action_ids"))
        and _int_count(stop_condition.get("max_new_samples")) > 0
        and _int_count(stop_condition.get("max_iterations")) > 0
        and stop_condition.get("live_order_authority") in {None, "none"}
        and runway.get("status") == "continue_paper_optimization"
        and runway.get("safe_operator_action") == BOUNDED_PAPER_ACTION_ID
        and runway.get("commands_live_disabled") is True
        and _int_count(runway.get("max_new_samples")) > 0
        and _int_count(runway.get("max_iterations")) > 0
        and runway.get("live_order_authority") in {None, "none"}
        and optimizer_evidence.get("sample_budget_open") is True
        and optimizer_evidence.get("paper_feedback_only") is True
        and optimizer_evidence.get("live_order_authority") in {None, "none"}
        and optimizer_repair.get("status") == "needs_repair_samples"
        and _int_count(optimizer_repair.get("target_new_samples")) > 0
        and _int_count(optimizer_repair.get("repair_samples_remaining")) > 0
        and optimizer_repair.get("live_order_authority") in {None, "none"}
    )


def _blocking_gap_action_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    gaps: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        blockers = _string_list(item.get("blockers"))
        gaps.append({
            "id": item.get("id"),
            "status": item.get("status"),
            "operator_action": item.get("operator_action"),
            "release_condition": item.get("release_condition"),
            "verification_artifacts": _string_list(item.get("verification_artifacts")),
            "blocker_count": len(blockers),
            "live_order_authority": item.get("live_order_authority"),
        })
    return gaps


def _script_path(profile_home: Path, script: str | None) -> Path | None:
    if not script:
        return None
    path = Path(script)
    if path.is_absolute():
        return path
    return profile_home / "scripts" / script


def _compile_script(path: Path) -> tuple[bool, str | None]:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return False, str(exc)
    return True, None


def verify_torben_live_profile(
    *,
    profile_home: str | Path,
    repo_snapshot_home: str | Path | None = None,
    check_snapshot_sync: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = Path(profile_home)
    jobs_path = profile / "cron" / "jobs.json"
    snapshot = Path(repo_snapshot_home) if repo_snapshot_home else None
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []

    if not profile.exists():
        return {
            "task": "torben_live_profile_verify",
            "wakeAgent": True,
            "generated_at": _utc_now(),
            "status": "fail",
            "profile_home": str(profile),
            "errors": [f"profile_home missing: {profile}"],
            "warnings": [],
            "script_checks": [],
        }
    if not jobs_path.exists():
        return {
            "task": "torben_live_profile_verify",
            "wakeAgent": True,
            "generated_at": _utc_now(),
            "status": "fail",
            "profile_home": str(profile),
            "errors": [f"cron jobs file missing: {jobs_path}"],
            "warnings": [],
            "script_checks": [],
        }

    jobs = _load_jobs(jobs_path)
    checks: list[ScriptCheck] = []
    for job in jobs:
        enabled = bool(job.get("enabled", True))
        script = str(job.get("script") or "").strip() or None
        name = str(job.get("name") or job.get("id") or "unnamed")
        live_path = _script_path(profile, script)
        check = ScriptCheck(
            name=name,
            enabled=enabled,
            script=script,
            live_path=str(live_path) if live_path else None,
            last_status=job.get("last_status"),
            last_error=job.get("last_error"),
            last_delivery_error=job.get("last_delivery_error"),
        )
        checks.append(check)

        if not enabled:
            continue
        if not script:
            continue
        if live_path is None or not live_path.exists():
            check.errors.append(f"enabled cron script missing: {live_path}")
            continue
        check.exists = True
        compiles, compile_error = _compile_script(live_path)
        check.compiles = compiles
        if not compiles:
            check.errors.append(f"script does not compile: {compile_error}")

        ignore_stale_self_status = script == "torben_live_profile_verify.py"
        if job.get("last_error") and not ignore_stale_self_status:
            check.errors.append(f"last_error is set: {job.get('last_error')}")
        elif job.get("last_error"):
            check.warnings.append(f"ignoring stale verifier self last_error: {job.get('last_error')}")
        if job.get("last_delivery_error") and not ignore_stale_self_status:
            check.errors.append(f"last_delivery_error is set: {job.get('last_delivery_error')}")
        elif job.get("last_delivery_error"):
            check.warnings.append(
                f"ignoring stale verifier self last_delivery_error: {job.get('last_delivery_error')}"
            )
        if (
            str(job.get("last_status") or "").lower() in {"error", "failed", "fail"}
            and not ignore_stale_self_status
        ):
            check.errors.append(f"last_status is failing: {job.get('last_status')}")
        elif str(job.get("last_status") or "").lower() in {"error", "failed", "fail"}:
            check.warnings.append(f"ignoring stale verifier self last_status: {job.get('last_status')}")

        if check_snapshot_sync and snapshot is not None and script and not Path(script).is_absolute():
            snapshot_script = snapshot / "scripts" / script
            if not snapshot_script.exists():
                check.warnings.append(f"repo snapshot script missing: {snapshot_script}")
                check.snapshot_in_sync = None
            else:
                check.snapshot_in_sync = snapshot_script.read_bytes() == live_path.read_bytes()
                if not check.snapshot_in_sync:
                    check.errors.append(f"live script differs from repo snapshot: {snapshot_script}")

    for check in checks:
        errors.extend(f"{check.name}: {error}" for error in check.errors)
        warnings.extend(f"{check.name}: {warning}" for warning in check.warnings)

    gmail_realtime_health = _verify_gmail_realtime_health(profile, jobs, now_utc)
    errors.extend(f"gmail_realtime: {error}" for error in gmail_realtime_health.get("errors") or [])
    warnings.extend(f"gmail_realtime: {warning}" for warning in gmail_realtime_health.get("warnings") or [])
    finance_cron_snapshot = _verify_finance_cron_snapshot(profile, jobs)
    errors.extend(f"finance_cron_snapshot: {error}" for error in finance_cron_snapshot.get("errors") or [])
    warnings.extend(
        f"finance_cron_snapshot: {warning}" for warning in finance_cron_snapshot.get("warnings") or []
    )
    backend_artifact_health = _verify_backend_artifact_health(profile, jobs)
    errors.extend(f"backend_artifacts: {error}" for error in backend_artifact_health.get("errors") or [])
    warnings.extend(f"backend_artifacts: {warning}" for warning in backend_artifact_health.get("warnings") or [])
    hygiene_review_artifact_health = _verify_hygiene_review_artifact_health(profile, jobs, now_utc)
    errors.extend(f"hygiene_review: {error}" for error in hygiene_review_artifact_health.get("errors") or [])
    warnings.extend(f"hygiene_review: {warning}" for warning in hygiene_review_artifact_health.get("warnings") or [])
    submanager_contract_health = validate_torben_submanager_contracts()
    errors.extend(f"submanager_contracts: {error}" for error in submanager_contract_health.get("errors") or [])
    warnings.extend(
        f"submanager_contracts: {warning}" for warning in submanager_contract_health.get("warnings") or []
    )

    status = "pass" if not errors else "fail"
    return {
        "task": "torben_live_profile_verify",
        "wakeAgent": status != "pass",
        "generated_at": now_utc.isoformat().replace("+00:00", "Z"),
        "status": status,
        "profile_home": str(profile),
        "jobs_path": str(jobs_path),
        "repo_snapshot_home": str(snapshot) if snapshot else None,
        "enabled_jobs_checked": sum(1 for job in jobs if bool(job.get("enabled", True))),
        "script_checks": [check.to_dict() for check in checks],
        "gmail_realtime_health": gmail_realtime_health,
        "finance_cron_snapshot": finance_cron_snapshot,
        "backend_artifact_health": backend_artifact_health,
        "hygiene_review_artifact_health": hygiene_review_artifact_health,
        "submanager_contract_health": submanager_contract_health,
        "errors": errors,
        "warnings": warnings,
    }


def render_verification_failure(payload: dict[str, Any]) -> str:
    errors = list(payload.get("errors") or [])
    warnings = list(payload.get("warnings") or [])
    lines = [
        "Torben live-profile verification failed.",
        "",
        "Why it matters: enabled cron jobs may be blind or noisy until live profile drift is fixed.",
    ]
    if errors:
        lines.extend(["", "Errors:"])
        lines.extend(f"- {error}" for error in errors[:20])
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings[:10])
    return "\n".join(lines).strip() + "\n"
