from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WATCH = Path("/Users/ericfreeman/.hermes/profiles/torben/scripts/manus_cancellation_watch.py")
NEXT_FOLLOW_UP_AFTER = datetime.fromisoformat("2026-07-01T18:55:00+00:00")


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
        print(f"FIN-20260629-003 Manus cancellation watcher failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.returncode or 1
    try:
        data = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001 - cron boundary records unreadable child output.
        print(f"FIN-20260629-003 Manus cancellation watcher returned unreadable output: {exc}")
        return 1

    if data.get("cancellation_confirmed_detected"):
        print("FIN-20260629-003 Manus cancellation appears confirmed by vendor reply. Review case note and mark closed.")
        return 0
    if data.get("blocked_detected"):
        print(
            "FIN-20260629-003 Manus cancellation is blocked by vendor reply. "
            "It likely requires self-service login/downgrade. I need Eric to complete or provide the required login path."
        )
        return 0
    if int(data.get("vendor_messages_found") or 0) > 0:
        latest = (data.get("latest_messages") or [{}])[0]
        print(
            "FIN-20260629-003 Manus cancellation has a vendor-related reply to review. Latest: "
            + str(latest.get("from"))
            + " / "
            + str(latest.get("subject"))
        )
        return 0
    if datetime.now(timezone.utc) >= NEXT_FOLLOW_UP_AFTER:
        print(
            "FIN-20260629-003 Manus cancellation follow-up is due. "
            "No vendor reply detected since the cancellation request. "
            "Next move: send a short follow-up to contact@manus.im or use self-service login if available."
        )
    return 0


if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("manus_cancellation_watchdog", main))
