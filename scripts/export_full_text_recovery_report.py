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

from core.config import load_analyst_list
from core.retrieval.source_whitelist import load_source_whitelist, official_account_suggestions


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser()
    scan_dir = output_root / "scans" / args.scan_id
    reports_dir = scan_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report = build_recovery_report(
        scan_dir,
        analyst_list=args.analyst_list,
        source_whitelist=args.source_whitelist,
    )
    json_path = reports_dir / "full_text_recovery_report.json"
    md_path = reports_dir / "full_text_recovery_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"full_text_recovery_report={md_path}")
    print(f"json={json_path}")
    print(f"production_ready={report['production_ready']}")
    return 0


def build_recovery_report(scan_dir: Path, *, analyst_list: str, source_whitelist: str) -> dict[str, Any]:
    coverage = read_json(scan_dir / "coverage_summary.json")
    extraction = read_json(scan_dir / "extracted" / "extraction_summary.json")
    whitelist = load_source_whitelist(source_whitelist)
    teams = [team for team in load_analyst_list(analyst_list) if team["active"]]
    coverage_by_id = {item["analyst_id"]: item for item in coverage.get("teams", [])}
    zero_signal = set((extraction.get("quality") or {}).get("zero_signal_documents") or [])
    rows = []
    for team in teams:
        item = coverage_by_id.get(team["analyst_id"], {})
        rows.append(recovery_row(team, item, zero_signal, whitelist))
    rows = sorted(rows, key=lambda row: (priority_rank(row["priority"]), row["analyst_id"]))
    summary = build_summary(coverage.get("summary", {}), rows, zero_signal)
    production_ready = (
        parse_percent(summary.get("production_coverage_rate")) >= 0.60
        and parse_percent(summary.get("full_text_rate")) >= 0.50
        and parse_percent(summary.get("official_or_broker_source_rate")) >= 0.70
        and int(summary.get("zero_signal_count") or 0) <= 1
    )
    return {
        "scan_id": coverage.get("scan_id") or scan_dir.name,
        "summary": summary,
        "production_ready": production_ready,
        "priority_recovery_list": rows,
    }


def recovery_row(team: dict[str, Any], item: dict[str, Any], zero_signal: set[str], whitelist: dict[str, Any]) -> dict[str, Any]:
    source = (item.get("sources") or [{}])[0]
    issues = []
    analyst_id = team["analyst_id"]
    text_access = item.get("text_access") or "missing"
    source_type = item.get("source_type") or "unknown"
    source_completeness = item.get("source_completeness") or source.get("source_completeness") or "unknown"
    if analyst_id in zero_signal:
        issues.append("zero_signal")
    if text_access != "full_text":
        issues.append(text_access)
    if source_type not in {"official_wechat", "broker_official"}:
        issues.append("non_official")
    if text_access != "full_text" and source_completeness != "full_article":
        issues.append("not_full_article")
    whitelist_review = official_account_suggestions(team, whitelist)
    if whitelist_review["needs_review"]:
        issues.append("whitelist_review")
    priority = assign_priority(issues, text_access, source_type)
    return {
        "priority": priority,
        "analyst_id": analyst_id,
        "institution": team.get("institution"),
        "role": team.get("role"),
        "current_source_type": source_type,
        "text_access": text_access,
        "source_completeness": source_completeness,
        "source_url": source.get("url") or "",
        "account_name": source.get("account_name") or "",
        "issues": issues,
        "recommended_action": recommended_action(priority, issues),
        "whitelist_accounts": whitelist_review.get("whitelist_accounts", []),
    }


def assign_priority(issues: list[str], text_access: str, source_type: str) -> str:
    if "zero_signal" in issues or (source_type not in {"official_wechat", "broker_official"} and text_access != "full_text"):
        return "P0"
    if text_access != "full_text" or source_type not in {"official_wechat", "broker_official"}:
        return "P1"
    if source_type not in {"official_wechat", "broker_official"}:
        return "P2"
    if "zero_signal" in issues:
        return "P3"
    return "OK"


def recommended_action(priority: str, issues: list[str]) -> str:
    if priority == "OK":
        return "无需补采"
    if "zero_signal" in issues:
        return "优先补官方公众号全文，并复核该样本是否为观点正文"
    if "non_official" in issues:
        return "补官方公众号或券商官方研究平台全文"
    if "not_full_article" in issues:
        return "补 full_article 正文并标注 source_completeness"
    return "补充高可信全文来源"


def build_summary(summary: dict[str, Any], rows: list[dict[str, Any]], zero_signal: set[str]) -> dict[str, Any]:
    total = int(summary.get("total_teams") or len(rows))
    full_text = int(summary.get("full_text_count") or 0)
    official = sum(1 for row in rows if row["current_source_type"] in {"official_wechat", "broker_official"})
    return {
        "total_teams": total,
        "full_text_count": full_text,
        "partial_text_count": int(summary.get("partial_text_count") or 0),
        "full_text_rate": summary.get("full_text_rate"),
        "production_coverage_rate": summary.get("production_coverage_rate"),
        "official_source_count": official,
        "non_official_source_count": total - official,
        "official_or_broker_source_rate": summary.get("official_or_broker_source_rate"),
        "zero_signal_count": len(zero_signal),
        "p0_count": sum(1 for row in rows if row["priority"] == "P0"),
        "p1_count": sum(1 for row in rows if row["priority"] == "P1"),
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Full-text Recovery Report",
        "",
        f"Scan: `{report['scan_id']}`",
        f"Production ready: **{'yes' if report['production_ready'] else 'no'}**",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "|---|---:|",
    ]
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Priority Recovery List",
            "",
            "| priority | analyst_id | current_source_type | text_access | source_completeness | source_url | issue | recommended_action |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["priority_recovery_list"]:
        lines.append(
            "| {priority} | {analyst_id} | {source_type} | {text_access} | {completeness} | {url} | {issues} | {action} |".format(
                priority=row["priority"],
                analyst_id=row["analyst_id"],
                source_type=row["current_source_type"],
                text_access=row["text_access"],
                completeness=row["source_completeness"],
                url=row["source_url"],
                issues=", ".join(row["issues"]) or "none",
                action=row["recommended_action"],
            )
        )
    return "\n".join(lines) + "\n"


def priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "OK": 9}.get(priority, 8)


def parse_percent(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value)
    if not text.endswith("%"):
        return 0.0
    return float(text[:-1]) / 100


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export full-text recovery report for low-quality analyst-view samples.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--analyst-list", default="data/analyst-list-acceptance-candidates.md")
    parser.add_argument("--source-whitelist", default="data/source_whitelist.yaml")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
