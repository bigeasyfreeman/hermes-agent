from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

WATCH = Path("/Users/ericfreeman/.hermes/profiles/torben/scripts/fin_20260701_002_semgrep_watch.py")


def main() -> int:
    proc = subprocess.run(
        ["uv", "run", "python", str(WATCH)],
        cwd="/Users/ericfreeman/.hermes/hermes-agent",
        env={**os.environ, "HERMES_HOME": "/Users/ericfreeman/.hermes/profiles/torben"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
        check=False,
    )
    if proc.returncode != 0:
        print("FIN-20260701-002 Semgrep watcher failed: " + (proc.stderr.strip() or proc.stdout.strip()))
        return proc.returncode or 1
    try:
        data = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001 - cron boundary records unreadable child output.
        print("FIN-20260701-002 Semgrep watcher returned unreadable output: " + str(exc))
        return 1
    if int(data.get("new_relevant_count") or 0) > 0:
        latest = (data.get("new_relevant_messages") or [{}])[0]
        print(
            "FIN-20260701-002 Semgrep cancellation/refund loop has new relevant email: "
            + str(latest.get("from"))
            + " / "
            + str(latest.get("subject"))
            + ". Review case note and decide next action."
        )
    return 0


if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("FIN-20260701-002 Semgrep cancellation watcher", main))
