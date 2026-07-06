#!/usr/bin/env python3
"""Torben Loopy memory maintenance wrapper."""

from __future__ import annotations

import sys

from tools.loopy_memory_tool import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
