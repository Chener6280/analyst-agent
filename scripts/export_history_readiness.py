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

from core.history.timeseries import build_history_readiness


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser()
    reports_dir = output_root / "scans" / args.scan_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    readiness = build_history_readiness(args.scan_id, db_path=args.db_path, min_scans=args.min_scans)

    json_path = reports_dir / "history_readiness.json"
    md_path = reports_dir / "history_readiness.md"
    json_path.write_text(json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(readiness), encoding="utf-8")

    print(f"history_readiness={md_path}")
    print(f"json={json_path}")
    print(f"status={readiness['status']}")
    return 0 if readiness["status"] in {"ready", "insufficient_history"} else 1


def render_markdown(readiness: dict[str, Any]) -> str:
    lines = [
        "# History Readiness",
        "",
        f"Scan: `{readiness['scan_id']}`",
        f"Status: **{readiness['status']}**",
        "",
        "## Threshold",
        "",
        f"- min_scans_for_trend: {readiness['min_scans_for_trend']}",
        f"- available_scan_count: {readiness['available_scan_count']}",
        f"- missing_scan_count: {readiness['missing_scan_count']}",
        "",
        "## Notes",
        "",
    ]
    for note in readiness.get("notes", []):
        lines.append(f"- {note}")

    lines.extend(["", "## Available Scans", "", "| scan_id | window | teams | stance_rows |", "|---|---|---:|---:|"])
    for scan in readiness.get("available_scans", []):
        window = f"{scan.get('window_start')} to {scan.get('window_end')}"
        lines.append(f"| {scan.get('scan_id')} | {window} | {scan.get('team_count')} | {scan.get('stance_rows')} |")
    if not readiness.get("available_scans"):
        lines.append("| n/a | n/a | 0 | 0 |")

    examples = readiness.get("examples") or {}
    lines.extend(["", "## Current Scan Snapshot", ""])
    growth = examples.get("current_growth")
    if growth:
        lines.append(
            "- macro.growth: n_non_null={n_non_null}, mode={mode_label}, median={median}, dispersion={dispersion_range}".format(
                **growth
            )
        )
    sector = examples.get("current_sector")
    if sector:
        lines.append(f"- strategy.sector mentions: {sector.get('n_mentions')}")
        positives = ", ".join(tag["tag"] for tag in sector.get("top_positive_tags", []))
        negatives = ", ".join(tag["tag"] for tag in sector.get("top_negative_tags", []))
        lines.append(f"- strategy.sector positive tags: {positives or 'none'}")
        lines.append(f"- strategy.sector negative tags: {negatives or 'none'}")

    lines.extend(["", "## Supported Queries", "", "| query | example |", "|---|---|"])
    for item in readiness.get("supported_queries", []):
        lines.append(f"| {item['name']} | `{item['example']}` |")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export P6 history readiness and time-series query hints.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    parser.add_argument("--min-scans", type=int, default=4)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
