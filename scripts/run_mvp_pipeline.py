#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import make_scan_id, resolve_window


def main() -> int:
    args = parse_args()
    steps = build_steps(args)

    failed_steps: list[tuple[list[str], int]] = []
    for step in steps:
        print("")
        print(f"== {' '.join(step[1:])} ==")
        completed = subprocess.run(step, cwd=REPO_ROOT, text=True)
        print(f"exit_code={completed.returncode}")
        if completed.returncode != 0:
            if step[1] == "scripts/check_mvp_acceptance.py":
                failed_steps.append((step, completed.returncode))
                print("mvp_acceptance=failed_but_continuing_to_package")
                continue
            if step[1] == "scripts/check_extract_accuracy.py":
                failed_steps.append((step, completed.returncode))
                print("extract_accuracy=failed_but_continuing")
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
    window = resolve_window(args.mode, args.start, args.end)
    scan_id = make_scan_id(window, args.mode, args.run_version)
    output_root = str(Path(args.output_root).expanduser())
    scan_dir = str(Path(output_root) / "scans" / scan_id)
    diagnostics_dir = str(Path(output_root) / "diagnostics")
    phase1_steps = build_phase1_steps(args, output_root, scan_dir, diagnostics_dir)
    return [
        *phase1_steps,
        [sys.executable, "scripts/run_extract_mvp.py", "--scan-id", scan_id, "--output-root", output_root],
        [
            sys.executable,
            "scripts/check_extract_accuracy.py",
            "--gold",
            getattr(args, "gold", None) or "tests/gold/extraction_gold.jsonl",
            "--diagnostics-dir",
            diagnostics_dir,
            "--min-accuracy",
            str(getattr(args, "min_accuracy", 0.9)),
        ],
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
            "scripts/export_project_package.py",
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
            "scripts/generate_weekly_brief.py",
            "--scan-id",
            scan_id,
            "--output-root",
            output_root,
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
        args.mode,
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
    if args.allow_single_wechat_provider:
        coverage_step.append("--allow-single-wechat-provider")
    if args.allow_empty_wewe_feeds:
        coverage_step.append("--allow-empty-wewe-feeds")
    steps = []
    if should_check_wechat_dual_source(args):
        steps.append(
            [
                sys.executable,
                "scripts/ensure_wechat_dual_source_accounts.py",
                "--accounts",
                args.wechat_accounts,
                "--analyst-list",
                args.analyst_list,
                "--source-matrix",
                args.source_matrix,
                "--fail-on-missing",
            ]
        )
    if should_prepare_wewe(args):
        prepare_step = [
            sys.executable,
            "scripts/prepare_wewe_login.py",
            "--base-url",
            args.wewe_base,
            "--container",
            args.wewe_container,
            "--auth-code",
            args.wewe_auth_code,
            "--accounts",
            args.wechat_accounts,
            "--wait-seconds",
            str(args.wewe_login_wait_seconds),
        ]
        steps.append(prepare_step)
    return [
        *steps,
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


def should_prepare_wewe(args: argparse.Namespace) -> bool:
    if getattr(args, "skip_wewe_login_prepare", False):
        return False
    if args.retrieval_profile != "live":
        return False
    return "wechat_opencli" in [item.strip() for item in str(args.sources or "").split(",")]


def should_check_wechat_dual_source(args: argparse.Namespace) -> bool:
    if getattr(args, "skip_wechat_dual_source_check", False):
        return False
    if getattr(args, "allow_single_wechat_provider", False):
        return False
    if args.retrieval_profile != "live":
        return False
    return "wechat_opencli" in [item.strip() for item in str(args.sources or "").split(",")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1-8 MVP pipeline with gates.")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--mode", choices=["manual", "weekly"], default="manual")
    parser.add_argument("--run-version", default="v1")
    parser.add_argument("--max-teams", type=int, default=3)
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--retrieval-profile", choices=["manual", "live"], default="manual")
    parser.add_argument("--sources", default="manual_wechat,wechat_opencli,bocha,exa,web_search")
    parser.add_argument("--min-teams", type=int, default=10)
    parser.add_argument("--min-extracted", type=int, default=5)
    parser.add_argument("--quality-profile", choices=["sample", "production", "production_trend"], default="sample")
    parser.add_argument("--env-file")
    parser.add_argument("--articles-root", default="~/macro-strategy/manual_wechat_articles")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    parser.add_argument("--source-whitelist", default="data/source_whitelist.yaml")
    parser.add_argument("--source-matrix", default="broker_wechat_matrix.md")
    parser.add_argument("--skip-wewe-login-prepare", action="store_true", help="Skip local wewe-rss startup/login probe before live WeChat retrieval.")
    parser.add_argument("--skip-wechat-dual-source-check", action="store_true", help="Skip the fast dajiala+wewe account config check before live retrieval.")
    parser.add_argument("--allow-single-wechat-provider", action="store_true", help="Allow live retrieval when a searched account lacks dajiala or wewe configuration.")
    parser.add_argument("--allow-empty-wewe-feeds", action="store_true", help="Allow live retrieval to proceed even when a configured wewe feed is empty and has no dajiala fallback.")
    parser.add_argument("--wewe-base", default=os.environ.get("WEWE_RSS_BASE", "http://localhost:4001"))
    parser.add_argument("--wewe-container", default=os.environ.get("WEWE_RSS_CONTAINER", "wewe-rss-ir"))
    parser.add_argument("--wewe-auth-code", default=os.environ.get("WEWE_AUTH_CODE", "irsearch"))
    parser.add_argument("--wewe-login-wait-seconds", type=int, default=0)
    parser.add_argument("--wechat-accounts", default=os.environ.get("WECHAT_ACCOUNTS_PATH", "/Users/chen/Documents/ir_search/accounts.json"))
    parser.add_argument("--gold", default=os.environ.get("EXTRACTION_GOLD_PATH", "tests/gold/extraction_gold.jsonl"), help="Gold file for the extraction accuracy gate. Point at the human-labeled private gold for production; defaults to EXTRACTION_GOLD_PATH or the committed seed file.")
    parser.add_argument("--min-accuracy", type=float, default=0.9)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
