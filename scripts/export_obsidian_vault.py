#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.obsidian.export import export_scan_to_obsidian


def main() -> int:
    args = parse_args()
    try:
        manifest = export_scan_to_obsidian(
            args.scan_id,
            output_root=args.output_root,
            vault_path=args.vault,
            obsidian_root=args.obsidian_root,
        )
    except ValueError as exc:
        print(f"obsidian_export_failed={exc}", file=sys.stderr)
        return 1

    print(f"obsidian_root={manifest['obsidian_root']}")
    print(f"entry_note={manifest['entry_note']}")
    print(f"institution_notes={manifest['institution_notes']}")
    print(f"topic_notes={manifest['topic_notes']}")
    print(f"source_links={manifest['source_links']}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a weekly analyst-agent scan into an Obsidian vault.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--vault", default="~/Documents/Obsidian Vault")
    parser.add_argument("--obsidian-root", default="Analyst Agent")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

