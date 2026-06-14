#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.visual.charts import build_visual_pack


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser()
    reports_dir = output_root / "scans" / args.scan_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    try:
        pack = build_visual_pack(args.scan_id, output_root=output_root, db_path=args.db_path)
    except ValueError as exc:
        print(f"visual_pack_failed={exc}", file=sys.stderr)
        return 1

    json_path = reports_dir / "visual_pack.json"
    md_path = reports_dir / "visual_pack.md"
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(pack), encoding="utf-8")

    print(f"visual_pack={md_path}")
    print(f"json={json_path}")
    print(f"status={pack['status']}")
    return 0 if pack["status"] == "ready" else 1


def render_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Visual Pack",
        "",
        f"Scan: `{pack['scan_id']}`",
        f"Status: **{pack['status']}**",
        f"History status: `{pack.get('history_status')}`",
        "",
        "## Visuals",
        "",
        "| title | source | bytes | path |",
        "|---|---|---:|---|",
    ]
    for item in pack.get("visuals", []):
        lines.append(f"| {item['title']} | {item['source']} | {item['bytes']} | `{item['path']}` |")

    notes = pack.get("notes") or []
    if notes:
        lines.extend(["", "## Notes", ""])
        for note in notes:
            lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export P7 SVG visual pack from local analyst-view artifacts.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
