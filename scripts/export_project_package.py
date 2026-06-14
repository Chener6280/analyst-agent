#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.package.delivery import build_project_package


def main() -> int:
    args = parse_args()
    manifest = build_project_package(
        args.scan_id,
        output_root=args.output_root,
        db_path=args.db_path,
        repo_root=REPO_ROOT,
    )
    print(f"project_package={manifest['package_dir']}")
    print(f"json={manifest['package_files']['project_completion_json']}")
    print(f"status={manifest['status']}")
    return 0 if manifest["status"] in {"ready", "review_required"} else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export final project delivery package.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
