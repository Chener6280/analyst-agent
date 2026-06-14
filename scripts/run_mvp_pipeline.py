#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    steps = build_steps(args)

    failed_steps: list[tuple[list[str], int]] = []
    for step in steps:
        print("")
        print(f"== {' '.join(step[1:])} ==")
        completed = subprocess.run(step, cwd=repo_root, text=True)
        print(f"exit_code={completed.returncode}")
        if completed.returncode != 0:
            if step[1] == "scripts/check_mvp_acceptance.py":
                failed_steps.append((step, completed.returncode))
                print("mvp_acceptance=failed_but_continuing_to_package")
                continue
            print("mvp_pipeline=failed")
            print(f"failed_step={step[1]}")
            return completed.returncode

    if failed_steps:
        print("")
        print("mvp_pipeline=failed")
        print(f"failed_step={failed_steps[0][0][1]}")
        return failed_steps[0][1]

    print("")
    print("mvp_pipeline=passed")
    return 0


def build_steps(args: argparse.Namespace) -> list[list[str]]:
    scan_id = f"manual-{args.start}-{args.end}-{args.run_version}"
    output_root = str(Path(args.output_root).expanduser())
    scan_dir = str(Path(output_root) / "scans" / scan_id)
    diagnostics_dir = str(Path(output_root) / "diagnostics")
    phase1_steps = build_phase1_steps(args, output_root, scan_dir, diagnostics_dir)
    return [
        *phase1_steps,
        [sys.executable, "scripts/run_extract_mvp.py", "--scan-id", scan_id, "--output-root", output_root],
        [
            sys.executable,
            "scripts/check_phase3_readiness.py",
            "--scan-dir",
            scan_dir,
            "--diagnostics-dir",
            diagnostics_dir,
        ],
        [
            sys.executable,
            "scripts/ingest_sqlite.py",
            "--scan-id",
            scan_id,
            "--analyst-list",
            args.analyst_list,
            "--output-root",
            output_root,
            "--db-path",
            args.db_path,
        ],
        [
            sys.executable,
            "scripts/aggregate_cross_section.py",
            "--scan-id",
            scan_id,
            "--output",
            "markdown",
            "--output-root",
            output_root,
            "--db-path",
            args.db_path,
        ],
        [
            sys.executable,
            "scripts/generate_weekly_brief.py",
            "--scan-id",
            scan_id,
            "--output-root",
            output_root,
        ],
        [
            sys.executable,
            "scripts/export_full_text_recovery_report.py",
            "--scan-id",
            scan_id,
            "--output-root",
            output_root,
            "--analyst-list",
            args.analyst_list,
            "--source-whitelist",
            args.source_whitelist,
        ],
        [
            sys.executable,
            "scripts/export_agent_handoff.py",
            "--scan-id",
            scan_id,
            "--output-root",
            output_root,
            "--db-path",
            args.db_path,
        ],
        [
            sys.executable,
            "scripts/export_history_readiness.py",
            "--scan-id",
            scan_id,
            "--output-root",
            output_root,
            "--db-path",
            args.db_path,
        ],
        [
            sys.executable,
            "scripts/export_visual_pack.py",
            "--scan-id",
            scan_id,
            "--output-root",
            output_root,
            "--db-path",
            args.db_path,
        ],
        [
            sys.executable,
            "scripts/check_mvp_acceptance.py",
            "--scan-id",
            scan_id,
            "--min-teams",
            str(args.min_teams),
            "--min-extracted",
            str(args.min_extracted),
            "--output-root",
            output_root,
            "--db-path",
            args.db_path,
            "--quality-profile",
            args.quality_profile,
        ],
        [
            sys.executable,
            "scripts/export_project_package.py",
            "--scan-id",
            scan_id,
            "--output-root",
            output_root,
            "--db-path",
            args.db_path,
        ],
    ]


def build_phase1_steps(args: argparse.Namespace, output_root: str, scan_dir: str, diagnostics_dir: str) -> list[list[str]]:
    if args.retrieval_profile == "manual":
        step = [
            sys.executable,
            "scripts/run_phase1_manual_check.py",
            "--start",
            args.start,
            "--end",
            args.end,
            "--max-teams",
            str(args.max_teams),
            "--analyst-list",
            args.analyst_list,
            "--run-version",
            args.run_version,
            "--articles-root",
            args.articles_root,
            "--output-root",
            output_root,
            "--source-whitelist",
            args.source_whitelist,
            "--source-matrix",
            args.source_matrix,
        ]
        if args.env_file:
            step.extend(["--env-file", args.env_file])
        return [step]

    coverage_step = [
        sys.executable,
        "scripts/run_coverage_check.py",
        "--mode",
        "manual",
        "--start",
        args.start,
        "--end",
        args.end,
        "--max-teams",
        str(args.max_teams),
        "--analyst-list",
        args.analyst_list,
        "--run-version",
        args.run_version,
        "--sources",
        args.sources,
        "--output-root",
        output_root,
        "--source-list-confirmed",
        "--source-whitelist",
        args.source_whitelist,
        "--source-matrix",
        args.source_matrix,
    ]
    if args.env_file:
        coverage_step.extend(["--env-file", args.env_file])
    return [
        coverage_step,
        [
            sys.executable,
            "scripts/check_phase2_readiness.py",
            "--scan-dir",
            scan_dir,
            "--diagnostics-dir",
            diagnostics_dir,
        ],
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1-8 MVP pipeline with gates.")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--run-version", default="v1")
    parser.add_argument("--max-teams", type=int, default=3)
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--retrieval-profile", choices=["manual", "live"], default="manual")
    parser.add_argument("--sources", default="manual_wechat,wechat_opencli,bocha,exa,web_search")
    parser.add_argument("--min-teams", type=int, default=10)
    parser.add_argument("--min-extracted", type=int, default=5)
    parser.add_argument("--quality-profile", choices=["sample", "production"], default="sample")
    parser.add_argument("--env-file")
    parser.add_argument("--articles-root", default="~/macro-strategy/manual_wechat_articles")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    parser.add_argument("--source-whitelist", default="data/source_whitelist.yaml")
    parser.add_argument("--source-matrix", default="broker_wechat_matrix.md")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
