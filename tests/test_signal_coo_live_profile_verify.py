from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hermes_cli.signal_coo.live_profile_verify import (
    REQUIRED_FINANCE_CRON_SNAPSHOT_JOBS,
    clear_live_profile_investigation_request,
    consume_live_profile_investigation_request,
    live_profile_failure_fingerprint,
    render_verification_failure,
    stage_live_profile_investigation_request,
    update_live_profile_alert_state,
    verify_torben_live_profile,
)


def _write_jobs(profile: Path, jobs: list[dict]) -> None:
    jobs_path = profile / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(json.dumps({"jobs": jobs}, indent=2) + "\n", encoding="utf-8")


def _write_jobs_snapshot(profile: Path, jobs: list[dict]) -> None:
    jobs_path = profile / "cron" / "jobs.snapshot.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(json.dumps({"jobs": jobs}, indent=2) + "\n", encoding="utf-8")


def _write_script(root: Path, name: str, body: str = "print('ok')\n") -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / name).write_text(body, encoding="utf-8")


def _write_gmail_health_state(profile: Path, *, expiration_at: str, pull_generated_at: str) -> None:
    state = profile / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "torben-gmail-watch-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "last_watch_registration_status": "pass",
                "accounts": {
                    "personal": {
                        "alias": "personal",
                        "email": "eric@example.com",
                        "history_id": "123",
                        "watch_expiration_at": expiration_at,
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (state / "torben-gmail-pubsub-pull-latest.json").write_text(
        json.dumps(
            {
                "task": "torben_gmail_pubsub_pull",
                "wakeAgent": False,
                "generated_at": pull_generated_at,
                "reason": "no pubsub notifications",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_backend_artifact(profile: Path, name: str, payload: dict) -> None:
    state = profile / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _loop_readiness_ledger(**overrides: object) -> dict:
    ledger = {
        "task": "equity_loop_readiness_ledger",
        "status": "blocked",
        "ledger_status": "pass",
        "implementation_status": "stage_only_production_ready_live_blocked",
        "current_state": {
            "safe_operator_action": "wait_for_oos_or_market_data",
            "stop_condition": {
                "status": "wait_for_paper_evidence",
                "primary_next_action": "wait_for_oos_or_market_data",
                "max_new_samples": 0,
                "max_iterations": 0,
                "live_order_authority": "none",
            },
            "paper_evidence_runway": {
                "status": "wait_for_paper_evidence",
                "safe_operator_action": "wait_for_oos_or_market_data",
                "max_new_samples": 0,
                "max_iterations": 0,
                "commands_live_disabled": True,
                "live_order_authority": "none",
            },
            "go_live": {
                "status": "blocked",
                "ready_to_submit": False,
                "go_live_blocked": True,
                "blocker_count": 7,
            },
            "halt_and_circuit_breaker": {
                "status": "blocked",
                "trading_halt_active": True,
                "circuit_breaker_active": True,
                "live_order_authority": "none",
            },
            "live_promotion_controls": {
                "operator_approval": {
                    "status": "missing_or_invalid",
                    "required_scope": "one_shot_live_canary",
                    "live_order_authority": "none",
                },
                "live_flags": {
                    "status": "disabled_until_final_gate",
                    "enabled_now": False,
                    "one_shot_live_submit_available": False,
                    "live_order_authority": "none",
                },
            },
            "optimizer_evidence": {
                "status": "blocked",
                "optimizer_status": "collecting_data",
                "calibration_repair_plan": {
                    "status": "awaiting_paper_evidence",
                    "target_new_samples": 0,
                    "repair_samples_remaining": 0,
                    "live_order_authority": "none",
                },
                "paper_feedback_only": True,
                "sample_budget_open": False,
                "live_order_authority": "none",
            },
            "paper_verifier_gates": {
                "status": "blocked",
                "performance_status": "insufficient",
                "calibration_status": "insufficient",
                "sample_count": 145,
                "calibrated_sample_count": 145,
                "blocked_gate_ids": [
                    "brier_score",
                    "newey_west_tstat_proxy",
                    "oos_months",
                    "sharpe_ratio",
                ],
                "gate_statuses": {
                    "sample_count": "pass",
                    "sharpe_ratio": "blocked",
                    "max_drawdown": "pass",
                    "newey_west_tstat_proxy": "blocked",
                    "oos_months": "blocked",
                    "max_symbol_concentration": "pass",
                    "brier_score": "blocked",
                },
                "live_order_authority": "none",
            },
        },
        "blocking_gaps": [
            {
                "id": "paper_performance",
                "status": "blocking_live_go",
                "operator_action": "wait_for_oos_window_or_new_paper_outcomes",
                "release_condition": "performance.status == sufficient",
                "verification_artifacts": ["state/trading-loop/performance.json"],
                "blockers": ["paper_performance_gate_failed:sharpe_ratio"],
                "live_order_authority": "none",
            },
            {
                "id": "paper_calibration",
                "status": "blocking_live_go",
                "operator_action": "wait_for_calibration_evidence_or_explicit_repair_demand",
                "release_condition": "calibration.status == sufficient",
                "verification_artifacts": ["state/trading-loop/calibration.json"],
                "blockers": ["paper_calibration_gate_failed:brier_score"],
                "live_order_authority": "none",
            },
            {
                "id": "paper_evidence_runway",
                "status": "intentional_wait",
                "operator_action": "wait_for_oos_or_market_data",
                "release_condition": "new paper outcome, OOS window progress, or explicit optimizer repair demand",
                "verification_artifacts": ["state/trading-loop/evidence-wait-packet.json"],
                "blockers": ["paper_performance_gate_failed:sharpe_ratio"],
                "live_order_authority": "none",
            },
            {
                "id": "operator_approval",
                "status": "blocking_live_go",
                "operator_action": "prepare_exact_one_shot_live_canary_approval_after_all_non_approval_gates_pass",
                "release_condition": "approval.status == approved",
                "verification_artifacts": ["state/approvals/<signal_id>.json"],
                "blockers": ["missing_approval_artifact"],
                "live_order_authority": "none",
            },
        ],
        "paper_requirements": {
            "self_improvement": {
                "status": "pass",
                "lesson_count": 302,
                "paper_trade_retrospective_count": 12,
                "optimizer_lessons_used_count": 12,
                "policy_id": "paper_feedback_retrospective_candidate_policy_v1",
                "policy_live_order_authority": "none",
            }
        },
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }
    ledger.update(overrides)
    return ledger


def _write_hygiene_review_artifact(
    profile: Path,
    *,
    generated_at: str = "2026-06-29T14:23:48Z",
    recommendations: list[dict] | None = None,
    recommendation_count: int | None = None,
    messages_scanned: int = 1569,
    gmail_reads: int = 1974,
    gmail_writes: int = 0,
    external_mutations: int = 0,
    llm_review_status: str = "accepted",
) -> None:
    recommendations = recommendations if recommendations is not None else [{"handle": "EA-20260629-001"}]
    if recommendation_count is None:
        recommendation_count = len(recommendations)
    _write_backend_artifact(
        profile,
        "torben-email-hygiene-review-actions-latest.json",
        {
            "task": "torben_email_hygiene_weekly_review",
            "wakeAgent": bool(recommendations),
            "generated_at": generated_at,
            "mutation_boundary": "weekly review stages recommendations only",
            "recommendations": recommendations,
            "diagnostics": {
                "messages_scanned": messages_scanned,
                "recommendation_count": recommendation_count,
                "gmail_reads": gmail_reads,
                "gmail_writes": gmail_writes,
                "external_mutations": external_mutations,
                "llm_review": {"status": llm_review_status},
            },
        },
    )


def test_live_profile_verify_passes_enabled_scripts_and_snapshot_sync(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    snapshot = tmp_path / "snapshot"
    _write_jobs(
        profile,
        [
            {"name": "active", "enabled": True, "script": "active.py", "last_status": "ok"},
            {"name": "disabled", "enabled": False, "script": "missing-disabled.py", "last_status": "error"},
        ],
    )
    _write_script(profile, "active.py")
    _write_script(snapshot, "active.py")

    payload = verify_torben_live_profile(profile_home=profile, repo_snapshot_home=snapshot)

    assert payload["status"] == "pass"
    assert payload["wakeAgent"] is False
    assert payload["submanager_contract_health"]["status"] == "pass"
    assert payload["submanager_contract_health"]["contracts"]["finance"]["provider"] == "ratatosk_robinhood_v01"
    active = [item for item in payload["script_checks"] if item["name"] == "active"][0]
    assert active["exists"] is True
    assert active["compiles"] is True
    assert active["snapshot_in_sync"] is True


def test_live_profile_verify_fails_missing_enabled_script(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(profile, [{"name": "missing", "enabled": True, "script": "missing.py"}])

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert payload["wakeAgent"] is True
    assert "missing: enabled cron script missing" in payload["errors"][0]


def test_live_profile_verify_fails_compile_error(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(profile, [{"name": "bad", "enabled": True, "script": "bad.py"}])
    _write_script(profile, "bad.py", "def nope(:\n")

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("script does not compile" in error for error in payload["errors"])


def test_live_profile_verify_passes_full_finance_cron_snapshot_parity(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    schedules = {
        "torben-finance-radar": "35 9,12,15 * * 1-5",
        "torben-finance-loop-heartbeat": "5,35 9-16 * * 1-5",
        "torben-finance-next-wake-runner": "15,45 9-16 * * 1-5",
        "torben-finance-next-wake-offhours-recheck": "5 19,20 * * *",
        "torben-finance-go-live-packet": "17,47 9-16 * * 1-5",
        "torben-finance-repair-window-simulator": "20,50 9-16 * * 1-5",
        "torben-finance-market-open-sample-acquisition": "31,46 9 * * 1-5",
        "torben-finance-sample-collector": "8,38 9-16 * * 1-5",
        "torben-finance-experiment-programs": "25,55 9-16 * * 1-5",
        "torben-finance-risk-monitor": "10,40 9-16 * * 1-5",
    }
    jobs = [
        {
            "name": name,
            "enabled": True,
            "script": script,
            "schedule_display": schedules[name],
            "no_agent": True,
            "last_status": "ok",
        }
        for name, script in sorted(REQUIRED_FINANCE_CRON_SNAPSHOT_JOBS.items())
    ]
    _write_jobs(profile, jobs)
    _write_jobs_snapshot(profile, jobs)
    for job in jobs:
        _write_script(profile, job["script"])

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    assert payload["finance_cron_snapshot"]["status"] == "pass"
    assert payload["finance_cron_snapshot"]["required_job_count"] == len(REQUIRED_FINANCE_CRON_SNAPSHOT_JOBS)


def test_live_profile_verify_fails_full_finance_cron_snapshot_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    schedules = {
        "torben-finance-radar": "35 9,12,15 * * 1-5",
        "torben-finance-loop-heartbeat": "5,35 9-16 * * 1-5",
        "torben-finance-next-wake-runner": "15,45 9-16 * * 1-5",
        "torben-finance-next-wake-offhours-recheck": "5 19,20 * * *",
        "torben-finance-go-live-packet": "17,47 9-16 * * 1-5",
        "torben-finance-repair-window-simulator": "20,50 9-16 * * 1-5",
        "torben-finance-market-open-sample-acquisition": "31,46 9 * * 1-5",
        "torben-finance-sample-collector": "8,38 9-16 * * 1-5",
        "torben-finance-experiment-programs": "25,55 9-16 * * 1-5",
        "torben-finance-risk-monitor": "10,40 9-16 * * 1-5",
    }
    jobs = [
        {
            "name": name,
            "enabled": True,
            "script": script,
            "schedule_display": schedules[name],
            "no_agent": True,
            "last_status": "ok",
        }
        for name, script in sorted(REQUIRED_FINANCE_CRON_SNAPSHOT_JOBS.items())
    ]
    _write_jobs(profile, jobs)
    _write_jobs_snapshot(profile, [jobs[0]])
    for job in jobs:
        _write_script(profile, job["script"])

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert payload["finance_cron_snapshot"]["status"] == "fail"
    assert any("finance cron snapshot missing enabled job" in error for error in payload["errors"])


def test_live_profile_verify_fails_stale_cron_errors(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "errored",
                "enabled": True,
                "script": "ok.py",
                "last_status": "ok",
                "last_error": "script missing",
                "last_delivery_error": "delivery failed",
            }
        ],
    )
    _write_script(profile, "ok.py")

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("last_error is set" in error for error in payload["errors"])
    assert any("last_delivery_error is set" in error for error in payload["errors"])


def test_live_profile_verify_fails_backend_error_artifact(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(profile, [{"name": "torben-gtm-radar", "enabled": True, "script": "torben_gtm_radar.py"}])
    _write_script(profile, "torben_gtm_radar.py")
    _write_backend_artifact(
        profile,
        "torben-gtm-radar-latest.json",
        {
            "task": "torben_gtm_radar_adapter",
            "wakeAgent": True,
            "error": {
                "type": "RuntimeError",
                "message": "Magnus GTM radar refresh failed",
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("backend_artifacts: torben_gtm_radar.py: latest artifact has error" in error for error in payload["errors"])
    assert payload["backend_artifact_health"]["artifacts"][0]["status"] == "fail"


def test_live_profile_verify_fails_backend_forbidden_mutation_count(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(profile, [{"name": "torben-finance-radar", "enabled": True, "script": "torben_finance_radar.py"}])
    _write_script(profile, "torben_finance_radar.py")
    _write_backend_artifact(
        profile,
        "torben-finance-radar-latest.json",
        {
            "task": "torben_finance_radar",
            "wakeAgent": True,
            "generated_at": "2026-06-26T12:00:00Z",
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 1,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("backend_artifacts: torben_finance_radar.py: broker_orders_submitted is nonzero: 1" in error for error in payload["errors"])


def test_live_profile_verify_fails_backend_order_submission_count(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(profile, [{"name": "torben-finance-radar", "enabled": True, "script": "torben_finance_radar.py"}])
    _write_script(profile, "torben_finance_radar.py")
    _write_backend_artifact(
        profile,
        "torben-finance-radar-latest.json",
        {
            "task": "torben_finance_radar",
            "wakeAgent": True,
            "generated_at": "2026-06-26T12:00:00Z",
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 1,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert payload["backend_artifact_health"]["artifacts"][0]["orders_submitted"] == 1
    assert any(
        "backend_artifacts: torben_finance_radar.py: orders_submitted is nonzero: 1" in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_backend_missing_required_mutation_counter(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(profile, [{"name": "torben-finance-radar", "enabled": True, "script": "torben_finance_radar.py"}])
    _write_script(profile, "torben_finance_radar.py")
    _write_backend_artifact(
        profile,
        "torben-finance-radar-latest.json",
        {
            "task": "torben_finance_radar",
            "wakeAgent": False,
            "generated_at": "2026-06-26T12:00:00Z",
            "public_actions_taken": 0,
            "external_mutations": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert payload["backend_artifact_health"]["artifacts"][0]["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_radar.py: latest artifact missing mutation counter: orders_submitted"
        in error
        for error in payload["errors"]
    )



def _live_disabled_source_refresh(root: Path) -> dict:
    return {
        "status": "success",
        "root": str(root),
        "command": [
            "uv",
            "run",
            "python",
            "scripts/equity_paper_sample_collector.py",
            "--json",
            "--max-candidates",
            "3",
            "--max-outcomes",
            "3",
        ],
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }


def _sample_collector_backend_payload(
    *,
    task: str = "torben_finance_sample_collector",
    generated_at: str = "2026-07-01T11:12:09Z",
    status: str = "idle",
    budget_date: str = "2026-07-01",
    source_refresh: dict | None = None,
) -> dict:
    payload = {
        "task": task,
        "wakeAgent": False,
        "generated_at": generated_at,
        "status": status,
        "sample_budget": {
            "policy_id": "daily_bounded_paper_sample_budget_v1",
            "budget_date": budget_date,
            "daily_sample_cap": 6,
            "observed_sample_count_today": 6,
            "requested_new_samples_this_window": 3,
            "approved_new_samples_this_window": 0,
            "remaining_samples_today": 0,
            "budget_exhausted": True,
            "live_order_authority": "none",
        },
        "sample_budget_guard": {
            "policy_id": "daily_bounded_paper_sample_budget_v1",
            "status": "closed",
            "requested_new_samples": 3,
            "approved_new_samples_this_window": 0,
            "remaining_samples_today": 0,
            "budget_exhausted": True,
            "live_order_authority": "none",
        },
        "signal_optimizer": {
            "calibration_repair_plan": {
                "policy_id": "paper_feedback_calibration_repair_plan_v1",
                "status": "needs_repair_samples",
                "target_new_samples": 3,
                "repair_samples_remaining": 3,
                "preferred_existing_symbols": ["BA"],
                "live_order_authority": "none",
            },
            "historical_policy_coverage": {
                "status": "covered",
                "live_order_authority": "none",
            },
        },
        "canaries_created_count": 0,
        "canaries_reconciled_count": 0,
        "outcomes_observed": 0,
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }
    if source_refresh is not None:
        payload["source_refresh"] = source_refresh
    return payload


def _write_sample_collector_source(root: Path, payload: dict) -> None:
    path = root / "state" / "trading-loop" / "sample-collector.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_sample_collector_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-sample-collector",
                "enabled": True,
                "script": "torben_finance_sample_collector.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:12:00+00:00",
                "next_run_at": "2026-07-01T11:38:00+00:00",
                "schedule_display": "8,38 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_sample_collector.py")
    profile_payload = payload | {"source_refresh": _live_disabled_source_refresh(ratatosk_root)}
    _write_backend_artifact(profile, "torben-finance-sample-collector-latest.json", profile_payload)


def test_live_profile_verify_passes_sample_collector_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _sample_collector_backend_payload()
    source_payload = _sample_collector_backend_payload(task="equity_paper_sample_collector")
    _write_sample_collector_profile(profile, ratatosk_root, profile_payload)
    _write_sample_collector_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_sample_collector.py"]["sample_collector_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_sample_budget.budget_date"] == "2026-07-01"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_sample_collector_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _sample_collector_backend_payload(
        generated_at="2026-07-01T11:12:09Z",
        budget_date="2026-07-01",
    )
    source_payload = _sample_collector_backend_payload(
        task="equity_paper_sample_collector",
        generated_at="2026-07-02T11:12:09Z",
        budget_date="2026-07-02",
    )
    _write_sample_collector_profile(profile, ratatosk_root, profile_payload)
    _write_sample_collector_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source sample collector generated_at differs" in error for error in payload["errors"])
    assert any("source sample collector sample_budget.budget_date differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_sample_collector.py"]["sample_collector_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "fail"
    assert alignment["mismatches"] == ["generated_at", "sample_budget.budget_date"]



def _experiment_programs_source_refresh(root: Path) -> dict:
    return {
        "status": "success",
        "root": str(root),
        "command": ["uv", "run", "python", "scripts/equity_experiment_programs.py", "--json"],
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }


def _experiment_programs_backend_payload(
    *,
    task: str = "torben_finance_experiment_programs",
    generated_at: str = "2026-07-01T11:25:04Z",
    repair_preferred_symbols: list[str] | None = None,
) -> dict:
    repair_preferred_symbols = repair_preferred_symbols or ["BA"]
    loops = {
        "execution-tactics": {
            "experiment_id": "equity-execution-repair-priority-v1",
            "status": "active",
            "manual_approval_required": False,
            "live_order_authority": "none",
        },
        "regime-detection": {
            "experiment_id": "equity-regime-momentum-filter-v1",
            "status": "active",
            "manual_approval_required": False,
            "live_order_authority": "none",
        },
        "risk-thresholds": {
            "experiment_id": "equity-risk-thresholds-paper-v1",
            "status": "active",
            "manual_approval_required": True,
            "live_order_authority": "none",
        },
    }
    return {
        "task": task,
        "adapter_task": "equity_experiment_programs",
        "wakeAgent": False,
        "generated_at": generated_at,
        "source_refresh_safe": True,
        "experiment_programs_contract_safe": True,
        "status": "programs_prepared",
        "optimization_mode": "paper_feedback_only",
        "state_root": "/Users/ericfreeman/ratatosk/state",
        "read_only_broker": True,
        "evidence": {
            "sample_count": 217,
            "calibrated_sample_count": 217,
            "repair_plan_status": "needs_repair_samples",
            "repair_target_new_samples": 3,
            "repair_preferred_symbols": repair_preferred_symbols,
            "historical_policy_coverage_status": "covered",
            "live_order_authority": "none",
        },
        "loops": loops,
        "active_loop_count": len(loops),
        "active_loop_ids": [loop["experiment_id"] for loop in loops.values()],
        "broker_review_attempted": False,
        "broker_place_attempted": False,
        "live_order_authority": "none",
        "mutation_counters": {
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _experiment_programs_source_payload(profile_payload: dict) -> dict:
    source = dict(profile_payload)
    source["task"] = "equity_experiment_programs"
    source.pop("adapter_task", None)
    source.pop("wakeAgent", None)
    source.pop("source_refresh_safe", None)
    source.pop("experiment_programs_contract_safe", None)
    source.pop("active_loop_count", None)
    source.pop("active_loop_ids", None)
    source.pop("mutation_counters", None)
    return source


def _write_experiment_programs_source(root: Path, payload: dict) -> None:
    path = root / "state" / "trading-loop" / "experiment-programs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_experiment_programs_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-experiment-programs",
                "enabled": True,
                "script": "torben_finance_experiment_programs.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:25:00+00:00",
                "next_run_at": "2026-07-01T11:55:00+00:00",
                "schedule_display": "25,55 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_experiment_programs.py")
    profile_payload = payload | {"source_refresh": _experiment_programs_source_refresh(ratatosk_root)}
    _write_backend_artifact(profile, "torben-finance-experiment-programs-latest.json", profile_payload)


def test_live_profile_verify_passes_experiment_programs_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _experiment_programs_backend_payload()
    source_payload = _experiment_programs_source_payload(profile_payload)
    _write_experiment_programs_profile(profile, ratatosk_root, profile_payload)
    _write_experiment_programs_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_experiment_programs.py"]["experiment_programs_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_generated_at"] == "2026-07-01T11:25:04Z"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_experiment_programs_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _experiment_programs_backend_payload(
        generated_at="2026-07-01T11:25:04Z",
        repair_preferred_symbols=["BA"],
    )
    source_profile_shape = _experiment_programs_backend_payload(
        generated_at="2026-07-02T11:25:04Z",
        repair_preferred_symbols=["MSFT"],
    )
    source_payload = _experiment_programs_source_payload(source_profile_shape)
    _write_experiment_programs_profile(profile, ratatosk_root, profile_payload)
    _write_experiment_programs_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source experiment-programs generated_at differs" in error for error in payload["errors"])
    assert any("source experiment-programs evidence differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_experiment_programs.py"]["experiment_programs_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "fail"
    assert alignment["mismatches"] == ["generated_at", "evidence"]

def _repair_window_source_refresh(root: Path) -> dict:
    return {
        "status": "success",
        "root": str(root),
        "command": [
            "uv",
            "run",
            "python",
            "scripts/equity_repair_window_simulator.py",
            "--json",
        ],
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }


def _repair_window_backend_payload(
    *,
    task: str = "torben_finance_repair_window_simulator",
    generated_at: str = "2026-07-01T11:50:04Z",
    simulation_state_root: str = "/tmp/ratatosk-repair-window-sim-test",
) -> dict:
    return {
        "task": task,
        "adapter_task": "equity_repair_window_simulation",
        "wakeAgent": False,
        "generated_at": generated_at,
        "source_refresh_safe": True,
        "simulation_contract_safe": True,
        "status": "pass",
        "reason": "simulation_passed",
        "repair_plan_source": "runtime_optimizer_before_simulation",
        "repair_plan": {
            "status": "needs_repair_samples",
            "target_new_samples": 3,
            "repair_samples_remaining": 3,
            "preferred_existing_symbols": ["BA"],
            "live_order_authority": "none",
        },
        "source_state_root": "/Users/ericfreeman/ratatosk/state",
        "simulation_state_root": simulation_state_root,
        "requested_samples": 3,
        "preferred_symbols": ["BA"],
        "candidate_symbols": ["BA", "BA", "BA"],
        "checks": {
            "active_repair_plan": True,
            "isolated_state_root": True,
            "source_state_sample_artifacts_unchanged": True,
            "tick_completed": True,
            "research_batch_succeeded": True,
            "research_selected_requested_samples": True,
            "sample_collector_collected": True,
            "sample_budget_open": True,
            "created_requested_canaries": True,
            "observed_requested_outcomes": True,
            "created_symbols_from_repair_plan": True,
            "live_order_authority_none": True,
            "zero_mutation_counters": True,
            "broker_review_not_attempted": True,
            "broker_place_not_attempted": True,
        },
        "broker_review_attempted": False,
        "broker_place_attempted": False,
        "live_order_authority": "none",
        "mutation_counters": {
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _write_repair_window_source(root: Path, payload: dict) -> None:
    path = root / "state" / "trading-loop" / "repair-window-simulation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_repair_window_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-repair-window-simulator",
                "enabled": True,
                "script": "torben_finance_repair_window_simulator.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:50:00+00:00",
                "next_run_at": "2026-07-01T12:20:00+00:00",
                "schedule_display": "20,50 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_repair_window_simulator.py")
    profile_payload = payload | {"source_refresh": _repair_window_source_refresh(ratatosk_root)}
    _write_backend_artifact(profile, "torben-finance-repair-window-simulator-latest.json", profile_payload)


def test_live_profile_verify_passes_repair_window_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _repair_window_backend_payload()
    source_payload = _repair_window_backend_payload(task="equity_repair_window_simulation")
    _write_repair_window_profile(profile, ratatosk_root, profile_payload)
    _write_repair_window_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_repair_window_simulator.py"]["repair_window_simulation_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_generated_at"] == "2026-07-01T11:50:04Z"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_repair_window_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _repair_window_backend_payload(
        generated_at="2026-07-01T11:50:04Z",
        simulation_state_root="/tmp/ratatosk-repair-window-profile",
    )
    source_payload = _repair_window_backend_payload(
        task="equity_repair_window_simulation",
        generated_at="2026-07-02T11:50:04Z",
        simulation_state_root="/tmp/ratatosk-repair-window-source",
    )
    _write_repair_window_profile(profile, ratatosk_root, profile_payload)
    _write_repair_window_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source repair-window simulation generated_at differs" in error for error in payload["errors"])
    assert any("source repair-window simulation simulation_state_root differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_repair_window_simulator.py"]["repair_window_simulation_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "fail"
    assert alignment["mismatches"] == ["generated_at", "simulation_state_root"]


def _next_wake_runner_source_refresh(root: Path) -> dict:
    return {
        "status": "success",
        "root": str(root),
        "command": [
            "uv",
            "run",
            "python",
            "scripts/equity_next_wake_runner.py",
            "--json",
            "--execute",
        ],
        "returncode": 0,
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }


def _next_wake_runner_backend_payload(
    *,
    task: str = "torben_finance_next_wake_runner",
    generated_at: str = "2026-07-01T11:45:04Z",
    status: str = "not_due",
    due: bool = False,
    ready_now: bool = False,
    required_operator_action: str = "continue_wait",
    safe_command_ids: list[str] | None = None,
    wake_reason_ids: list[str] | None = None,
    execute_requested: bool = True,
    execution_attempted: bool = False,
    command_results: list[dict] | None = None,
) -> dict:
    counters = {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }
    return {
        "task": task,
        "adapter_task": "equity_next_wake_runner",
        "wakeAgent": False,
        "generated_at": generated_at,
        "source_refresh_safe": True,
        "runner_contract_safe": True,
        "status": status,
        "due": due,
        "ready_now": ready_now,
        "execute_requested": execute_requested,
        "execution_attempted": execution_attempted,
        "next_recheck_after_utc": "2026-07-05T00:00:00Z",
        "bounded_collection_not_before_utc": "2026-07-06T13:30:00Z",
        "budget_reopens_after_utc": "2026-07-05T00:00:00Z",
        "market_scan_recheck_after_utc": "2026-07-06T13:30:00Z",
        "required_operator_action": required_operator_action,
        "wake_reason_ids": wake_reason_ids
        or [
            "daily_paper_sample_budget_exhausted",
            "market_closed_scan_supply",
            "release_signal_absent",
        ],
        "safe_command_ids": safe_command_ids
        or [
            "recheck_evidence_wait_packet",
            "recheck_readiness_ledger",
            "recheck_research_candidate_supply",
            "recheck_stop_condition",
        ],
        "command_results": command_results or [],
        "commands_live_disabled": True,
        "broker_submit_allowed": False,
        "human_live_review_allowed": False,
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
    }


def _next_wake_runner_source_payload(profile_payload: dict) -> dict:
    source = json.loads(json.dumps(profile_payload))
    source["task"] = "equity_next_wake_runner"
    source.pop("adapter_task", None)
    source.pop("wakeAgent", None)
    source.pop("source_refresh_safe", None)
    source.pop("runner_contract_safe", None)
    source.pop("source_refresh", None)
    return source


def _write_next_wake_runner_source(root: Path, payload: dict) -> None:
    path = root / "state" / "trading-loop" / "next-wake-runner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_next_wake_runner_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-next-wake-runner",
                "enabled": True,
                "script": "torben_finance_next_wake_runner.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:45:00+00:00",
                "next_run_at": "2026-07-01T12:15:00+00:00",
                "schedule_display": "15,45 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_next_wake_runner.py")
    profile_payload = payload | {"source_refresh": _next_wake_runner_source_refresh(ratatosk_root)}
    _write_backend_artifact(profile, "torben-finance-next-wake-runner-latest.json", profile_payload)


def test_live_profile_verify_passes_next_wake_runner_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _next_wake_runner_backend_payload()
    source_payload = _next_wake_runner_source_payload(profile_payload)
    _write_next_wake_runner_profile(profile, ratatosk_root, profile_payload)
    _write_next_wake_runner_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_next_wake_runner.py"]["next_wake_runner_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_generated_at"] == "2026-07-01T11:45:04Z"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_next_wake_runner_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _next_wake_runner_backend_payload(
        generated_at="2026-07-01T11:45:04Z",
        required_operator_action="continue_wait",
    )
    source_shape = _next_wake_runner_backend_payload(
        generated_at="2026-07-02T11:45:04Z",
        required_operator_action="collect_bounded_paper_samples",
    )
    source_payload = _next_wake_runner_source_payload(source_shape)
    _write_next_wake_runner_profile(profile, ratatosk_root, profile_payload)
    _write_next_wake_runner_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source next-wake runner generated_at differs" in error for error in payload["errors"])
    assert any("source next-wake runner required_operator_action differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_next_wake_runner.py"]["next_wake_runner_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "fail"
    assert alignment["mismatches"] == ["generated_at", "required_operator_action"]


def test_live_profile_verify_allows_next_wake_offhours_hold_source_overlay(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    source_shape = _next_wake_runner_backend_payload(
        status="ready",
        due=True,
        ready_now=True,
        required_operator_action="collect_bounded_paper_samples",
        safe_command_ids=["bounded_paper_sample_collection", "recheck_stop_condition"],
        execute_requested=False,
        execution_attempted=False,
    )
    source_payload = _next_wake_runner_source_payload(source_shape)
    profile_payload = source_payload | {
        "task": "torben_finance_next_wake_runner",
        "adapter_task": "equity_next_wake_runner",
        "wakeAgent": False,
        "source_refresh_safe": True,
        "runner_contract_safe": True,
        "status": "held_bounded_collection_offhours",
        "errors": [],
        "execute_requested": False,
        "execution_attempted": False,
        "command_results": [],
        "offhours_recheck_mode": True,
        "offhours_bounded_collection_blocked": True,
        "execution_block_reason": "bounded_paper_sample_collection_disabled_for_offhours_recheck",
    }
    _write_next_wake_runner_profile(profile, ratatosk_root, profile_payload)
    _write_next_wake_runner_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_next_wake_runner.py"]["next_wake_runner_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "pass"
    assert alignment["offhours_bounded_collection_overlay"] is True
    assert alignment["source_bounded_collection_requested"] is True
    assert alignment["mismatches"] == []

def test_live_profile_verify_checks_finance_loop_backend_artifacts(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    jobs = [
        {
            "name": "torben-finance-radar",
            "enabled": True,
            "script": "torben_finance_radar.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:30:00+00:00",
            "next_run_at": "2026-07-01T09:35:00-04:00",
            "schedule_display": "35 9-16 * * 1-5",
        },
        {
            "name": "torben-finance-loop-heartbeat",
            "enabled": True,
            "script": "torben_finance_loop_heartbeat.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:29:20+00:00",
            "next_run_at": "2026-07-01T09:05:00-04:00",
            "schedule_display": "5,35 9-16 * * 1-5",
        },
        {
            "name": "torben-finance-sample-collector",
            "enabled": True,
            "script": "torben_finance_sample_collector.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:12:00+00:00",
            "next_run_at": "2026-07-01T09:08:00-04:00",
            "schedule_display": "8,38 9-16 * * 1-5",
        },
        {
            "name": "torben-finance-experiment-programs",
            "enabled": True,
            "script": "torben_finance_experiment_programs.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:25:00+00:00",
            "next_run_at": "2026-07-01T09:25:00-04:00",
            "schedule_display": "25,55 9-16 * * 1-5",
        },
        {
            "name": "torben-finance-risk-monitor",
            "enabled": True,
            "script": "torben_finance_risk_monitor.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:38:00+00:00",
            "next_run_at": "2026-07-01T09:10:00-04:00",
            "schedule_display": "10,40 9-16 * * 1-5",
        },
        {
            "name": "torben-finance-next-wake-runner",
            "enabled": True,
            "script": "torben_finance_next_wake_runner.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:45:00+00:00",
            "next_run_at": "2026-07-01T10:15:00-04:00",
            "schedule_display": "15,45 9-16 * * 1-5",
        },
        {
            "name": "torben-finance-go-live-packet",
            "enabled": True,
            "script": "torben_finance_go_live_packet.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:47:00+00:00",
            "next_run_at": "2026-07-01T10:17:00-04:00",
            "schedule_display": "17,47 9-16 * * 1-5",
        },
        {
            "name": "torben-finance-repair-window-simulator",
            "enabled": True,
            "script": "torben_finance_repair_window_simulator.py",
            "last_status": "ok",
            "last_run_at": "2026-07-01T07:50:00+00:00",
            "next_run_at": "2026-07-01T10:20:00-04:00",
            "schedule_display": "20,50 9-16 * * 1-5",
        },
    ]
    _write_jobs(profile, jobs)
    for job in jobs:
        _write_script(profile, job["script"])

    source_refresh = {
        "status": "success",
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }
    stop_condition = {
        "status": "wait_for_market_open_scan_supply",
        "primary_next_action": "wait_for_market_open_scan_supply",
        "release_conditions": ["scan_candidate_supply.market_open == true"],
    }
    _write_backend_artifact(
        profile,
        "torben-finance-radar-latest.json",
        {
            "task": "torben_finance_radar",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:30:27Z",
            "source_refresh": source_refresh,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-loop-heartbeat-latest.json",
        {
            "task": "torben_finance_loop_heartbeat",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:29:27Z",
            "source_refresh": source_refresh,
            "stop_condition": stop_condition,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-sample-collector-latest.json",
        {
            "task": "torben_finance_sample_collector",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:12:09Z",
            "source_refresh": source_refresh,
            "status": "idle",
            "sample_budget": {
                "policy_id": "daily_bounded_paper_sample_budget_v1",
                "budget_date": "2026-07-01",
                "daily_sample_cap": 6,
                "observed_sample_count_today": 6,
                "requested_new_samples_this_window": 3,
                "approved_new_samples_this_window": 0,
                "remaining_samples_today": 0,
                "budget_exhausted": True,
                "live_order_authority": "none",
            },
            "sample_budget_guard": {
                "policy_id": "daily_bounded_paper_sample_budget_v1",
                "status": "closed",
                "requested_new_samples": 3,
                "approved_new_samples_this_window": 0,
                "remaining_samples_today": 0,
                "budget_exhausted": True,
                "live_order_authority": "none",
            },
            "signal_optimizer": {
                "calibration_repair_plan": {
                    "policy_id": "paper_feedback_calibration_repair_plan_v1",
                    "status": "needs_repair_samples",
                    "target_new_samples": 3,
                    "repair_samples_remaining": 3,
                    "preferred_existing_symbols": ["BA"],
                    "live_order_authority": "none",
                },
                "historical_policy_coverage": {
                    "status": "covered",
                    "live_order_authority": "none",
                },
            },
            "canaries_created_count": 0,
            "canaries_reconciled_count": 0,
            "outcomes_observed": 0,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-experiment-programs-latest.json",
        {
            "task": "torben_finance_experiment_programs",
            "adapter_task": "equity_experiment_programs",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:25:04Z",
            "source_refresh": source_refresh,
            "source_refresh_safe": True,
            "experiment_programs_contract_safe": True,
            "status": "programs_prepared",
            "optimization_mode": "paper_feedback_only",
            "read_only_broker": True,
            "evidence": {
                "sample_count": 87,
                "calibrated_sample_count": 87,
                "repair_plan_status": "needs_repair_samples",
                "repair_target_new_samples": 3,
                "repair_preferred_symbols": ["BA"],
                "historical_policy_coverage_status": "covered",
                "live_order_authority": "none",
            },
            "loops": {
                "risk-thresholds": {
                    "experiment_id": "equity-risk-thresholds-paper-v1",
                    "status": "active",
                    "manual_approval_required": True,
                    "live_order_authority": "none",
                },
                "execution-tactics": {
                    "experiment_id": "equity-execution-repair-priority-v1",
                    "status": "active",
                    "manual_approval_required": False,
                    "live_order_authority": "none",
                },
            },
            "active_loop_count": 2,
            "active_loop_ids": [
                "equity-risk-thresholds-paper-v1",
                "equity-execution-repair-priority-v1",
            ],
            "broker_review_attempted": False,
            "broker_place_attempted": False,
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-risk-monitor-latest.json",
        {
            "task": "torben_finance_risk_monitor",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:38:04Z",
            "source_refresh": source_refresh,
            "stop_condition": stop_condition,
            "loop_readiness_ledger": _loop_readiness_ledger(),
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-next-wake-runner-latest.json",
        {
            "task": "torben_finance_next_wake_runner",
            "adapter_task": "equity_next_wake_runner",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:45:04Z",
            "source_refresh": source_refresh,
            "source_refresh_safe": True,
            "runner_contract_safe": True,
            "commands_live_disabled": True,
            "broker_submit_allowed": False,
            "human_live_review_allowed": False,
            "live_order_authority": "none",
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-go-live-packet-latest.json",
        {
            "task": "torben_finance_go_live_packet",
            "adapter_task": "equity_go_live_operator_packet",
            "schema_version": "equity_go_live_operator_packet_v1",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:47:04Z",
            "source_refresh": source_refresh,
            "source_refresh_safe": True,
            "go_live_packet_contract_safe": True,
            "status": "blocked",
            "ready_to_submit": False,
            "go_live_blocked": True,
            "read_only": True,
            "broker_review_attempted": False,
            "broker_place_attempted": False,
            "approval_created": False,
            "approval_modified": False,
            "halt_or_circuit_cleared": False,
            "live_flags_enabled": False,
            "operator_mandate": {
                "human_approval_required": True,
                "self_approval_allowed": False,
                "required_approval_scope": "one_shot_live_canary",
            },
            "command_gates": {
                "one_shot_live_submit": {
                    "available": False,
                    "reason": "go_live_operator_packet_blocked",
                    "blocked_by": ["missing_approval_artifact"],
                }
            },
            "commands": {"one_shot_live_submit": None},
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-repair-window-simulator-latest.json",
        {
            "task": "torben_finance_repair_window_simulator",
            "adapter_task": "equity_repair_window_simulation",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:50:04Z",
            "source_refresh": source_refresh,
            "source_refresh_safe": True,
            "simulation_contract_safe": True,
            "status": "pass",
            "reason": "simulation_passed",
            "repair_plan_source": "runtime_optimizer_before_simulation",
            "repair_plan": {
                "status": "needs_repair_samples",
                "target_new_samples": 3,
                "repair_samples_remaining": 3,
                "preferred_existing_symbols": ["BA"],
                "live_order_authority": "none",
            },
            "requested_samples": 3,
            "candidate_symbols": ["BA", "BA", "BA"],
            "simulation_state_root": "/tmp/ratatosk-repair-window-sim-test",
            "checks": {
                "active_repair_plan": True,
                "isolated_state_root": True,
                "source_state_sample_artifacts_unchanged": True,
                "tick_completed": True,
                "research_batch_succeeded": True,
                "research_selected_requested_samples": True,
                "sample_collector_collected": True,
                "sample_budget_open": True,
                "created_requested_canaries": True,
                "observed_requested_outcomes": True,
                "created_symbols_from_repair_plan": True,
                "live_order_authority_none": True,
                "zero_mutation_counters": True,
                "broker_review_not_attempted": True,
                "broker_place_not_attempted": True,
            },
            "broker_review_attempted": False,
            "broker_place_attempted": False,
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {
        item["script"]: item
        for item in payload["backend_artifact_health"]["artifacts"]
    }
    assert artifacts["torben_finance_loop_heartbeat.py"]["stop_condition_status"] == "wait_for_market_open_scan_supply"
    assert artifacts["torben_finance_radar.py"]["live_safety_env"]["RATATOSK_LIVE_TRADING"] == "0"
    assert (
        artifacts["torben_finance_loop_heartbeat.py"]["job_artifact_alignment"]["latest_successful_job_name"]
        == "torben-finance-loop-heartbeat"
    )
    assert artifacts["torben_finance_sample_collector.py"]["live_safety_env"]["RATATOSK_LIVE_TRADING"] == "0"
    assert artifacts["torben_finance_sample_collector.py"]["job_artifact_alignment"]["next_job_name"] == (
        "torben-finance-sample-collector"
    )
    sample_contract = artifacts["torben_finance_sample_collector.py"]["sample_collector_contract"]
    assert sample_contract["sample_budget_guard_status"] == "closed"
    assert sample_contract["budget_exhausted"] is True
    assert sample_contract["canaries_created_count"] == 0
    assert sample_contract["repair_target_new_samples"] == 3
    assert sample_contract["repair_preferred_existing_symbols"] == ["BA"]
    experiment_contract = artifacts["torben_finance_experiment_programs.py"][
        "experiment_programs_contract"
    ]
    assert artifacts["torben_finance_experiment_programs.py"]["source_refresh_safe"] is True
    assert artifacts["torben_finance_experiment_programs.py"]["experiment_programs_contract_safe"] is True
    assert experiment_contract["status"] == "programs_prepared"
    assert experiment_contract["repair_target_new_samples"] == 3
    assert experiment_contract["repair_preferred_symbols"] == ["BA"]
    assert experiment_contract["active_loop_count"] == 2
    assert experiment_contract["active_loop_ids"] == [
        "equity-risk-thresholds-paper-v1",
        "equity-execution-repair-priority-v1",
    ]
    assert artifacts["torben_finance_next_wake_runner.py"]["source_refresh_safe"] is True
    assert artifacts["torben_finance_next_wake_runner.py"]["runner_contract_safe"] is True
    assert artifacts["torben_finance_next_wake_runner.py"]["commands_live_disabled"] is True
    go_live_contract = artifacts["torben_finance_go_live_packet.py"]["go_live_packet_contract"]
    assert go_live_contract["status"] == "blocked"
    assert go_live_contract["ready_to_submit"] is False
    assert go_live_contract["go_live_blocked"] is True
    assert go_live_contract["operator_approval_scope"] == "one_shot_live_canary"
    assert go_live_contract["one_shot_live_submit_available"] is False
    assert artifacts["torben_finance_go_live_packet.py"]["source_refresh_safe"] is True
    assert artifacts["torben_finance_go_live_packet.py"]["go_live_packet_contract_safe"] is True
    repair_contract = artifacts["torben_finance_repair_window_simulator.py"][
        "repair_window_simulation_contract"
    ]
    assert repair_contract["status"] == "pass"
    assert repair_contract["requested_samples"] == 3
    assert repair_contract["candidate_symbols"] == ["BA", "BA", "BA"]
    assert repair_contract["checks"]["source_state_sample_artifacts_unchanged"] is True
    assert artifacts["torben_finance_repair_window_simulator.py"]["source_refresh_safe"] is True
    assert artifacts["torben_finance_repair_window_simulator.py"]["simulation_contract_safe"] is True
    assert artifacts["torben_finance_risk_monitor.py"]["primary_next_action"] == "wait_for_market_open_scan_supply"
    assert artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["ledger_status"] == "pass"
    assert artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["go_live_blocked"] is True
    assert (
        artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["safe_operator_action"]
        == "wait_for_oos_or_market_data"
    )
    assert artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["self_improvement_status"] == "pass"
    assert artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["paper_trade_retrospective_count"] == 12
    assert (
        artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["halt_and_circuit_breaker_status"]
        == "blocked"
    )
    assert (
        artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["operator_approval_status"]
        == "missing_or_invalid"
    )
    assert (
        artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["live_flags_status"]
        == "disabled_until_final_gate"
    )
    assert (
        artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["optimizer_evidence_status"]
        == "blocked"
    )
    assert (
        artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["optimizer_sample_budget_open"]
        is False
    )
    assert (
        artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["paper_verifier_status"]
        == "blocked"
    )
    assert (
        "sharpe_ratio"
        in artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["paper_blocked_gate_ids"]
    )
    gap_actions = {
        item["id"]: item
        for item in artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]["blocking_gap_actions"]
    }
    assert gap_actions["paper_evidence_runway"]["operator_action"] == "wait_for_oos_or_market_data"
    assert gap_actions["operator_approval"]["live_order_authority"] == "none"


def test_live_profile_verify_fails_finance_loop_artifact_older_than_successful_job_run(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-sample-collector",
                "enabled": True,
                "script": "torben_finance_sample_collector.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T09:08:00-04:00",
                "next_run_at": "2026-07-01T09:38:00-04:00",
                "schedule_display": "8,38 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_sample_collector.py")
    _write_backend_artifact(
        profile,
        "torben-finance-sample-collector-latest.json",
        {
            "task": "torben_finance_sample_collector",
            "wakeAgent": False,
            "generated_at": "2026-07-01T13:00:00Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    artifact = payload["backend_artifact_health"]["artifacts"][0]
    assert artifact["job_artifact_alignment"]["latest_successful_job_name"] == "torben-finance-sample-collector"
    assert any(
        "backend_artifacts: torben_finance_sample_collector.py: latest artifact generated_at "
        "2026-07-01T13:00:00Z is older than latest successful job run"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_finance_loop_artifact_when_live_safety_is_enabled(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-sample-collector", "enabled": True, "script": "torben_finance_sample_collector.py"}],
    )
    _write_script(profile, "torben_finance_sample_collector.py")
    _write_backend_artifact(
        profile,
        "torben-finance-sample-collector-latest.json",
        {
            "task": "torben_finance_sample_collector",
            "wakeAgent": True,
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "1",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_sample_collector.py: RATATOSK_LIVE_TRADING is not live-disabled"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_finance_loop_artifact_missing_equity_live_safety(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-sample-collector", "enabled": True, "script": "torben_finance_sample_collector.py"}],
    )
    _write_script(profile, "torben_finance_sample_collector.py")
    _write_backend_artifact(
        profile,
        "torben-finance-sample-collector-latest.json",
        {
            "task": "torben_finance_sample_collector",
            "wakeAgent": True,
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                },
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_sample_collector.py: ROBINHOOD_EQUITY_LIVE is not live-disabled"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_sample_collector_when_exhausted_budget_creates_canaries(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-sample-collector",
                "enabled": True,
                "script": "torben_finance_sample_collector.py",
            }
        ],
    )
    _write_script(profile, "torben_finance_sample_collector.py")
    _write_backend_artifact(
        profile,
        "torben-finance-sample-collector-latest.json",
        {
            "task": "torben_finance_sample_collector",
            "wakeAgent": True,
            "generated_at": "2026-07-01T13:12:09Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "status": "collected",
            "sample_budget": {
                "policy_id": "daily_bounded_paper_sample_budget_v1",
                "budget_date": "2026-07-01",
                "daily_sample_cap": 6,
                "observed_sample_count_today": 6,
                "requested_new_samples_this_window": 3,
                "approved_new_samples_this_window": 0,
                "remaining_samples_today": 0,
                "budget_exhausted": True,
                "live_order_authority": "none",
            },
            "sample_budget_guard": {
                "policy_id": "daily_bounded_paper_sample_budget_v1",
                "status": "closed",
                "requested_new_samples": 3,
                "approved_new_samples_this_window": 0,
                "remaining_samples_today": 0,
                "budget_exhausted": True,
                "live_order_authority": "none",
            },
            "signal_optimizer": {
                "calibration_repair_plan": {
                    "policy_id": "paper_feedback_calibration_repair_plan_v1",
                    "status": "needs_repair_samples",
                    "target_new_samples": 3,
                    "repair_samples_remaining": 3,
                    "preferred_existing_symbols": ["BA"],
                    "live_order_authority": "none",
                },
                "historical_policy_coverage": {
                    "status": "covered",
                    "live_order_authority": "none",
                },
            },
            "canaries_created_count": 1,
            "canaries_reconciled_count": 0,
            "outcomes_observed": 0,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_sample_collector.py: "
        "budget exhausted but canaries_created_count is nonzero: 1"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_sample_collector_without_budget_guard(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-sample-collector",
                "enabled": True,
                "script": "torben_finance_sample_collector.py",
            }
        ],
    )
    _write_script(profile, "torben_finance_sample_collector.py")
    _write_backend_artifact(
        profile,
        "torben-finance-sample-collector-latest.json",
        {
            "task": "torben_finance_sample_collector",
            "wakeAgent": False,
            "generated_at": "2026-07-01T13:12:09Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "status": "idle",
            "sample_budget": {
                "policy_id": "daily_bounded_paper_sample_budget_v1",
                "budget_date": "2026-07-01",
                "daily_sample_cap": 6,
                "observed_sample_count_today": 0,
                "requested_new_samples_this_window": 3,
                "approved_new_samples_this_window": 3,
                "remaining_samples_today": 3,
                "budget_exhausted": False,
                "live_order_authority": "none",
            },
            "signal_optimizer": {
                "calibration_repair_plan": {
                    "policy_id": "paper_feedback_calibration_repair_plan_v1",
                    "status": "needs_repair_samples",
                    "target_new_samples": 3,
                    "repair_samples_remaining": 3,
                    "preferred_existing_symbols": ["BA"],
                    "live_order_authority": "none",
                },
                "historical_policy_coverage": {
                    "status": "covered",
                    "live_order_authority": "none",
                },
            },
            "canaries_created_count": 0,
            "canaries_reconciled_count": 0,
            "outcomes_observed": 0,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_sample_collector.py: latest artifact missing sample_budget_guard"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_next_wake_runner_without_safe_contract(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-next-wake-runner",
                "enabled": True,
                "script": "torben_finance_next_wake_runner.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T09:45:00-04:00",
                "next_run_at": "2026-07-01T10:15:00-04:00",
                "schedule_display": "15,45 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_next_wake_runner.py")
    _write_backend_artifact(
        profile,
        "torben-finance-next-wake-runner-latest.json",
        {
            "task": "torben_finance_next_wake_runner",
            "wakeAgent": True,
            "generated_at": "2026-07-01T13:46:00Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "source_refresh_safe": True,
            "runner_contract_safe": False,
            "commands_live_disabled": False,
            "broker_submit_allowed": True,
            "human_live_review_allowed": False,
            "live_order_authority": "review_only",
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_next_wake_runner.py: runner_contract_safe is not true"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_next_wake_runner.py: commands_live_disabled is not true"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_next_wake_runner.py: broker_submit_allowed is not false"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_next_wake_runner.py: live_order_authority is not none: review_only"
        in error
        for error in payload["errors"]
    )



def _go_live_packet_source_refresh(root: Path) -> dict:
    return {
        "status": "success",
        "root": str(root),
        "command": [
            "uv",
            "run",
            "python",
            "scripts/equity_go_live_packet.py",
            "--latest-research-candidate",
            "--skip-mcp-live-probe",
            "--json",
        ],
        "returncode": 0,
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }


def _go_live_packet_backend_payload(
    *,
    task: str = "torben_finance_go_live_packet",
    generated_at: str = "2026-07-01T11:47:04Z",
    blockers: list[str] | None = None,
) -> dict:
    counters = {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }
    blockers = blockers or [
        "paper_performance",
        "paper_calibration",
        "operator_approval",
        "live_flags",
    ]
    return {
        "task": task,
        "adapter_task": "equity_go_live_operator_packet",
        "schema_version": "equity_go_live_operator_packet_v1",
        "wakeAgent": False,
        "generated_at": generated_at,
        "source_refresh_safe": True,
        "go_live_packet_contract_safe": True,
        "status": "blocked",
        "status_scope": "one_shot_live_canary",
        "ready_to_submit": False,
        "go_live_blocked": True,
        "resolved_signal_id": None,
        "requested_signal_id": None,
        "state_root": "/Users/ericfreeman/ratatosk/state",
        "artifact_path": "/Users/ericfreeman/ratatosk/state/trading-loop/go-live-operator-packet.json",
        "latest_research_candidate": None,
        "blockers": blockers,
        "evidence_gates": {
            "paper_performance": {"passed": False, "live_order_authority": "none"},
            "paper_calibration": {"passed": False, "live_order_authority": "none"},
            "operator_approval": {"passed": False, "live_order_authority": "none"},
        },
        "paper_performance": {"status": "blocked", "live_order_authority": "none"},
        "paper_calibration": {"status": "blocked", "live_order_authority": "none"},
        "paper_outcome": {"status": "pending", "live_order_authority": "none"},
        "paper_evidence_runway": {"status": "wait_for_oos_or_market_data", "live_order_authority": "none"},
        "risk_incident": {"status": "blocked", "live_order_authority": "none"},
        "live_status": {"status": "disabled_until_final_gate", "live_order_authority": "none"},
        "mcp_readiness": {"status": "blocked", "live_order_authority": "none"},
        "research": {"status": "not_selected", "live_order_authority": "none"},
        "operator_mandate": {
            "human_approval_required": True,
            "self_approval_allowed": False,
            "required_approval_scope": "one_shot_live_canary",
        },
        "approval": {
            "status": "missing_or_invalid",
            "approval_scope": None,
            "approved": False,
            "approved_by_present": False,
            "approved_at_present": False,
            "account_number_present": False,
            "risk_acknowledgement_complete": False,
            "live_order_authority": "none",
        },
        "command_gates": {
            "one_shot_live_submit": {
                "available": False,
                "reason": "go_live_operator_packet_blocked",
                "blocked_by": blockers,
            }
        },
        "commands": {"one_shot_live_submit": None},
        "next_actions": ["wait_for_oos_or_market_data"],
        "promotion": {"status": "blocked", "live_order_authority": "none"},
        "canary": {"status": "blocked", "live_order_authority": "none"},
        "read_only": True,
        "broker_review_attempted": False,
        "broker_place_attempted": False,
        "approval_created": False,
        "approval_modified": False,
        "halt_or_circuit_cleared": False,
        "live_flags_enabled": False,
        "local_artifact_written": True,
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
    }


def _go_live_packet_source_payload(profile_payload: dict) -> dict:
    source = json.loads(json.dumps(profile_payload))
    source["task"] = "equity_go_live_operator_packet"
    source.pop("adapter_task", None)
    source.pop("wakeAgent", None)
    source.pop("source_refresh_safe", None)
    source.pop("go_live_packet_contract_safe", None)
    source.pop("source_refresh", None)
    source.pop("go_live_packet_fingerprint", None)
    source.pop("previous_go_live_packet_fingerprint", None)
    source.pop("text", None)
    source.pop("live_order_authority", None)
    return source


def _write_go_live_packet_source(root: Path, payload: dict) -> None:
    path = root / "state" / "trading-loop" / "go-live-operator-packet.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_go_live_packet_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-go-live-packet",
                "enabled": True,
                "script": "torben_finance_go_live_packet.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:47:00+00:00",
                "next_run_at": "2026-07-01T12:17:00+00:00",
                "schedule_display": "17,47 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_go_live_packet.py")
    profile_payload = payload | {"source_refresh": _go_live_packet_source_refresh(ratatosk_root)}
    _write_backend_artifact(profile, "torben-finance-go-live-packet-latest.json", profile_payload)


def test_live_profile_verify_passes_go_live_packet_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _go_live_packet_backend_payload()
    source_payload = _go_live_packet_source_payload(profile_payload)
    _write_go_live_packet_profile(profile, ratatosk_root, profile_payload)
    _write_go_live_packet_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_go_live_packet.py"]["go_live_packet_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_generated_at"] == "2026-07-01T11:47:04Z"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_go_live_packet_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _go_live_packet_backend_payload(
        generated_at="2026-07-01T11:47:04Z",
        blockers=["operator_approval"],
    )
    source_shape = _go_live_packet_backend_payload(
        generated_at="2026-07-02T11:47:04Z",
        blockers=["paper_performance", "operator_approval"],
    )
    source_payload = _go_live_packet_source_payload(source_shape)
    _write_go_live_packet_profile(profile, ratatosk_root, profile_payload)
    _write_go_live_packet_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source go-live packet generated_at differs" in error for error in payload["errors"])
    assert any("source go-live packet blockers differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_go_live_packet.py"]["go_live_packet_contract"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "fail"
    assert alignment["mismatches"] == ["generated_at", "blockers", "command_gates"]

def test_live_profile_verify_fails_go_live_packet_without_safe_contract(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-go-live-packet",
                "enabled": True,
                "script": "torben_finance_go_live_packet.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T09:47:00-04:00",
                "next_run_at": "2026-07-01T10:17:00-04:00",
                "schedule_display": "17,47 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_go_live_packet.py")
    _write_backend_artifact(
        profile,
        "torben-finance-go-live-packet-latest.json",
        {
            "task": "torben_finance_go_live_packet",
            "adapter_task": "equity_go_live_operator_packet",
            "schema_version": "equity_go_live_operator_packet_v1",
            "wakeAgent": True,
            "generated_at": "2026-07-01T13:48:00Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "source_refresh_safe": True,
            "go_live_packet_contract_safe": False,
            "status": "blocked",
            "ready_to_submit": False,
            "go_live_blocked": True,
            "read_only": False,
            "broker_review_attempted": True,
            "broker_place_attempted": False,
            "approval_created": True,
            "approval_modified": False,
            "halt_or_circuit_cleared": False,
            "live_flags_enabled": False,
            "operator_mandate": {
                "human_approval_required": True,
                "self_approval_allowed": False,
                "required_approval_scope": "dry_run_promotion",
            },
            "command_gates": {
                "one_shot_live_submit": {
                    "available": True,
                    "reason": None,
                    "blocked_by": [],
                }
            },
            "commands": {
                "one_shot_live_submit": "uv run python scripts/equity_live_canary_from_signal.py",
            },
            "live_order_authority": "review_only",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_go_live_packet.py: go_live_packet_contract_safe is not true"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_go_live_packet.py: read_only is not true"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_go_live_packet.py: blocked go-live packet one_shot_live_submit gate is not unavailable"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_go_live_packet.py: operator_mandate required_approval_scope is not one_shot_live_canary"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_ready_go_live_packet_without_equity_live_flag(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-go-live-packet",
                "enabled": True,
                "script": "torben_finance_go_live_packet.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T09:47:00-04:00",
                "next_run_at": "2026-07-01T10:17:00-04:00",
                "schedule_display": "17,47 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_go_live_packet.py")
    _write_backend_artifact(
        profile,
        "torben-finance-go-live-packet-latest.json",
        {
            "task": "torben_finance_go_live_packet",
            "adapter_task": "equity_go_live_operator_packet",
            "schema_version": "equity_go_live_operator_packet_v1",
            "wakeAgent": True,
            "generated_at": "2026-07-01T13:48:00Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "source_refresh_safe": True,
            "go_live_packet_contract_safe": True,
            "status": "ready_to_submit",
            "ready_to_submit": True,
            "go_live_blocked": False,
            "read_only": True,
            "broker_review_attempted": False,
            "broker_place_attempted": False,
            "approval_created": False,
            "approval_modified": False,
            "halt_or_circuit_cleared": False,
            "live_flags_enabled": False,
            "operator_mandate": {
                "human_approval_required": True,
                "self_approval_allowed": False,
                "required_approval_scope": "one_shot_live_canary",
            },
            "command_gates": {
                "one_shot_live_submit": {
                    "available": True,
                    "reason": None,
                    "blocked_by": [],
                }
            },
            "commands": {
                "one_shot_live_submit": (
                    "RATATOSK_LIVE_TRADING=true ROBINHOOD_LIVE=true "
                    "uv run python scripts/equity_live_canary_from_signal.py --execute-live-order --json"
                ),
            },
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_go_live_packet.py: ready go-live packet one_shot_live_submit command missing scoped live flags"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_repair_window_simulation_without_safe_contract(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-repair-window-simulator",
                "enabled": True,
                "script": "torben_finance_repair_window_simulator.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T09:50:00-04:00",
                "next_run_at": "2026-07-01T10:20:00-04:00",
                "schedule_display": "20,50 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_repair_window_simulator.py")
    _write_backend_artifact(
        profile,
        "torben-finance-repair-window-simulator-latest.json",
        {
            "task": "torben_finance_repair_window_simulator",
            "wakeAgent": True,
            "generated_at": "2026-07-01T13:51:00Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "source_refresh_safe": True,
            "simulation_contract_safe": False,
            "status": "pass",
            "reason": "simulation_passed",
            "repair_plan": {
                "status": "needs_repair_samples",
                "target_new_samples": 3,
                "repair_samples_remaining": 3,
                "preferred_existing_symbols": ["BA"],
                "live_order_authority": "none",
            },
            "requested_samples": 3,
            "candidate_symbols": ["BA", "BA", "BA"],
            "checks": {
                "active_repair_plan": True,
                "isolated_state_root": True,
                "source_state_sample_artifacts_unchanged": False,
                "tick_completed": True,
                "research_batch_succeeded": True,
                "research_selected_requested_samples": True,
                "sample_collector_collected": True,
                "sample_budget_open": True,
                "created_requested_canaries": True,
                "observed_requested_outcomes": True,
                "created_symbols_from_repair_plan": True,
                "live_order_authority_none": True,
                "zero_mutation_counters": True,
                "broker_review_not_attempted": True,
                "broker_place_not_attempted": True,
            },
            "live_order_authority": "none",
            "mutation_counters": {
                "public_actions_taken": 0,
                "external_mutations": 0,
                "orders_submitted": 0,
                "broker_orders_submitted": 0,
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_repair_window_simulator.py: simulation_contract_safe is not true"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_repair_window_simulator.py: "
        "repair-window check source_state_sample_artifacts_unchanged is not true"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_finance_loop_artifact_without_stop_condition(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-loop-heartbeat", "enabled": True, "script": "torben_finance_loop_heartbeat.py"}],
    )
    _write_script(profile, "torben_finance_loop_heartbeat.py")
    _write_backend_artifact(
        profile,
        "torben-finance-loop-heartbeat-latest.json",
        {
            "task": "torben_finance_loop_heartbeat",
            "wakeAgent": True,
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_loop_heartbeat.py: latest artifact missing stop_condition.status"
        in error
        for error in payload["errors"]
    )




def _ratatosk_source_refresh(root: Path, script: str) -> dict:
    return {
        "status": "success",
        "root": str(root),
        "command": ["uv", "run", "python", script, "--json"],
        "returncode": 0,
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }


def _zero_finance_counters() -> dict:
    return {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }


def _write_finance_radar_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-radar",
                "enabled": True,
                "script": "torben_finance_radar.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:30:30+00:00",
                "next_run_at": "2026-07-01T12:00:00+00:00",
                "schedule_display": "35 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_radar.py")
    profile_payload = payload | {
        "source_refresh": _ratatosk_source_refresh(ratatosk_root, "scripts/equity_research_signal_cron.py")
    }
    _write_backend_artifact(profile, "torben-finance-radar-latest.json", profile_payload)


def _write_finance_radar_source(root: Path, payload: dict) -> None:
    path = root / "state" / "equity-research" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _finance_radar_profile_payload(**overrides: object) -> dict:
    payload = {
        "task": "torben_finance_radar",
        "wakeAgent": False,
        "generated_at": "2026-07-01T11:30:30Z",
        "ratatosk_status": "no_actionable_signal",
        "candidate_count": 0,
        "selected_count": 0,
        "primary_next_action": "wait_for_market_open_scan_supply",
        "scan_candidate_supply": {
            "present": True,
            "status": "market_closed",
            "market_count": 40,
            "proposal_count": 0,
            "selected_candidate_count": 0,
            "rejection_reasons": [],
        },
        **_zero_finance_counters(),
    }
    payload.update(overrides)
    return payload


def _finance_radar_source_payload(**overrides: object) -> dict:
    payload = {
        "task": "ratatosk_equity_research_signal_cron",
        "generated_at": "2026-07-01T11:30:04Z",
        "status": "no_actionable_signal",
        "candidate_count": 0,
        "primary_next_action": "wait_for_market_open_scan_supply",
        "live_order_authority": "none",
        "scan_candidate_supply": {
            "status": "market_closed",
            "market_count": 40,
            "proposal_count": 0,
            "selected_candidate_count": 0,
            "rejection_reasons": {},
        },
        **_zero_finance_counters(),
    }
    payload.update(overrides)
    return payload


def test_live_profile_verify_passes_finance_radar_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    _write_finance_radar_profile(profile, ratatosk_root, _finance_radar_profile_payload())
    _write_finance_radar_source(ratatosk_root, _finance_radar_source_payload())

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_radar.py"]["source_artifact_alignment"]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_generated_at"] == "2026-07-01T11:30:04Z"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_finance_radar_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    _write_finance_radar_profile(profile, ratatosk_root, _finance_radar_profile_payload())
    _write_finance_radar_source(ratatosk_root, _finance_radar_source_payload(candidate_count=1))

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source finance radar candidate_count differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_radar.py"]["source_artifact_alignment"]
    assert alignment["status"] == "fail"
    assert "candidate_count" in alignment["mismatches"]


def _heartbeat_stop_condition(**overrides: object) -> dict:
    payload = {
        "status": "wait_for_paper_evidence",
        "primary_next_action": "wait_for_oos_or_market_data",
        "release_conditions": ["new paper outcome, OOS window progress, or explicit optimizer repair demand"],
        "live_order_authority": "none",
        "max_new_samples": 0,
        "max_iterations": 0,
        "broker_orders_submitted": 0,
    }
    payload.update(overrides)
    return payload


def _heartbeat_performance() -> dict:
    return {
        "status": "insufficient",
        "sample_count": 217,
        "hit_rate": 0.58,
        "average_return": 0.013,
        "cumulative_return": 12.5,
        "sharpe_ratio": 0.21,
        "max_drawdown": 0.15,
        "newey_west_tstat_proxy": 1.8,
        "oos_months": 0.22,
        "max_symbol_concentration": 0.23,
        "blocking_reasons": ["paper_performance_gate_failed:sharpe_ratio"],
    }


def _heartbeat_source_payload(**overrides: object) -> dict:
    deterministic_stop_condition = {
        "condition_id": "paper_optimization_until_window_and_repair_targets_clear",
        "wait_when": ["paper_sample_budget.remaining_samples_today == 0"],
    }
    payload = {
        "task": "equity_trading_loop_tick",
        "generated_at": "2026-07-01T11:30:04Z",
        "status": "completed",
        "tick_id": "equity-loop-20260701T113004Z",
        "research_mode": "batch",
        "research": {
            "status": "no_actionable_signal",
            "candidate_count": 0,
            "symbols": [],
        },
        "paper_canary": {"status": "skipped", "reason": "no_torben_worthy_candidate"},
        "primary_next_action": "wait_for_oos_or_market_data",
        "stop_condition": _heartbeat_stop_condition(),
        "deterministic_stop_condition": deterministic_stop_condition,
        "paper_outcome": {"status": "skipped", "signal_id": None, "symbol": None, "failures": []},
        "paper_performance": _heartbeat_performance(),
        "signal_optimizer": {
            "status": "blocked",
            "promotion_decision": "hold",
            "recommended_action_ids": ["wait_for_market_open_scan_supply"],
            "blocking_reasons": ["paper_performance_insufficient"],
        },
        "experiment_evaluation": {"status": "waiting_for_target_samples", "decisions": ["wait"]},
        "risk_incident": {"status": "blocked", "blocking_reasons": ["circuit_breaker_active"]},
        "read_only_broker": True,
        **_zero_finance_counters(),
    }
    payload.update(overrides)
    return payload


def _heartbeat_profile_payload(**overrides: object) -> dict:
    source = _heartbeat_source_payload()
    payload = {
        "task": "torben_finance_loop_heartbeat",
        "adapter_task": "torben_finance_radar",
        "wakeAgent": False,
        "generated_at": "2026-07-01T11:30:30Z",
        "ratatosk_status": source["status"],
        "candidate_count": 0,
        "selected_count": 0,
        "primary_next_action": source["primary_next_action"],
        "loop_heartbeat": {
            "present": True,
            "tick_id": source["tick_id"],
            "status": source["status"],
            "research_mode": source["research_mode"],
            "research_status": source["research"]["status"],
            "research_candidate_count": source["research"]["candidate_count"],
            "research_symbols": source["research"]["symbols"],
            "paper_canary_status": source["paper_canary"]["status"],
            "paper_canary_reason": source["paper_canary"]["reason"],
        },
        "stop_condition": source["stop_condition"],
        "deterministic_stop_condition": source["deterministic_stop_condition"],
        "paper_outcome": source["paper_outcome"],
        "paper_performance": source["paper_performance"],
        "signal_optimizer": source["signal_optimizer"],
        "experiment_evaluation": source["experiment_evaluation"],
        "risk_incident": source["risk_incident"],
        **_zero_finance_counters(),
    }
    payload.update(overrides)
    return payload


def _write_finance_heartbeat_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-loop-heartbeat",
                "enabled": True,
                "script": "torben_finance_loop_heartbeat.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:30:30+00:00",
                "next_run_at": "2026-07-01T12:00:00+00:00",
                "schedule_display": "5,35 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_loop_heartbeat.py")
    profile_payload = payload | {
        "source_refresh": _ratatosk_source_refresh(ratatosk_root, "scripts/equity_trading_loop_tick.py")
    }
    _write_backend_artifact(profile, "torben-finance-loop-heartbeat-latest.json", profile_payload)


def _write_finance_heartbeat_source(root: Path, payload: dict) -> None:
    path = root / "state" / "trading-loop" / "ticks" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_live_profile_verify_passes_finance_loop_heartbeat_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    _write_finance_heartbeat_profile(profile, ratatosk_root, _heartbeat_profile_payload())
    _write_finance_heartbeat_source(ratatosk_root, _heartbeat_source_payload())

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_loop_heartbeat.py"]["source_artifact_alignment"]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_generated_at"] == "2026-07-01T11:30:04Z"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_finance_loop_heartbeat_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    _write_finance_heartbeat_profile(profile, ratatosk_root, _heartbeat_profile_payload())
    source = _heartbeat_source_payload(stop_condition=_heartbeat_stop_condition(status="candidate_available"))
    _write_finance_heartbeat_source(ratatosk_root, source)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source finance loop heartbeat stop_condition.status differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_loop_heartbeat.py"]["source_artifact_alignment"]
    assert alignment["status"] == "fail"
    assert "stop_condition.status" in alignment["mismatches"]

def _risk_monitor_source_refresh(root: Path) -> dict:
    return {
        "status": "success",
        "root": str(root / "risk-monitor-worktree"),
        "state_root": str(root / "state"),
        "canonical_root": str(root),
        "command": [
            "uv",
            "run",
            "python",
            "scripts/equity_trading_risk_monitor.py",
            "--state-root",
            str(root / "state"),
            "--json",
        ],
        "returncode": 0,
        "live_safety_env": {
            "RATATOSK_LIVE_TRADING": "0",
            "ROBINHOOD_LIVE": "0",
            "ROBINHOOD_EQUITY_LIVE": "0",
        },
    }


def _risk_monitor_backend_payload(
    *,
    task: str = "torben_finance_risk_monitor",
    generated_at: str = "2026-07-01T11:38:04Z",
    paper_performance_status: str = "blocked",
) -> dict:
    counters = {
        "public_actions_taken": 0,
        "external_mutations": 0,
        "orders_submitted": 0,
        "broker_orders_submitted": 0,
    }
    stop_condition = {
        "status": "wait_for_paper_evidence",
        "primary_next_action": "wait_for_oos_or_market_data",
        "release_conditions": ["paper_evidence_runway.status == pass"],
        "live_order_authority": "none",
        "mutation_counters": counters,
    }
    return {
        "task": task,
        "adapter_task": "equity_trading_risk_monitor",
        "wakeAgent": False,
        "generated_at": generated_at,
        "status": "blocked",
        "state_root": "/Users/ericfreeman/ratatosk/state",
        "artifact_path": "/Users/ericfreeman/ratatosk/state/trading-loop/risk-monitor.json",
        "blocking_reasons": ["paper_performance", "operator_approval"],
        "warning_reasons": ["historical_verifier_gate_failed:sharpe_ratio"],
        "stop_condition": stop_condition,
        "paper_evidence_runway": {
            "status": "wait_for_paper_evidence",
            "safe_operator_action": "wait_for_oos_or_market_data",
            "commands_live_disabled": True,
            "live_order_authority": "none",
        },
        "evidence_wait_packet": {
            "status": "waiting",
            "checks": {"release_condition_not_met": True},
            "live_order_authority": "none",
        },
        "live_status": {"status": "disabled_until_final_gate", "live_order_authority": "none"},
        "live_order_gate": {"status": "blocked", "live_order_authority": "none"},
        "risk_incident": {"status": "blocked", "live_order_authority": "none"},
        "role_separation_audit": {"status": "pass", "live_order_authority": "none", "mutation_counters": counters},
        "verifier_debt_audit": {"status": "pass", "live_order_authority": "none"},
        "historical_strategy_gate": {"status": "blocked", "live_order_authority": "none"},
        "historical_verifier": {"status": "blocked", "live_order_authority": "none"},
        "paper_performance": {"status": paper_performance_status, "live_order_authority": "none"},
        "paper_calibration": {"status": "blocked", "live_order_authority": "none"},
        "experiment_evaluation": {"status": "active", "live_order_authority": "none"},
        "active_experiment_sample_window": {"status": "open", "live_order_authority": "none"},
        "signal_optimizer": {
            "status": "blocked",
            "calibration_repair_plan": {"status": "needs_repair_samples", "live_order_authority": "none"},
            "live_order_authority": "none",
        },
        "research_candidate_supply": {"status": "wait", "live_order_authority": "none"},
        "heartbeat": {"status": "wait", "live_order_authority": "none"},
        "upstream_mutations": counters,
        "next_actions": ["wait_for_oos_or_market_data"],
        "read_only": True,
        "broker_review_attempted": False,
        "broker_place_attempted": False,
        "persisted": True,
        "loop_readiness_ledger": _loop_readiness_ledger(),
        "quiet_paper_evidence_wait": True,
        "risk_fingerprint": "risk-fingerprint-test",
        "previous_risk_fingerprint": "risk-fingerprint-test",
        "live_order_authority": "none",
        "mutation_counters": counters,
        **counters,
    }


def _risk_monitor_source_payload(profile_payload: dict) -> dict:
    source = json.loads(json.dumps(profile_payload))
    source["task"] = "equity_trading_risk_monitor"
    source.pop("adapter_task", None)
    source.pop("wakeAgent", None)
    source.pop("loop_readiness_ledger", None)
    source.pop("quiet_paper_evidence_wait", None)
    source.pop("risk_fingerprint", None)
    source.pop("previous_risk_fingerprint", None)
    source.pop("source_refresh", None)
    source.pop("text", None)
    source.pop("live_order_authority", None)
    source.pop("mutation_counters", None)
    return source


def _write_risk_monitor_source(root: Path, payload: dict) -> None:
    path = root / "state" / "trading-loop" / "risk-monitor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_risk_monitor_profile(profile: Path, ratatosk_root: Path, payload: dict) -> None:
    _write_jobs(
        profile,
        [
            {
                "name": "torben-finance-risk-monitor",
                "enabled": True,
                "script": "torben_finance_risk_monitor.py",
                "last_status": "ok",
                "last_run_at": "2026-07-01T11:38:00+00:00",
                "next_run_at": "2026-07-01T12:08:00+00:00",
                "schedule_display": "10,40 9-16 * * 1-5",
            }
        ],
    )
    _write_script(profile, "torben_finance_risk_monitor.py")
    profile_payload = payload | {"source_refresh": _risk_monitor_source_refresh(ratatosk_root)}
    _write_backend_artifact(profile, "torben-finance-risk-monitor-latest.json", profile_payload)


def test_live_profile_verify_passes_risk_monitor_source_alignment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _risk_monitor_backend_payload()
    source_payload = _risk_monitor_source_payload(profile_payload)
    _write_risk_monitor_profile(profile, ratatosk_root, profile_payload)
    _write_risk_monitor_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "pass"
    assert alignment["source_artifact_exists"] is True
    assert alignment["source_generated_at"] == "2026-07-01T11:38:04Z"
    assert alignment["mismatches"] == []


def test_live_profile_verify_fails_risk_monitor_source_alignment_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ratatosk_root = tmp_path / "ratatosk"
    profile_payload = _risk_monitor_backend_payload(
        generated_at="2026-07-01T11:38:04Z",
        paper_performance_status="blocked",
    )
    source_shape = _risk_monitor_backend_payload(
        generated_at="2026-07-02T11:38:04Z",
        paper_performance_status="pass",
    )
    source_payload = _risk_monitor_source_payload(source_shape)
    _write_risk_monitor_profile(profile, ratatosk_root, profile_payload)
    _write_risk_monitor_source(ratatosk_root, source_payload)

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any("source risk monitor generated_at differs" in error for error in payload["errors"])
    assert any("source risk monitor paper_performance differs" in error for error in payload["errors"])
    artifacts = {item["script"]: item for item in payload["backend_artifact_health"]["artifacts"]}
    alignment = artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"][
        "source_artifact_alignment"
    ]
    assert alignment["status"] == "fail"
    assert alignment["mismatches"] == ["generated_at", "paper_performance"]

def test_live_profile_verify_fails_risk_monitor_without_loop_readiness_ledger(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-risk-monitor", "enabled": True, "script": "torben_finance_risk_monitor.py"}],
    )
    _write_script(profile, "torben_finance_risk_monitor.py")
    _write_backend_artifact(
        profile,
        "torben-finance-risk-monitor-latest.json",
        {
            "task": "torben_finance_risk_monitor",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:38:04Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "stop_condition": {
                "status": "wait_for_paper_evidence",
                "primary_next_action": "wait_for_oos_or_market_data",
                "release_conditions": [],
            },
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_risk_monitor.py: latest artifact missing loop_readiness_ledger"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_risk_monitor_when_loop_readiness_ledger_allows_live_submit(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-risk-monitor", "enabled": True, "script": "torben_finance_risk_monitor.py"}],
    )
    _write_script(profile, "torben_finance_risk_monitor.py")
    bad_ledger = _loop_readiness_ledger(
        status="ready",
        implementation_status="live_go_ready",
        current_state={
            "safe_operator_action": "prepare_human_live_review_packet",
            "stop_condition": {
                "status": "live_ready",
                "primary_next_action": "prepare_human_live_review_packet",
                "live_order_authority": "none",
            },
            "paper_evidence_runway": {
                "status": "live_ready",
                "safe_operator_action": "prepare_human_live_review_packet",
                "commands_live_disabled": False,
                "live_order_authority": "none",
            },
            "go_live": {
                "status": "ready_to_submit",
                "ready_to_submit": True,
                "go_live_blocked": False,
                "blocker_count": 0,
            },
        },
    )
    _write_backend_artifact(
        profile,
        "torben-finance-risk-monitor-latest.json",
        {
            "task": "torben_finance_risk_monitor",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:38:04Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "stop_condition": {
                "status": "wait_for_paper_evidence",
                "primary_next_action": "wait_for_oos_or_market_data",
                "release_conditions": [],
            },
            "loop_readiness_ledger": bad_ledger,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_risk_monitor.py: loop_readiness_ledger status is not blocked: ready"
        in error
        for error in payload["errors"]
    )
    assert any(
        "backend_artifacts: torben_finance_risk_monitor.py: loop_readiness_ledger ready_to_submit is not false"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_risk_monitor_when_loop_readiness_ledger_lacks_memory(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-risk-monitor", "enabled": True, "script": "torben_finance_risk_monitor.py"}],
    )
    _write_script(profile, "torben_finance_risk_monitor.py")
    bad_ledger = _loop_readiness_ledger(paper_requirements={"self_improvement": {"status": "missing_or_blocked"}})
    _write_backend_artifact(
        profile,
        "torben-finance-risk-monitor-latest.json",
        {
            "task": "torben_finance_risk_monitor",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:38:04Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "stop_condition": {
                "status": "wait_for_paper_evidence",
                "primary_next_action": "wait_for_oos_or_market_data",
                "release_conditions": [],
            },
            "loop_readiness_ledger": bad_ledger,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "backend_artifacts: torben_finance_risk_monitor.py: "
        "loop_readiness_ledger self_improvement status is not pass: missing_or_blocked"
        in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_risk_monitor_when_loop_readiness_ledger_live_flags_enabled(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-risk-monitor", "enabled": True, "script": "torben_finance_risk_monitor.py"}],
    )
    _write_script(profile, "torben_finance_risk_monitor.py")
    bad_ledger = _loop_readiness_ledger()
    bad_ledger["current_state"]["live_promotion_controls"]["live_flags"]["enabled_now"] = True
    _write_backend_artifact(
        profile,
        "torben-finance-risk-monitor-latest.json",
        {
            "task": "torben_finance_risk_monitor",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:38:04Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "stop_condition": {
                "status": "wait_for_paper_evidence",
                "primary_next_action": "wait_for_oos_or_market_data",
                "release_conditions": [],
            },
            "loop_readiness_ledger": bad_ledger,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "loop_readiness_ledger live_flags enabled_now is not false" in error
        for error in payload["errors"]
    )


def test_live_profile_verify_fails_risk_monitor_when_loop_readiness_ledger_optimizer_budget_open(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-risk-monitor", "enabled": True, "script": "torben_finance_risk_monitor.py"}],
    )
    _write_script(profile, "torben_finance_risk_monitor.py")
    bad_ledger = _loop_readiness_ledger()
    bad_ledger["current_state"]["optimizer_evidence"]["sample_budget_open"] = True
    bad_ledger["current_state"]["optimizer_evidence"]["calibration_repair_plan"]["target_new_samples"] = 3
    _write_backend_artifact(
        profile,
        "torben-finance-risk-monitor-latest.json",
        {
            "task": "torben_finance_risk_monitor",
            "wakeAgent": False,
            "generated_at": "2026-07-01T11:38:04Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "stop_condition": {
                "status": "wait_for_paper_evidence",
                "primary_next_action": "wait_for_oos_or_market_data",
                "release_conditions": [],
            },
            "loop_readiness_ledger": bad_ledger,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "fail"
    assert any(
        "loop_readiness_ledger optimizer_evidence sample_budget_open is not false" in error
        for error in payload["errors"]
    )


def test_live_profile_verify_allows_bounded_paper_optimization_budget(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [{"name": "torben-finance-risk-monitor", "enabled": True, "script": "torben_finance_risk_monitor.py"}],
    )
    _write_script(profile, "torben_finance_risk_monitor.py")
    ledger = _loop_readiness_ledger()
    current = ledger["current_state"]
    current["safe_operator_action"] = "run_bounded_paper_optimization_window"
    current["stop_condition"] = {
        "status": "continue_paper_optimization",
        "primary_next_action": "run_bounded_paper_sample_collection",
        "recommended_action_ids": ["run_bounded_paper_optimization_window"],
        "max_new_samples": 3,
        "max_iterations": 3,
        "live_order_authority": "none",
    }
    current["paper_evidence_runway"] = {
        "status": "continue_paper_optimization",
        "safe_operator_action": "run_bounded_paper_optimization_window",
        "max_new_samples": 3,
        "max_iterations": 3,
        "commands_live_disabled": True,
        "live_order_authority": "none",
    }
    current["optimizer_evidence"]["sample_budget_open"] = True
    current["optimizer_evidence"]["calibration_repair_plan"] = {
        "status": "needs_repair_samples",
        "target_new_samples": 3,
        "repair_samples_remaining": 3,
        "live_order_authority": "none",
    }
    _write_backend_artifact(
        profile,
        "torben-finance-risk-monitor-latest.json",
        {
            "task": "torben_finance_risk_monitor",
            "wakeAgent": True,
            "generated_at": "2026-07-01T11:38:04Z",
            "source_refresh": {
                "status": "success",
                "live_safety_env": {
                    "RATATOSK_LIVE_TRADING": "0",
                    "ROBINHOOD_LIVE": "0",
                    "ROBINHOOD_EQUITY_LIVE": "0",
                },
            },
            "stop_condition": current["stop_condition"],
            "loop_readiness_ledger": ledger,
            "public_actions_taken": 0,
            "external_mutations": 0,
            "orders_submitted": 0,
            "broker_orders_submitted": 0,
        },
    )

    payload = verify_torben_live_profile(profile_home=profile)

    assert payload["status"] == "pass"
    artifacts = {
        item["script"]: item
        for item in payload["backend_artifact_health"]["artifacts"]
    }
    ledger_summary = artifacts["torben_finance_risk_monitor.py"]["loop_readiness_ledger"]
    assert ledger_summary["bounded_paper_optimization"] is True
    assert ledger_summary["optimizer_sample_budget_open"] is True
    assert ledger_summary["safe_operator_action"] == "run_bounded_paper_optimization_window"


def test_live_profile_verify_passes_fresh_hygiene_review_artifact_with_degraded_llm_warning(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    now = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
    _write_jobs(
        profile,
        [
            {
                "name": "torben-email-hygiene-weekly-review",
                "enabled": True,
                "script": "torben_email_hygiene_review.py",
                "last_status": "ok",
            }
        ],
    )
    _write_script(profile, "torben_email_hygiene_review.py")
    _write_hygiene_review_artifact(profile, llm_review_status="failed_deterministic_fallback")

    payload = verify_torben_live_profile(profile_home=profile, now=now)

    assert payload["status"] == "pass"
    health = payload["hygiene_review_artifact_health"]
    assert health["status"] == "pass"
    assert health["artifacts"][0]["messages_scanned"] == 1569
    assert health["artifacts"][0]["recommendation_count"] == 1
    assert health["artifacts"][0]["external_mutations"] == 0
    assert any("LLM hygiene review degraded" in warning for warning in payload["warnings"])


def test_live_profile_verify_fails_stale_hygiene_review_artifact(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    now = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
    _write_jobs(
        profile,
        [{"name": "torben-email-hygiene-weekly-review", "enabled": True, "script": "torben_email_hygiene_review.py"}],
    )
    _write_script(profile, "torben_email_hygiene_review.py")
    _write_hygiene_review_artifact(profile, generated_at="2026-06-20T14:23:48Z")

    payload = verify_torben_live_profile(profile_home=profile, now=now)

    assert payload["status"] == "fail"
    assert payload["hygiene_review_artifact_health"]["artifacts"][0]["status"] == "fail"
    assert any("hygiene_review: torben_email_hygiene_review.py: latest review artifact is stale" in error for error in payload["errors"])


def test_live_profile_verify_fails_hygiene_review_mutation_counts(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    now = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
    _write_jobs(
        profile,
        [{"name": "torben-email-hygiene-weekly-review", "enabled": True, "script": "torben_email_hygiene_review.py"}],
    )
    _write_script(profile, "torben_email_hygiene_review.py")
    _write_hygiene_review_artifact(profile, gmail_writes=1, external_mutations=1)

    payload = verify_torben_live_profile(profile_home=profile, now=now)

    assert payload["status"] == "fail"
    assert any("hygiene_review: torben_email_hygiene_review.py: gmail_writes is nonzero: 1" in error for error in payload["errors"])
    assert any("hygiene_review: torben_email_hygiene_review.py: external_mutations is nonzero: 1" in error for error in payload["errors"])


def test_live_profile_verify_fails_hygiene_review_recommendation_count_mismatch(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    now = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
    _write_jobs(
        profile,
        [{"name": "torben-email-hygiene-weekly-review", "enabled": True, "script": "torben_email_hygiene_review.py"}],
    )
    _write_script(profile, "torben_email_hygiene_review.py")
    _write_hygiene_review_artifact(profile, recommendations=[{"handle": "EA-1"}], recommendation_count=2)

    payload = verify_torben_live_profile(profile_home=profile, now=now)

    assert payload["status"] == "fail"
    assert any("recommendation_count mismatch" in error for error in payload["errors"])


def test_live_profile_verify_ignores_stale_self_status_after_repair(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    snapshot = tmp_path / "snapshot"
    _write_jobs(
        profile,
        [
            {
                "name": "torben-live-profile-verify",
                "enabled": True,
                "script": "torben_live_profile_verify.py",
                "last_status": "error",
                "last_error": "previous drift before repair",
                "last_delivery_error": "previous delivery failure",
            }
        ],
    )
    _write_script(profile, "torben_live_profile_verify.py")
    _write_script(snapshot, "torben_live_profile_verify.py")

    payload = verify_torben_live_profile(profile_home=profile, repo_snapshot_home=snapshot)

    assert payload["status"] == "pass"
    assert payload["wakeAgent"] is False
    assert payload["errors"] == []
    assert any("ignoring stale verifier self last_error" in warning for warning in payload["warnings"])
    assert any("ignoring stale verifier self last_status" in warning for warning in payload["warnings"])


def test_live_profile_verify_fails_snapshot_drift(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    snapshot = tmp_path / "snapshot"
    _write_jobs(profile, [{"name": "drifted", "enabled": True, "script": "job.py"}])
    _write_script(profile, "job.py", "print('live')\n")
    _write_script(snapshot, "job.py", "print('snapshot')\n")

    payload = verify_torben_live_profile(profile_home=profile, repo_snapshot_home=snapshot)

    assert payload["status"] == "fail"
    assert any("live script differs from repo snapshot" in error for error in payload["errors"])


def test_live_profile_verify_passes_healthy_gmail_realtime_state(tmp_path: Path) -> None:
    now = datetime(2026, 6, 25, 20, 0, tzinfo=timezone.utc)
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {"name": "pull", "enabled": True, "script": "torben_gmail_pubsub_pull.py", "last_status": "ok"},
            {"name": "renew", "enabled": True, "script": "torben_gmail_watch_register.py", "last_status": "ok"},
        ],
    )
    _write_script(profile, "torben_gmail_pubsub_pull.py")
    _write_script(profile, "torben_gmail_watch_register.py")
    _write_gmail_health_state(
        profile,
        expiration_at="2026-07-02T20:00:00Z",
        pull_generated_at="2026-06-25T19:59:30Z",
    )

    payload = verify_torben_live_profile(profile_home=profile, now=now)

    assert payload["status"] == "pass"
    assert payload["gmail_realtime_health"]["status"] == "pass"
    assert payload["gmail_realtime_health"]["accounts_checked"] == 1


def test_live_profile_verify_fails_gmail_watch_inside_renewal_floor(tmp_path: Path) -> None:
    now = datetime(2026, 6, 25, 20, 0, tzinfo=timezone.utc)
    profile = tmp_path / "profile"
    _write_jobs(
        profile,
        [
            {"name": "pull", "enabled": True, "script": "torben_gmail_pubsub_pull.py", "last_status": "ok"},
            {"name": "renew", "enabled": True, "script": "torben_gmail_watch_register.py", "last_status": "ok"},
        ],
    )
    _write_script(profile, "torben_gmail_pubsub_pull.py")
    _write_script(profile, "torben_gmail_watch_register.py")
    _write_gmail_health_state(
        profile,
        expiration_at="2026-06-27T19:59:00Z",
        pull_generated_at="2026-06-25T19:59:30Z",
    )

    payload = verify_torben_live_profile(profile_home=profile, now=now)

    assert payload["status"] == "fail"
    assert payload["gmail_realtime_health"]["status"] == "fail"
    assert any("gmail watch expires within 48h" in error for error in payload["errors"])


def test_render_verification_failure_is_actionable(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _write_jobs(profile, [{"name": "missing", "enabled": True, "script": "missing.py"}])
    payload = verify_torben_live_profile(profile_home=profile)

    text = render_verification_failure(payload)

    assert "Torben live-profile verification failed." in text
    assert "enabled cron jobs may be blind or noisy" in text
    assert "missing: enabled cron script missing" in text


def test_live_profile_alert_state_suppresses_duplicate_failure(tmp_path: Path) -> None:
    state_path = tmp_path / "alert-state.json"
    now = datetime(2026, 6, 25, 20, 0, tzinfo=timezone.utc)
    payload = {
        "task": "torben_live_profile_verify",
        "status": "fail",
        "wakeAgent": True,
        "errors": ["torben-gmail-pubsub-pull: live script differs from repo snapshot"],
    }

    first_suppressed = update_live_profile_alert_state(payload=payload, state_path=state_path, now=now)
    repeated = dict(payload)
    repeated.pop("alert_dedupe", None)
    second_suppressed = update_live_profile_alert_state(
        payload=repeated,
        state_path=state_path,
        now=now.replace(minute=15),
    )

    assert first_suppressed is False
    assert payload["alert_dedupe"]["status"] == "new_failure"
    assert second_suppressed is True
    assert repeated["alert_dedupe"]["status"] == "duplicate_failure_suppressed"
    assert repeated["alert_dedupe"]["duplicate_count"] == 1
    assert repeated["alert_dedupe"]["fingerprint"] == live_profile_failure_fingerprint(payload)


def test_live_profile_alert_state_alerts_changed_failure_and_clears_on_pass(tmp_path: Path) -> None:
    state_path = tmp_path / "alert-state.json"
    now = datetime(2026, 6, 25, 20, 0, tzinfo=timezone.utc)
    first = {"status": "fail", "errors": ["old drift"], "wakeAgent": True}
    changed = {"status": "fail", "errors": ["new drift"], "wakeAgent": True}
    passed = {"status": "pass", "errors": [], "wakeAgent": False}

    assert update_live_profile_alert_state(payload=first, state_path=state_path, now=now) is False
    assert update_live_profile_alert_state(payload=changed, state_path=state_path, now=now.replace(minute=15)) is False
    assert changed["alert_dedupe"]["status"] == "new_failure"
    assert update_live_profile_alert_state(payload=passed, state_path=state_path, now=now.replace(minute=30)) is False

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "pass"
    assert state["active_fingerprint"] is None
    assert passed["alert_dedupe"]["status"] == "cleared"


def test_live_profile_investigation_request_stages_failure_evidence(tmp_path: Path) -> None:
    request_path = tmp_path / "investigation-request.json"
    payload = {
        "task": "torben_live_profile_verify",
        "status": "fail",
        "wakeAgent": True,
        "generated_at": "2026-06-25T20:00:00Z",
        "profile_home": "/tmp/profile",
        "jobs_path": "/tmp/profile/cron/jobs.json",
        "repo_snapshot_home": "/tmp/repo/profiles/torben",
        "errors": ["torben-gmail-pubsub-pull: live script differs from repo snapshot"],
        "warnings": ["gmail_realtime: pull latest wake reason: test"],
        "script_checks": [
            {
                "name": "torben-gmail-pubsub-pull",
                "script": "torben_gmail_pubsub_pull.py",
                "errors": ["live script differs from repo snapshot"],
            },
            {"name": "healthy", "script": "healthy.py", "errors": []},
        ],
        "gmail_realtime_health": {"status": "pass"},
    }

    request = stage_live_profile_investigation_request(payload=payload, request_path=request_path)

    assert request["wakeAgent"] is True
    assert request["status"] == "pending"
    assert request["failure_fingerprint"] == live_profile_failure_fingerprint(payload)
    assert request["failing_script_checks"][0]["name"] == "torben-gmail-pubsub-pull"
    assert request["investigation_contract"]["approval_required_before_fix"] is True
    assert payload["investigation_request"]["status"] == "staged"


def test_live_profile_investigation_consumer_hands_failure_to_llm_once(tmp_path: Path) -> None:
    request_path = tmp_path / "investigation-request.json"
    state_path = tmp_path / "investigation-state.json"
    payload = {
        "status": "fail",
        "wakeAgent": True,
        "errors": ["missing script"],
        "warnings": [],
        "script_checks": [],
    }
    stage_live_profile_investigation_request(payload=payload, request_path=request_path)

    first = consume_live_profile_investigation_request(request_path=request_path, state_path=state_path)
    second = consume_live_profile_investigation_request(request_path=request_path, state_path=state_path)

    assert first["wakeAgent"] is True
    assert first["status"] == "investigation_requested"
    assert first["request"]["errors"] == ["missing script"]
    assert first["operator_boundary"]["llm_must_not"][0] == "edit files"
    assert second["wakeAgent"] is False
    assert second["status"] == "duplicate_investigation_suppressed"


def test_live_profile_investigation_request_clears_on_pass(tmp_path: Path) -> None:
    request_path = tmp_path / "investigation-request.json"
    state_path = tmp_path / "investigation-state.json"
    passed = {"status": "pass", "wakeAgent": False, "errors": []}

    clear_live_profile_investigation_request(payload=passed, request_path=request_path)
    result = consume_live_profile_investigation_request(request_path=request_path, state_path=state_path)

    assert result["wakeAgent"] is False
    assert result["status"] == "idle"
    assert passed["investigation_request"]["status"] == "cleared"
