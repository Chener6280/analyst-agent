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

from scripts.diagnostic_io import write_diagnostic_pair


def main() -> int:
    args = parse_args()
    scan_dir = Path(args.scan_dir).expanduser()
    diagnostics_dir = Path(args.diagnostics_dir).expanduser()

    result = build_readiness(scan_dir, diagnostics_dir)
    json_path, md_path, scan_json_path, scan_md_path = write_diagnostic_pair(
        diagnostics_dir,
        stem="phase2_readiness",
        scan_id=result.get("scan_id"),
        data=result,
        markdown=render_markdown(result),
    )

    print(f"phase2_readiness={md_path}")
    print(f"json={json_path}")
    if scan_md_path:
        print(f"phase2_readiness_scan={scan_md_path}")
    if scan_json_path:
        print(f"json_scan={scan_json_path}")
    print(f"ready={result['ready']}")
    return 0 if result["ready"] else 1


def build_readiness(scan_dir: Path, diagnostics_dir: Path) -> dict[str, Any]:
    coverage = read_json(scan_dir / "coverage_summary.json")
    coverage_scan_id = coverage.get("scan_id") or scan_dir.name
    validation = read_validation_json(diagnostics_dir, coverage_scan_id)

    failed_reasons: list[str] = []
    summary = coverage.get("summary", {})
    eligible = eligible_samples(coverage)
    validation_required = any(sample.get("source") == "manual_wechat" for sample in eligible)
    validation_passed = bool(validation.get("passed"))
    if validation_required and not validation_passed:
        failed_reasons.append("manual_wechat real sample validation has not passed")
    validation_window = validation.get("window") or {}
    coverage_window = first_team_window(coverage)
    if validation_required and validation_window and coverage_window and not same_window(validation_window, coverage_window):
        failed_reasons.append("manual_wechat validation window does not match coverage window")

    phase1_gate = summary.get("phase1_gate", {})
    required_gates = [
        "covered_plus_partial_ge_60",
        "full_or_partial_text_ge_40",
        "high_or_med_attribution_ge_70",
        "mock_or_placeholder_eq_0",
    ]
    for gate in required_gates:
        if phase1_gate.get(gate) is not True:
            failed_reasons.append(f"coverage gate failed: {gate}")

    if len(eligible) < 1:
        failed_reasons.append("no eligible live/manual WeChat samples for Phase 2")

    ready = not failed_reasons
    return {
        "ready": ready,
        "scan_id": coverage_scan_id,
        "failed_reasons": failed_reasons,
        "validation": {
            "required": validation_required,
            "passed": validation_passed,
            "file_count": validation.get("file_count"),
            "template_count": validation.get("template_count"),
            "passed_teams": validation.get("passed_teams"),
            "total_teams": validation.get("total_teams"),
            "week_dir": validation.get("week_dir"),
            "window": validation_window,
        },
        "coverage_window": coverage_window,
        "coverage_summary": summary,
        "eligible_samples": eligible,
    }


def first_team_window(coverage: dict[str, Any]) -> dict[str, Any]:
    teams = coverage.get("teams") or []
    if not teams:
        return {}
    return teams[0].get("window") or {}


def read_validation_json(diagnostics_dir: Path, scan_id: str) -> dict[str, Any]:
    scan_specific = diagnostics_dir / f"{scan_id}__manual_wechat_validation.json"
    if scan_specific.exists():
        return read_json(scan_specific)
    return read_json(diagnostics_dir / "manual_wechat_validation.json")


def same_window(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ["start", "end", "iso_year", "iso_week"]
    return all(left.get(key) == right.get(key) for key in keys if key in left or key in right)


def eligible_samples(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for team in coverage.get("teams", []):
        if team.get("coverage") not in {"covered", "partial"}:
            continue
        if team.get("text_access") not in {"full_text", "partial_text"}:
            continue
        if team.get("attribution_confidence") not in {"high", "med"}:
            continue
        source = next((item for item in team.get("sources", []) if item.get("source") in {"manual_wechat", "wechat_opencli"}), None)
        if not source:
            continue
        if source.get("adapter_mode") != "live":
            continue
        out.append(
            {
                "analyst_id": team.get("analyst_id"),
                "source": source.get("source"),
                "text_access": team.get("text_access"),
                "attribution_confidence": team.get("attribution_confidence"),
                "content_path": source.get("content_path"),
            }
        )
    return out


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Phase 2 Readiness",
        "",
        f"Ready: **{'yes' if result['ready'] else 'no'}**",
        "",
        f"scan_id: `{result.get('scan_id') or ''}`",
        "",
        "## Failed Reasons",
        "",
    ]
    if result["failed_reasons"]:
        for reason in result["failed_reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")

    validation = result["validation"]
    lines.extend(
        [
            "",
            "## Validation",
            "",
            "| metric | value |",
            "|---|---:|",
            f"| required | {'yes' if validation.get('required') else 'no'} |",
            f"| passed | {'yes' if validation.get('passed') else 'no'} |",
            f"| file_count | {validation.get('file_count')} |",
            f"| template_count | {validation.get('template_count')} |",
            f"| passed_teams | {validation.get('passed_teams')} |",
            f"| total_teams | {validation.get('total_teams')} |",
            "",
            "## Eligible Samples",
            "",
            "| analyst_id | source | text_access | attribution_confidence | content_path |",
            "|---|---|---|---|---|",
        ]
    )
    for sample in result["eligible_samples"]:
        lines.append(
            f"| {sample['analyst_id']} | {sample['source']} | {sample['text_access']} | {sample['attribution_confidence']} | {sample.get('content_path') or ''} |"
        )
    if not result["eligible_samples"]:
        lines.append("|  |  |  |  |  |")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether Phase 2 may start.")
    parser.add_argument(
        "--scan-dir",
        default="~/macro-strategy/scans/manual-2026-06-01-2026-06-07-v1",
    )
    parser.add_argument("--diagnostics-dir", default="~/macro-strategy/diagnostics")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
