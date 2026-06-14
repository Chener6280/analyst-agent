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

from core.schema.stance import dimensions_for_role
from core.store.queries import build_cross_section


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser()
    scan_dir = output_root / "scans" / args.scan_id
    try:
        data = build_cross_section(args.scan_id, db_path=args.db_path)
    except ValueError as exc:
        print(f"aggregation_failed={exc}", file=sys.stderr)
        return 1
    coverage = read_json(scan_dir / "coverage_summary.json")

    reports_dir = scan_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "weekly_cross_section.json"
    md_path = reports_dir / "weekly_cross_section.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(data, coverage), encoding="utf-8")

    if args.output == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"weekly_cross_section={md_path}")
        print(f"json={json_path}")
    return 0


def render_markdown(data: dict[str, Any], coverage: dict[str, Any]) -> str:
    lines = [
        f"# Weekly Cross Section: {data['scan_id']}",
        "",
        "## 1. Coverage Summary",
        "",
    ]
    summary = coverage.get("summary", {})
    if summary:
        lines.extend(["| metric | value |", "|---|---:|"])
        for key in [
            "total_teams",
            "covered",
            "partial",
            "not_found",
            "source_lost",
            "covered_plus_partial_rate",
            "full_or_partial_text_rate",
            "full_text_rate",
            "high_or_med_attribution_rate",
            "mock_or_placeholder_count",
        ]:
            if key in summary:
                lines.append(f"| {key} | {summary[key]} |")
        source_type_counts = summary.get("source_type_counts") or {}
        if source_type_counts:
            lines.append(f"| source_type_counts | {format_count_map(source_type_counts)} |")
    else:
        lines.append("Coverage summary not found.")

    lines.extend(
        [
            "",
            "## 2. SQLite Summary",
            "",
            "| table | rows |",
            "|---|---:|",
        ]
    )
    for table, count in (data.get("db_counts") or {}).items():
        lines.append(f"| {table} | {count} |")

    lines.extend(["", "## 3. Macro Cross Section", ""])
    for dim_key, dim_def in dimensions_for_role("macro").items():
        if dim_def["type"] != "ordinal":
            continue
        lines.extend(render_ordinal_section(dim_key, data["macro"].get(dim_key, {})))

    lines.extend(["", "## 4. Strategy Cross Section", ""])
    for dim_key, dim_def in dimensions_for_role("strategy").items():
        if dim_def["type"] == "ordinal":
            lines.extend(render_ordinal_section(dim_key, data["strategy"].get(dim_key, {})))
        else:
            lines.extend(render_categorical_section(dim_key, data["strategy"].get(dim_key, {})))

    lines.extend(
        [
            "",
            "## 5. Entity Mentions",
            "",
            "| entity | positive | negative | neutral | teams |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for item in data.get("entities", []):
        lines.append(
            f"| {item['entity']} | {item['positive']} | {item['negative']} | {item['neutral']} | {', '.join(item['teams'])} |"
        )
    if not data.get("entities"):
        lines.append("|  |  |  |  |  |")

    lines.extend(render_quality_notes(coverage))
    return "\n".join(lines) + "\n"


def render_ordinal_section(dim_key: str, item: dict[str, Any]) -> list[str]:
    lines = [
        f"### {dim_key}",
        "",
        f"- 表态团队数：{item.get('n_non_null', 0)} / {item.get('n_teams', 0)}",
        f"- 中位数：{format_optional(item.get('median'))}",
        f"- 众数：{format_mode(item.get('mode'), item.get('mode_label'))}",
        f"- 分歧度：{format_optional(item.get('dispersion_range'))}",
        "- 主要证据：",
    ]
    teams = item.get("teams", [])
    if not teams:
        lines.append("  - 无")
    for team in teams[:5]:
        lines.append(
            "  - {analyst_id}: {label}，{verbatim}，{source_url}".format(
                analyst_id=team.get("analyst_id"),
                label=team.get("label"),
                verbatim=team.get("verbatim"),
                source_url=team.get("source_url") or "",
            )
        )
    lines.append("")
    return lines


def render_categorical_section(dim_key: str, item: dict[str, Any]) -> list[str]:
    lines = [f"### {dim_key}", ""]
    positives = item.get("top_positive_tags", [])
    negatives = item.get("top_negative_tags", [])
    lines.append("- 正向标签：" + format_tags(positives[:5]))
    lines.append("- 负向标签：" + format_tags(negatives[:5]))
    lines.append("- 分歧标签：" + format_tags(item.get("disputed_tags", [])[:5]))
    lines.append("")
    return lines


def format_tags(items: list[dict[str, Any]]) -> str:
    if not items:
        return "无"
    return "；".join(
        f"{item['tag']} (+{item['positive_count']}/-{item['negative_count']}/={item['neutral_count']})" for item in items
    )


def format_optional(value: Any) -> str:
    return "无" if value is None else str(value)


def format_mode(value: Any, label: Any) -> str:
    if value is None:
        return "无"
    return f"{value} {label or ''}".rstrip()


def render_quality_notes(coverage: dict[str, Any]) -> list[str]:
    lines = ["", "## 6. Data Quality Notes", ""]
    teams = coverage.get("teams", [])
    text_counts = count_values(teams, "text_access")
    source_counts = count_values(teams, "source_type")
    partial = [team["analyst_id"] for team in teams if team.get("text_access") == "partial_text"]
    snippet = [team["analyst_id"] for team in teams if team.get("text_access") == "snippet_only"]
    fallback = [team["analyst_id"] for team in teams if team.get("fallback_hit")]
    low = [team["analyst_id"] for team in teams if team.get("attribution_confidence") == "low"]
    non_official = [
        f"{team['analyst_id']}({team.get('source_type') or 'unknown'})"
        for team in teams
        if team.get("source_type") not in {None, "", "official_wechat"}
    ]
    freshness = [team["analyst_id"] for team in teams if team.get("freshness_note")]
    lines.append(f"- 文本访问分布：{format_count_map(text_counts) if text_counts else '无'}")
    lines.append(f"- 来源类型分布：{format_count_map(source_counts) if source_counts else '无'}")
    lines.append(f"- partial_text 样本（非全文）：{', '.join(partial) if partial else '无'}")
    lines.append(f"- snippet_only 未抽取样本：{', '.join(snippet) if snippet else '无'}")
    lines.append(f"- fallback 样本：{', '.join(fallback) if fallback else '无'}")
    lines.append(f"- 低置信度样本：{', '.join(low) if low else '无'}")
    lines.append(f"- 非官方来源样本：{', '.join(non_official) if non_official else '无'}")
    lines.append(f"- freshness/fallback 提示样本：{', '.join(freshness) if freshness else '无'}")
    return lines


def count_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def format_count_map(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate the current scan into a weekly cross-section report.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
