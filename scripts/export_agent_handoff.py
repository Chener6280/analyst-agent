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

from core.interface.read_api import build_agent_handoff


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser()
    reports_dir = output_root / "scans" / args.scan_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    try:
        handoff = build_agent_handoff(args.scan_id, output_root=output_root, db_path=args.db_path)
    except ValueError as exc:
        print(f"agent_handoff_failed={exc}", file=sys.stderr)
        return 1

    json_path = reports_dir / "agent_handoff.json"
    md_path = reports_dir / "agent_handoff.md"
    json_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(handoff), encoding="utf-8")

    print(f"agent_handoff={md_path}")
    print(f"json={json_path}")
    print(f"status={handoff['status']}")
    return 0 if handoff["status"] in {"ready", "review_required"} else 1


def render_markdown(handoff: dict[str, Any]) -> str:
    lines = [
        "# Agent Handoff",
        "",
        f"Scan: `{handoff['scan_id']}`",
        f"Status: **{handoff['status']}**",
        "",
        "## Headline",
        "",
        handoff.get("headline") or "n/a",
        "",
        "## Artifacts",
        "",
        "| artifact | path |",
        "|---|---|",
    ]
    for key, value in handoff.get("artifacts", {}).items():
        lines.append(f"| {key} | `{value}` |")

    lines.extend(["", "## Supported Queries", "", "| query | example |", "|---|---|"])
    for item in handoff.get("supported_queries", []):
        lines.append(f"| {item['name']} | `{item['example']}` |")

    lines.extend(["", "## Quality", ""])
    quality = handoff.get("quality") or {}
    lines.append(f"- acceptance_passed: {quality.get('acceptance_passed')}")
    lines.append(f"- full_text_rate: {quality.get('full_text_rate')}")
    source_counts = quality.get("source_type_counts") or {}
    lines.append(f"- source_type_counts: {format_count_map(source_counts) if source_counts else 'none'}")
    warnings = quality.get("quality_warnings") or []
    if warnings:
        lines.append("- quality_warnings:")
        for warning in warnings:
            lines.append(f"  - {warning}")

    lines.extend(["", "## Macro Snapshot", "", "| dim | summary | sample | dispersion |", "|---|---|---:|---:|"])
    for item in handoff.get("macro", []):
        lines.append(
            f"| {item.get('name')} | {item.get('summary')} | {item.get('n_non_null')}/{item.get('n_teams')} | "
            f"{format_optional(item.get('dispersion_range'))} |"
        )

    lines.extend(["", "## Strategy Snapshot", "", "| dim | summary | sample | dispersion |", "|---|---|---:|---:|"])
    for item in (handoff.get("strategy") or {}).get("ordinals", []):
        lines.append(
            f"| {item.get('name')} | {item.get('summary')} | {item.get('n_non_null')}/{item.get('n_teams')} | "
            f"{format_optional(item.get('dispersion_range'))} |"
        )

    lines.extend(["", "## Top Entities", "", "| entity | positive | negative | neutral | teams |", "|---|---:|---:|---:|---|"])
    for item in handoff.get("top_entities", []):
        lines.append(
            f"| {item.get('entity')} | {item.get('positive')} | {item.get('negative')} | "
            f"{item.get('neutral')} | {', '.join(item.get('teams') or [])} |"
        )
    if not handoff.get("top_entities"):
        lines.append("| n/a | 0 | 0 | 0 |  |")
    return "\n".join(lines) + "\n"


def format_count_map(counts: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def format_optional(value: Any) -> str:
    return "n/a" if value is None else str(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export P5 handoff package for downstream research agents.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
