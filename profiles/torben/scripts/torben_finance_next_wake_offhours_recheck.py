#!/usr/bin/env python3
"""Run Torben finance next-wake rechecks without off-hours bounded collection."""

from __future__ import annotations

import os

try:  # Package import under pytest.
    from . import torben_finance_next_wake_runner
except ImportError:  # Direct script execution from HERMES_HOME/scripts.
    import torben_finance_next_wake_runner  # type: ignore[no-redef]


def main() -> int:
    os.environ.setdefault("TORBEN_FINANCE_NEXT_WAKE_RUNNER_BLOCK_BOUNDED", "1")
    return torben_finance_next_wake_runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
