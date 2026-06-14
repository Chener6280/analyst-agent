#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.retrieval.source_matrix import DEFAULT_SOURCE_MATRIX, EXTERNAL_SOURCE_MATRIX


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser()
    target = Path(args.target).expanduser()
    if not source.exists():
        print(f"source_missing={source}")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.check:
        same = target.exists() and source.read_bytes() == target.read_bytes()
        print(f"source={source}")
        print(f"target={target}")
        print(f"in_sync={same}")
        return 0 if same else 1
    shutil.copyfile(source, target)
    print(f"synced_source={source}")
    print(f"synced_target={target}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync project broker_wechat_matrix.md to the ir_search work mirror.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE_MATRIX))
    parser.add_argument("--target", default=str(EXTERNAL_SOURCE_MATRIX))
    parser.add_argument("--check", action="store_true", help="Only check whether source and target are identical.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
