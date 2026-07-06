#!/usr/bin/env python3
"""Cron wrapper for Torben's daily Monarch spend-anomaly review."""

from torben_monarch_savings import main


if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("torben-monarch-savings-daily", lambda: main(["--loop", "daily"])))
