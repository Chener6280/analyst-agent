#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.diagnostic_io import write_diagnostic_pair


def main() -> int:
    args = parse_args()
    scan_dir = Path(args.output_root).expanduser() / "scans" / args.scan_id
    diagnostics_dir = Path(args.output_root).expanduser() / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    result = build_acceptance(
        scan_dir,
        diagnostics_dir=diagnostics_dir,
        db_path=Path(args.db_path).expanduser(),
        min_teams=args.min_teams,
        min_extracted=args.min_extracted,
        quality_profile=args.quality_profile,
    )
    json_path, md_path, scan_json_path, scan_md_path = write_diagnostic_pair(
        diagnostics_dir,
        stem=acceptance_stem(args.quality_profile),
        scan_id=result.get("scan_id"),
        data=result,
        markdown=render_markdown(result),
    )

    print(f"mvp_acceptance={md_path}")
    print(f"json={json_path}")
    if scan_md_path:
        print(f"mvp_acceptance_scan={scan_md_path}")
    if scan_json_path:
        print(f"json_scan={scan_json_path}")
    print(f"passed={result['passed']}")
    return 0 if result["passed"] else 1


def build_acceptance(
    scan_dir: Path,
    *,
    diagnostics_dir: Path,
    db_path: Path,
    min_teams: int,
    min_extracted: int,
    quality_profile: str = "sample",
) -> dict[str, Any]:
    coverage = read_json(scan_dir / "coverage_summary.json")
    extraction = read_json(scan_dir / "extracted" / "extraction_summary.json")
    phase3 = read_json(diagnostics_dir / "phase3_readiness.json")
    stance_docs = load_stance_docs(scan_dir / "extracted")
    scan_id = coverage.get("scan_id") or scan_dir.name

    summary = coverage.get("summary", {})
    phase1_gate = summary.get("phase1_gate", {})
    extraction_quality = extraction.get("quality", {})
    db_counts = sqlite_counts(db_path, scan_id)
    schema_evidence = scan_stance_evidence(stance_docs)
    cross_section_path = scan_dir / "reports" / "weekly_cross_section.md"
    weekly_brief_path = scan_dir / "reports" / "weekly_brief.md"
    agent_handoff_path = scan_dir / "reports" / "agent_handoff.json"
    agent_handoff = read_json(agent_handoff_path)
    history_readiness_path = scan_dir / "reports" / "history_readiness.json"
    history_readiness = read_json(history_readiness_path)
    visual_pack_path = scan_dir / "reports" / "visual_pack.json"
    visual_pack = read_json(visual_pack_path)
    full_text_recovery_path = scan_dir / "reports" / "full_text_recovery_report.json"
    full_text_recovery = read_json(full_text_recovery_path)
    project_completion_path = scan_dir / "reports" / "project_package" / "project_completion.json"
    project_completion = read_json(project_completion_path)

    sample_metrics = [
        metric("coverage teams", min_teams, summary.get("total_teams"), (summary.get("total_teams") or 0) >= min_teams),
        metric("covered + partial rate", ">=60%", summary.get("covered_plus_partial_rate"), phase1_gate.get("covered_plus_partial_ge_60") is True),
        metric("full/partial text rate", ">=40%", summary.get("full_or_partial_text_rate") or summary.get("full_text_rate"), phase1_gate.get("full_or_partial_text_ge_40") is True),
        metric("high/med attribution rate", ">=70%", summary.get("high_or_med_attribution_rate"), phase1_gate.get("high_or_med_attribution_ge_70") is True),
        metric("mock_or_placeholder_count", 0, summary.get("mock_or_placeholder_count"), summary.get("mock_or_placeholder_count") == 0),
        metric("extracted samples", min_extracted, extraction.get("written_count"), (extraction.get("written_count") or 0) >= min_extracted),
        metric("non-null stance missing evidence", 0, schema_evidence["missing_evidence"], schema_evidence["missing_evidence"] == 0),
        metric("null/zero confusion candidates", 0, schema_evidence["null_zero_confusion"], schema_evidence["null_zero_confusion"] == 0),
        metric("phase3 readiness", True, phase3.get("ready"), phase3.get("ready") is True),
        metric("phase3 readiness scan_id", scan_id, phase3.get("scan_id"), phase3.get("scan_id") == scan_id),
        metric("sqlite stance rows", ">0", db_counts.get("stance"), (db_counts.get("stance") or 0) > 0),
        metric(
            "weekly_cross_section.md",
            "exists",
            "exists" if cross_section_path.exists() else "missing",
            cross_section_path.exists(),
        ),
        metric("weekly_brief.md", "exists", "exists" if weekly_brief_path.exists() else "missing", weekly_brief_path.exists()),
        metric(
            "agent_handoff.json",
            "exists",
            "exists" if agent_handoff_path.exists() else "missing",
            agent_handoff_path.exists(),
        ),
        metric(
            "agent_handoff status",
            "ready/review_required",
            agent_handoff.get("status"),
            agent_handoff.get("status") in {"ready", "review_required"},
        ),
        metric(
            "history_readiness.json",
            "exists",
            "exists" if history_readiness_path.exists() else "missing",
            history_readiness_path.exists(),
        ),
        metric(
            "history readiness status",
            "ready/insufficient_history",
            history_readiness.get("status"),
            history_readiness.get("status") in {"ready", "insufficient_history"},
        ),
        metric(
            "visual_pack.json",
            "exists",
            "exists" if visual_pack_path.exists() else "missing",
            visual_pack_path.exists(),
        ),
        metric("visual pack status", "ready", visual_pack.get("status"), visual_pack.get("status") == "ready"),
        metric(
            "full_text_recovery_report.json",
            "exists",
            "exists" if full_text_recovery_path.exists() else "missing",
            full_text_recovery_path.exists(),
        ),
        metric(
            "full-text recovery production flag",
            "false/true",
            full_text_recovery.get("production_ready"),
            full_text_recovery.get("production_ready") in {False, True},
        ),
        metric(
            "project_completion.json",
            "exists",
            "exists" if project_completion_path.exists() else "missing",
            project_completion_path.exists(),
        ),
        metric(
            "project package status",
            "ready/review_required",
            project_completion.get("status"),
            project_completion.get("status") in {"ready", "review_required"},
        ),
    ]
    production_metrics = build_production_metrics(summary, extraction_quality, history_readiness)
    metrics = sample_metrics if quality_profile == "sample" else production_metrics
    failed = [item for item in metrics if not item["passed"]]
    engineering_ready = not [item for item in sample_metrics if not item["passed"]]
    production_ready = not [item for item in production_metrics if not item["passed"]]
    return {
        "passed": not failed,
        "quality_profile": quality_profile,
        "engineering_ready": engineering_ready,
        "production_ready": production_ready,
        "scan_id": scan_id,
        "scan_dir": str(scan_dir),
        "db_path": str(db_path),
        "metrics": metrics,
        "failed_metrics": failed,
        "main_causes": main_causes(failed),
        "quality_warnings": build_quality_warnings(summary, extraction),
        "quality": {
            "full_text_rate": summary.get("full_text_rate"),
            "source_type_counts": summary.get("source_type_counts", {}),
            "documents_with_any_signal": extraction_quality.get("documents_with_any_signal"),
            "zero_signal_documents": extraction_quality.get("zero_signal_documents", []),
            "dimension_non_null_counts": extraction_quality.get("dimension_non_null_counts", {}),
            "categorical_selection_counts": extraction_quality.get("categorical_selection_counts", {}),
        },
        "db_counts": db_counts,
        "sample_metrics": sample_metrics,
        "production_metrics": production_metrics,
    }


def metric(name: str, required: Any, actual: Any, passed: bool) -> dict[str, Any]:
    return {"metric": name, "required": required, "actual": actual, "passed": passed}


def acceptance_stem(quality_profile: str) -> str:
    return "mvp_acceptance" if quality_profile == "sample" else f"mvp_acceptance_{quality_profile}"


def build_production_metrics(
    coverage_summary: dict[str, Any],
    extraction_quality: dict[str, Any],
    history_readiness: dict[str, Any],
) -> list[dict[str, Any]]:
    full_text_rate = parse_percent(coverage_summary.get("full_text_rate")) or 0.0
    production_coverage_rate = parse_percent(coverage_summary.get("production_coverage_rate")) or 0.0
    official_rate = parse_percent(coverage_summary.get("official_or_broker_source_rate")) or 0.0
    zero_signal = extraction_quality.get("zero_signal_documents") or []
    dim_counts = extraction_quality.get("dimension_non_null_counts") or {}
    macro_counts = dim_counts.get("macro") or {}
    non_null_core = sum(1 for key in ["growth", "inflation", "monetary", "fiscal", "overseas"] if int(macro_counts.get(key) or 0) > 0)
    return [
        metric("production_coverage_rate", ">=60%", coverage_summary.get("production_coverage_rate"), production_coverage_rate >= 0.60),
        metric("full_text_rate", ">=50%", coverage_summary.get("full_text_rate"), full_text_rate >= 0.50),
        metric("official_or_broker_source_rate", ">=70%", coverage_summary.get("official_or_broker_source_rate"), official_rate >= 0.70),
        metric("zero_signal_documents", "<=1", len(zero_signal), len(zero_signal) <= 1),
        metric("macro core ordinal non-null coverage", ">=50%", f"{non_null_core}/5", non_null_core / 5 >= 0.50),
        metric("mock_or_placeholder_count", 0, coverage_summary.get("mock_or_placeholder_count"), coverage_summary.get("mock_or_placeholder_count") == 0),
        metric("history readiness for trend", "ready", history_readiness.get("status"), history_readiness.get("status") == "ready"),
    ]


def main_causes(failed: list[dict[str, Any]]) -> list[str]:
    causes = []
    names = {item["metric"] for item in failed}
    if "coverage teams" in names:
        causes.append("Current run covers fewer teams than the global MVP threshold; add real eligible samples before claiming global MVP acceptance.")
    if "extracted samples" in names:
        causes.append("Current run extracts fewer stance samples than the global MVP threshold; do not fill this with mock data.")
    if any("rate" in name for name in names):
        causes.append("Coverage quality gates failed; inspect coverage_report.md and source diagnostics.")
    if "phase3 readiness" in names or "phase3 readiness scan_id" in names or "sqlite stance rows" in names or "weekly_cross_section.md" in names:
        causes.append("P3 artifact generation is incomplete; rerun ingest and aggregation.")
    if "weekly_brief.md" in names:
        causes.append("P4 brief generation is incomplete; rerun the weekly brief step after cross-section aggregation.")
    if "agent_handoff.json" in names or "agent_handoff status" in names:
        causes.append("P5 agent handoff generation is incomplete; rerun the handoff export step after weekly brief generation.")
    if "history_readiness.json" in names or "history readiness status" in names:
        causes.append("P6 history readiness generation is incomplete; rerun the history readiness step after handoff export.")
    if "visual_pack.json" in names or "visual pack status" in names:
        causes.append("P7 visual pack generation is incomplete; rerun the visual export step after history readiness.")
    if "full_text_recovery_report.json" in names or "full-text recovery production flag" in names:
        causes.append("Full-text recovery report generation is incomplete; rerun recovery export after weekly brief generation.")
    if "project_completion.json" in names or "project package status" in names:
        causes.append("Final project package generation is incomplete; rerun the project package export step after visual export.")
    return causes or ["No failed metrics."]


def build_quality_warnings(coverage_summary: dict[str, Any], extraction_summary: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    quality = extraction_summary.get("quality", {})
    written_count = int(extraction_summary.get("written_count") or 0)
    signal_count = int(quality.get("documents_with_any_signal") or 0)
    zero_signal = quality.get("zero_signal_documents") or []
    if written_count and signal_count < written_count:
        warnings.append(
            f"{written_count - signal_count} extracted documents have no stance signal: {', '.join(zero_signal)}."
        )

    full_text_rate = parse_percent(coverage_summary.get("full_text_rate"))
    if full_text_rate is not None and full_text_rate < 0.5:
        warnings.append(f"Full-text coverage is low ({coverage_summary.get('full_text_rate')}); most extraction relies on excerpts.")

    source_counts = coverage_summary.get("source_type_counts") or {}
    non_official = {
        key: value
        for key, value in source_counts.items()
        if key not in {"official_wechat", "unknown"} and int(value or 0) > 0
    }
    if non_official:
        warnings.append(f"Non-official source types are present: {format_count_map(non_official)}.")

    dim_counts = quality.get("dimension_non_null_counts") or {}
    empty_ordinal_dims: list[str] = []
    for role, counts in dim_counts.items():
        for dim_key, count in counts.items():
            if int(count or 0) == 0:
                empty_ordinal_dims.append(f"{role}.{dim_key}")
    if empty_ordinal_dims:
        warnings.append(f"No non-null ordinal stance was extracted for dimensions: {', '.join(empty_ordinal_dims)}.")

    categorical_counts = quality.get("categorical_selection_counts") or {}
    empty_categorical_dims: list[str] = []
    for role, counts in categorical_counts.items():
        for dim_key, count in counts.items():
            if int(count or 0) == 0:
                empty_categorical_dims.append(f"{role}.{dim_key}")
    if empty_categorical_dims:
        warnings.append(f"No categorical selections were extracted for dimensions: {', '.join(empty_categorical_dims)}.")

    return warnings


def parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text.endswith("%"):
        return None
    try:
        return float(text[:-1]) / 100
    except ValueError:
        return None


def format_count_map(counts: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def format_nested_count_map(counts: dict[str, dict[str, Any]]) -> str:
    parts = []
    for key, nested in counts.items():
        if not nested:
            continue
        parts.append(f"{key}({format_count_map(nested)})")
    return "; ".join(parts)


def load_stance_docs(extracted_dir: Path) -> list[dict[str, Any]]:
    if not extracted_dir.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(extracted_dir.glob("*.stance.json"))]


def scan_stance_evidence(docs: list[dict[str, Any]]) -> dict[str, int]:
    missing_evidence = 0
    null_zero_confusion = 0
    for doc in docs:
        for dim in doc.get("dimensions", {}).values():
            if dim.get("value") is None:
                if dim.get("label") is not None or dim.get("evidence_ref") or dim.get("verbatim") is not None:
                    null_zero_confusion += 1
            elif not dim.get("evidence_ref") or not dim.get("verbatim"):
                missing_evidence += 1
        for selection in doc.get("selections", []):
            if not selection.get("evidence_ref") or not selection.get("verbatim"):
                missing_evidence += 1
    return {"missing_evidence": missing_evidence, "null_zero_confusion": null_zero_confusion}


def sqlite_counts(db_path: Path, scan_id: str) -> dict[str, int | None]:
    tables = ["analyst", "scan", "stance", "stance_selection", "source", "intra_window_change"]
    if not db_path.exists():
        return {table: None for table in tables}
    conn = sqlite3.connect(db_path)
    try:
        counts: dict[str, int | None] = {}
        for table in tables:
            if table == "analyst":
                counts[table] = int(conn.execute("SELECT COUNT(*) FROM analyst").fetchone()[0])
            elif table == "scan":
                counts[table] = int(conn.execute("SELECT COUNT(*) FROM scan WHERE scan_id=?", (scan_id,)).fetchone()[0])
            else:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE scan_id=?", (scan_id,)).fetchone()[0])
        return counts
    finally:
        conn.close()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# MVP Acceptance",
        "",
        f"Passed: **{'yes' if result['passed'] else 'no'}**",
        f"Quality profile: `{result.get('quality_profile', 'sample')}`",
        f"Engineering ready: **{'yes' if result.get('engineering_ready') else 'no'}**",
        f"Production ready: **{'yes' if result.get('production_ready') else 'no'}**",
        "",
        "## Metrics",
        "",
        "| metric | required | actual | passed |",
        "|---|---:|---:|---:|",
    ]
    for item in result["metrics"]:
        lines.append(f"| {item['metric']} | {item['required']} | {item['actual']} | {'yes' if item['passed'] else 'no'} |")
    if result.get("quality_warnings"):
        lines.extend(["", "## Quality Warnings", ""])
        for warning in result["quality_warnings"]:
            lines.append(f"- {warning}")
    quality = result.get("quality") or {}
    if quality:
        lines.extend(["", "## Quality Snapshot", ""])
        lines.append(f"- full_text_rate: {quality.get('full_text_rate')}")
        lines.append(f"- documents_with_any_signal: {quality.get('documents_with_any_signal')}")
        zero_signal = quality.get("zero_signal_documents") or []
        lines.append(f"- zero_signal_documents: {', '.join(zero_signal) if zero_signal else 'none'}")
        lines.append(f"- source_type_counts: {format_count_map(quality.get('source_type_counts') or {}) or 'none'}")
        lines.append(f"- categorical_selection_counts: {format_nested_count_map(quality.get('categorical_selection_counts') or {}) or 'none'}")
    if result["failed_metrics"]:
        lines.extend(["", "## Main Causes", ""])
        for idx, cause in enumerate(result["main_causes"], start=1):
            lines.append(f"{idx}. {cause}")
        lines.extend(["", "## Recommendation", ""])
        lines.append("1. Keep the current P0-P8 pipeline as the local MVP proof.")
        lines.append("2. Add real covered/partial samples until the run has at least 10 teams and 5 extracted stance documents.")
        lines.append("3. Rerun Phase 1-8 and this acceptance gate; do not proceed to v3 until this report passes.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check global MVP acceptance criteria.")
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    parser.add_argument("--min-teams", type=int, default=10)
    parser.add_argument("--min-extracted", type=int, default=5)
    parser.add_argument("--quality-profile", choices=["sample", "production"], default="sample")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
