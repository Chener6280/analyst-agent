#!/usr/bin/env python3
"""Stable wrapper for the IR System zsxq_web CLI."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    cli = project_root / "ir_system" / "adapters" / "zsxq_web" / "cli.js"
    if not cli.is_file():
        sys.stderr.write('{"status":"error","error":{"code":"zsxq_web_cli_not_found","message":"IR System zsxq_web CLI is missing"}}\n')
        return 3
    node = os.environ.get("NODE_COMMAND", "node")
    completed = subprocess.run([node, str(cli), *sys.argv[1:]], check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
