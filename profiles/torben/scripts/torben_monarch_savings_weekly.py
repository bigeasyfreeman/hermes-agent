#!/usr/bin/env python3
"""Cron wrapper for Torben's weekly Monarch subscription/license savings review."""

from torben_monarch_savings import main


if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("torben-monarch-savings-weekly", lambda: main(["--loop", "weekly"])))
