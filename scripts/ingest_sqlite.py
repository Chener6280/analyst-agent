#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.store.db import ingest_scan


def main() -> int:
    args = parse_args()
    scan_dir = Path(args.output_root).expanduser() / "scans" / args.scan_id
    summary = ingest_scan(scan_dir, db_path=args.db_path, analyst_list_path=args.analyst_list)
    print(f"db_path={summary['db_path']}")
    print(f"scan_id={summary['scan_id']}")
    print(f"stance_docs={summary['stance_docs']}")
    print(f"stance_rows={summary['stance_rows']}")
    print(f"selection_rows={summary['selection_rows']}")
    print(f"source_rows={summary['source_rows']}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Phase 2 stance JSON into SQLite.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
