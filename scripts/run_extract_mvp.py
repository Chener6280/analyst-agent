#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.retrieval.extract import MODEL_VERSION_RULES, run_extraction


def main() -> int:
    args = parse_args()
    scan_dir = Path(args.output_root).expanduser() / "scans" / args.scan_id
    summary = run_extraction(scan_dir, model_version=args.model_version)
    print(f"scan_id={summary['scan_id']}")
    print(f"extracted_dir={summary['extracted_dir']}")
    print(f"eligible_count={summary['eligible_count']}")
    print(f"written_count={summary['written_count']}")
    print(f"failed_count={summary['failed_count']}")
    print(f"passed={summary['passed']}")
    return 0 if summary["passed"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 2 stance extraction MVP.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--model-version", default=MODEL_VERSION_RULES)
    parser.add_argument("--output-root", default="~/macro-strategy")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
