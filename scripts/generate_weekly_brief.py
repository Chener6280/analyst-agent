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

from core.schema.stance import MACRO_DIMENSIONS, STRATEGY_DIMENSIONS


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser()
    scan_dir = output_root / "scans" / args.scan_id
    diagnostics_dir = output_root / "diagnostics"
    reports_dir = scan_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    try:
        brief = build_brief(scan_dir, diagnostics_dir=diagnostics_dir)
    except ValueError as exc:
        print(f"weekly_brief_failed={exc}", file=sys.stderr)
        return 1

    json_path = reports_dir / "weekly_brief.json"
    md_path = reports_dir / "weekly_brief.md"
    json_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(brief), encoding="utf-8")

    print(f"weekly_brief={md_path}")
    print(f"json={json_path}")
    return 0


def build_brief(scan_dir: Path, *, diagnostics_dir: Path) -> dict[str, Any]:
    cross_section = read_required_json(scan_dir / "reports" / "weekly_cross_section.json")
    coverage = read_json(scan_dir / "coverage_summary.json")
    extraction = read_json(scan_dir / "extracted" / "extraction_summary.json")
    scan_id = cross_section.get("scan_id") or scan_dir.name
    acceptance = read_json(diagnostics_dir / f"{scan_id}__mvp_acceptance.json") or read_json(
        diagnostics_dir / "mvp_acceptance.json"
    )

    db_counts = cross_section.get("db_counts") or {}
    if int(db_counts.get("stance") or 0) <= 0:
        raise ValueError(f"cross-section has no stance rows for scan: {scan_id}")

    macro = [summarize_ordinal(cross_section.get("macro", {}), dim_key, MACRO_DIMENSIONS[dim_key]) for dim_key in MACRO_DIMENSIONS]
    strategy_ordinals = [
        summarize_ordinal(cross_section.get("strategy", {}), dim_key, STRATEGY_DIMENSIONS[dim_key])
        for dim_key in ["market_view", "liquidity"]
    ]
    strategy_categories = [
        summarize_categorical(cross_section.get("strategy", {}), dim_key, STRATEGY_DIMENSIONS[dim_key])
        for dim_key in ["sector", "style", "theme"]
    ]

    quality = build_quality_summary(coverage, extraction, acceptance)
    evidence = collect_evidence(cross_section)
    return {
        "scan_id": scan_id,
        "scan_dir": str(scan_dir),
        "generated_from": {
            "cross_section": str(scan_dir / "reports" / "weekly_cross_section.json"),
            "coverage": str(scan_dir / "coverage_summary.json"),
            "extraction": str(scan_dir / "extracted" / "extraction_summary.json"),
            "acceptance": str(diagnostics_dir / f"{scan_id}__mvp_acceptance.json"),
        },
        "db_counts": db_counts,
        "headline": build_headline(macro, strategy_ordinals, quality),
        "macro": macro,
        "strategy": {"ordinals": strategy_ordinals, "categories": strategy_categories},
        "quality": quality,
        "evidence": evidence,
    }


def summarize_ordinal(section: dict[str, Any], dim_key: str, dim_def: dict[str, Any]) -> dict[str, Any]:
    item = section.get(dim_key) or {}
    teams = item.get("teams") or []
    n_non_null = int(item.get("n_non_null") or 0)
    mode_label = item.get("mode_label")
    if n_non_null == 0:
        summary = "无有效表态"
    elif item.get("dispersion_range") and item["dispersion_range"] >= 2:
        summary = f"分歧较高，众数为{mode_label}"
    else:
        summary = f"共识偏向{mode_label}"
    return {
        "dim_key": dim_key,
        "name": dim_def["name"],
        "axis": dim_def["axis"],
        "summary": summary,
        "n_teams": item.get("n_teams", 0),
        "n_non_null": n_non_null,
        "mode": item.get("mode"),
        "mode_label": mode_label,
        "median": item.get("median"),
        "dispersion_range": item.get("dispersion_range"),
        "bullish": item.get("n_bullish", 0),
        "neutral": item.get("n_neutral", 0),
        "bearish": item.get("n_bearish", 0),
        "teams": teams[:5],
    }


def summarize_categorical(section: dict[str, Any], dim_key: str, dim_def: dict[str, Any]) -> dict[str, Any]:
    item = section.get(dim_key) or {}
    positive = item.get("top_positive_tags") or []
    negative = item.get("top_negative_tags") or []
    disputed = item.get("disputed_tags") or []
    return {
        "dim_key": dim_key,
        "name": dim_def["name"],
        "axis": dim_def["axis"],
        "n_mentions": item.get("n_mentions", 0),
        "top_positive_tags": positive[:5],
        "top_negative_tags": negative[:5],
        "disputed_tags": disputed[:5],
    }


def build_quality_summary(coverage: dict[str, Any], extraction: dict[str, Any], acceptance: dict[str, Any]) -> dict[str, Any]:
    coverage_summary = coverage.get("summary") or {}
    extraction_quality = extraction.get("quality") or {}
    return {
        "acceptance_passed": acceptance.get("passed"),
        "coverage_total_teams": coverage_summary.get("total_teams"),
        "covered_plus_partial_rate": coverage_summary.get("covered_plus_partial_rate"),
        "full_text_rate": coverage_summary.get("full_text_rate"),
        "source_type_counts": coverage_summary.get("source_type_counts", {}),
        "production_coverage_rate": coverage_summary.get("production_coverage_rate"),
        "official_or_broker_source_rate": coverage_summary.get("official_or_broker_source_rate"),
        "documents_with_any_signal": extraction_quality.get("documents_with_any_signal"),
        "zero_signal_documents": extraction_quality.get("zero_signal_documents", []),
        "quality_warnings": acceptance.get("quality_warnings", []),
        "quality_banner": build_quality_banner(coverage_summary, extraction_quality),
    }


def build_quality_banner(coverage_summary: dict[str, Any], extraction_quality: dict[str, Any]) -> str:
    full_text_rate = parse_percent(coverage_summary.get("full_text_rate"))
    official_rate = parse_percent(coverage_summary.get("official_or_broker_source_rate"))
    zero_signal = extraction_quality.get("zero_signal_documents") or []
    if full_text_rate < 0.5 or official_rate < 0.7 or zero_signal:
        return "数据质量提示：本周结果为 sample MVP 输出。全文覆盖率低，部分来源为转载或研报平台，当前结果不应作为正式投研结论。"
    return "数据质量提示：当前样本满足 production profile 的主要来源质量阈值。"


def collect_evidence(cross_section: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for role, dim_names in {"macro": MACRO_DIMENSIONS, "strategy": STRATEGY_DIMENSIONS}.items():
        role_section = cross_section.get(role) or {}
        for dim_key, dim_def in dim_names.items():
            item = role_section.get(dim_key) or {}
            if dim_def["type"] == "ordinal":
                for team in item.get("teams", [])[:2]:
                    evidence.append(evidence_row(role, dim_key, dim_def["name"], team))
            else:
                for bucket in ["top_positive_tags", "top_negative_tags"]:
                    for tag in item.get(bucket, [])[:2]:
                        for team in tag.get("teams", [])[:1]:
                            row = evidence_row(role, dim_key, dim_def["name"], team)
                            row["tag"] = tag.get("tag")
                            row["lean_bucket"] = bucket
                            evidence.append(row)
    return evidence[:24]


def evidence_row(role: str, dim_key: str, dim_name: str, team: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": role,
        "dim_key": dim_key,
        "dim_name": dim_name,
        "analyst_id": team.get("analyst_id"),
        "institution": team.get("institution"),
        "label": team.get("label") or value_label(team),
        "verbatim": team.get("verbatim"),
        "source_url": team.get("source_url"),
        "source_type": team.get("source_type"),
    }


def value_label(team: dict[str, Any]) -> str | None:
    value = team.get("value")
    if value is None:
        return None
    role = team.get("role")
    dim_key = team.get("dim_key")
    dims = MACRO_DIMENSIONS if role == "macro" else STRATEGY_DIMENSIONS if role == "strategy" else {}
    dim = dims.get(dim_key) or {}
    return dim.get("values", {}).get(value)


def build_headline(macro: list[dict[str, Any]], strategy_ordinals: list[dict[str, Any]], quality: dict[str, Any]) -> str:
    macro_bits = [f"{item['name']}：{item['summary']}" for item in macro if item["n_non_null"] > 0][:3]
    strategy_bits = [f"{item['name']}：{item['summary']}" for item in strategy_ordinals if item["n_non_null"] > 0]
    body = "；".join(macro_bits + strategy_bits)
    if not body:
        body = "本周样本暂无足够非空观点形成结论"
    if quality.get("quality_warnings"):
        return body + "。需结合数据质量提示审阅。"
    return body + "。"


def render_markdown(brief: dict[str, Any]) -> str:
    lines = [
        "# Weekly Analyst Brief",
        "",
        f"Scan: `{brief['scan_id']}`",
        "",
        f"> {brief.get('quality', {}).get('quality_banner', '')}",
        "",
        "## 1. 本周结论",
        "",
        brief["headline"],
        "",
        "## 2. 宏观观点",
        "",
        "| 维度 | 样本 | 众数 | 中位数 | 分歧 | 摘要 |",
        "|---|---:|---|---:|---:|---|",
    ]
    for item in brief["macro"]:
        lines.append(
            f"| {item['name']} | {item['n_non_null']}/{item['n_teams']} | {item['mode_label'] or 'n/a'} | "
            f"{format_value(item['median'])} | {format_value(item['dispersion_range'])} | {item['summary']} |"
        )

    lines.extend(["", "## 3. 策略观点", "", "| 维度 | 样本 | 众数 | 中位数 | 分歧 | 摘要 |", "|---|---:|---|---:|---:|---|"])
    for item in brief["strategy"]["ordinals"]:
        lines.append(
            f"| {item['name']} | {item['n_non_null']}/{item['n_teams']} | {item['mode_label'] or 'n/a'} | "
            f"{format_value(item['median'])} | {format_value(item['dispersion_range'])} | {item['summary']} |"
        )

    lines.extend(["", "### 配置与主题", ""])
    for item in brief["strategy"]["categories"]:
        lines.append(f"- {item['name']}: {format_tags(item)}")

    lines.extend(["", "## 4. 数据质量", ""])
    quality = brief["quality"]
    lines.append(f"- acceptance_passed: {quality.get('acceptance_passed')}")
    lines.append(f"- coverage_total_teams: {quality.get('coverage_total_teams')}")
    lines.append(f"- covered_plus_partial_rate: {quality.get('covered_plus_partial_rate')}")
    lines.append(f"- full_text_rate: {quality.get('full_text_rate')}")
    lines.append(f"- production_coverage_rate: {quality.get('production_coverage_rate')}")
    lines.append(f"- official_or_broker_source_rate: {quality.get('official_or_broker_source_rate')}")
    lines.append(f"- source_type_counts: {format_count_map(quality.get('source_type_counts') or {}) or 'none'}")
    zero_signal = quality.get("zero_signal_documents") or []
    lines.append(f"- zero_signal_documents: {', '.join(zero_signal) if zero_signal else 'none'}")
    warnings = quality.get("quality_warnings") or []
    if warnings:
        lines.append("- quality_warnings:")
        for warning in warnings:
            lines.append(f"  - {warning}")

    lines.extend(
        [
            "",
            "## 5. 证据摘录",
            "",
            "| 角色 | 维度 | 团队 | 观点/标签 | 原文摘录 | 来源 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in brief["evidence"]:
        label = row.get("tag") or row.get("label") or "n/a"
        source = format_source(row.get("source_url"), row.get("source_type"))
        lines.append(
            f"| {row.get('role')} | {row.get('dim_name')} | {row.get('analyst_id')} | {label} | "
            f"{row.get('verbatim') or ''} | {source} |"
        )
    return "\n".join(lines) + "\n"


def format_tags(item: dict[str, Any]) -> str:
    positive = ", ".join(f"+{tag['tag']}({tag['positive_count']})" for tag in item.get("top_positive_tags", []))
    negative = ", ".join(f"-{tag['tag']}({tag['negative_count']})" for tag in item.get("top_negative_tags", []))
    disputed = ", ".join(tag["tag"] for tag in item.get("disputed_tags", []))
    parts = [part for part in [positive, negative, f"分歧: {disputed}" if disputed else ""] if part]
    return "; ".join(parts) if parts else "无有效标签"


def format_count_map(counts: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def parse_percent(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value)
    if not text.endswith("%"):
        return 0.0
    try:
        return float(text[:-1]) / 100
    except ValueError:
        return 0.0


def format_source(url: str | None, source_type: str | None) -> str:
    if not url:
        return source_type or "n/a"
    if source_type:
        return f"[{source_type}]({url})"
    return url


def format_value(value: Any) -> str:
    return "n/a" if value is None else str(value)


def read_required_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic weekly analyst brief from P3 outputs.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
