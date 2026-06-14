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

from core.retrieval.extract import is_eligible_team
from core.retrieval.manual_wechat import parse_manual_wechat_article
from core.schema.stance import validate_stance_document
from scripts.diagnostic_io import write_diagnostic_pair


def main() -> int:
    args = parse_args()
    scan_dir = Path(args.scan_dir).expanduser()
    diagnostics_dir = Path(args.diagnostics_dir).expanduser()
    result = build_readiness(scan_dir)

    json_path, md_path, scan_json_path, scan_md_path = write_diagnostic_pair(
        diagnostics_dir,
        stem="phase3_readiness",
        scan_id=result.get("scan_id"),
        data=result,
        markdown=render_markdown(result),
    )

    print(f"phase3_readiness={md_path}")
    print(f"json={json_path}")
    if scan_md_path:
        print(f"phase3_readiness_scan={scan_md_path}")
    if scan_json_path:
        print(f"json_scan={scan_json_path}")
    print(f"ready={result['ready']}")
    return 0 if result["ready"] else 1


def build_readiness(scan_dir: Path) -> dict[str, Any]:
    coverage = read_json(scan_dir / "coverage_summary.json")
    extraction_summary = read_json(scan_dir / "extracted" / "extraction_summary.json")
    scan_id = coverage.get("scan_id")
    teams = coverage.get("teams", [])
    eligible = [team for team in teams if is_eligible_team(team)]
    docs = load_stance_docs(scan_dir / "extracted")
    doc_by_analyst = {doc.get("analyst_id"): doc for doc in docs}

    failures: list[dict[str, Any]] = []
    global_errors: list[str] = []
    if extraction_summary.get("scan_id") != scan_id:
        global_errors.append("extraction_summary scan_id does not match coverage scan_id")
    doc_scan_mismatches = [doc.get("analyst_id") or "<unknown>" for doc in docs if doc.get("scan_id") != scan_id]
    if doc_scan_mismatches:
        global_errors.append(f"stance JSON scan_id mismatch: {', '.join(doc_scan_mismatches)}")
    duplicate_analysts = duplicate_values([doc.get("analyst_id") for doc in docs])
    if duplicate_analysts:
        global_errors.append(f"duplicate stance JSON analyst_id: {', '.join(duplicate_analysts)}")

    for team in eligible:
        analyst_id = team.get("analyst_id")
        doc = doc_by_analyst.get(analyst_id)
        if not doc:
            failures.append({"analyst_id": analyst_id, "errors": ["missing stance JSON"]})
            continue
        source_texts = source_texts_for_team(team)
        errors = validate_stance_document(doc, source_texts=source_texts)
        if errors:
            failures.append({"analyst_id": analyst_id, "errors": errors})

    missing_docs = [team.get("analyst_id") for team in eligible if team.get("analyst_id") not in doc_by_analyst]
    extra_docs = [doc.get("analyst_id") for doc in docs if doc.get("analyst_id") not in {team.get("analyst_id") for team in eligible}]
    schema_error_count = sum(len(item["errors"]) for item in failures)
    evidence_error_count = sum(
        1 for item in failures for error in item["errors"] if "evidence_ref" in error or "verbatim" in error
    )

    ready = (
        bool(eligible)
        and extraction_summary.get("passed") is True
        and not global_errors
        and len(docs) == len(eligible)
        and not missing_docs
        and not extra_docs
        and not failures
    )
    return {
        "ready": ready,
        "scan_id": scan_id,
        "eligible_count": len(eligible),
        "stance_doc_count": len(docs),
        "extraction_summary_passed": extraction_summary.get("passed"),
        "extraction_summary_scan_id": extraction_summary.get("scan_id"),
        "global_errors": global_errors,
        "schema_error_count": schema_error_count,
        "evidence_error_count": evidence_error_count,
        "missing_docs": missing_docs,
        "extra_docs": extra_docs,
        "failures": failures,
    }


def load_stance_docs(extracted_dir: Path) -> list[dict[str, Any]]:
    if not extracted_dir.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(extracted_dir.glob("*.stance.json"))]


def duplicate_values(values: list[Any]) -> list[str]:
    seen: set[Any] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(str(value))
        seen.add(value)
    return sorted(duplicates)


def source_texts_for_team(team: dict[str, Any]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for source in team.get("sources", []):
        content_path = source.get("content_path")
        source_id = source.get("id")
        if not content_path or not source_id:
            continue
        try:
            texts[source_id] = parse_manual_wechat_article(content_path)["body"]
        except ValueError:
            continue
    return texts


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Phase 3 Readiness",
        "",
        f"Ready: **{'yes' if result['ready'] else 'no'}**",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| eligible_count | {result['eligible_count']} |",
        f"| stance_doc_count | {result['stance_doc_count']} |",
        f"| extraction_summary_passed | {'yes' if result.get('extraction_summary_passed') else 'no'} |",
        f"| extraction_summary_scan_id | {result.get('extraction_summary_scan_id') or ''} |",
        f"| schema_error_count | {result['schema_error_count']} |",
        f"| evidence_error_count | {result['evidence_error_count']} |",
        "",
        "## Global Errors",
        "",
    ]
    if not result.get("global_errors"):
        lines.append("- none")
    else:
        for error in result["global_errors"]:
            lines.append(f"- {error}")
    lines.extend(
        [
        "",
        "## Failures",
        "",
        ]
    )
    if not result["failures"]:
        lines.append("- none")
    else:
        for failure in result["failures"]:
            lines.append(f"- {failure['analyst_id']}: {'; '.join(failure['errors'])}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether Phase 3 may start after stance extraction.")
    parser.add_argument("--scan-dir", default="~/macro-strategy/scans/manual-2026-06-01-2026-06-07-v1")
    parser.add_argument("--diagnostics-dir", default="~/macro-strategy/diagnostics")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
