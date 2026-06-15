#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    validation_cmd, coverage_cmd, readiness_cmd = build_commands(args)

    validation = run_step("manual_wechat validation", validation_cmd, repo_root)
    coverage = run_step("coverage check", coverage_cmd, repo_root)
    readiness = run_step("phase2 readiness", readiness_cmd, repo_root)

    print("")
    print("Phase 1 manual check outputs:")
    output_root = Path(args.output_root).expanduser()
    print(f"- {output_root / 'diagnostics' / 'manual_wechat_validation.md'}")
    print(f"- {output_root / 'scans' / f'manual-{args.start}-{args.end}-{args.run_version}' / 'coverage_report.md'}")
    print(f"- {output_root / 'diagnostics' / 'phase2_readiness.md'}")

    passed, reason = phase1_result(validation, coverage, readiness)
    if passed:
        print("phase1_manual_check=passed")
        return 0
    print("phase1_manual_check=failed")
    print(f"reason={reason}")
    return 1


def run_step(name: str, cmd: list[str], cwd: Path) -> int:
    print("")
    print(f"== {name} ==")
    completed = subprocess.run(cmd, cwd=cwd, text=True)
    print(f"{name}_exit_code={completed.returncode}")
    return completed.returncode


def phase1_result(validation: int, coverage: int, readiness: int) -> tuple[bool, str]:
    if validation != 0:
        return False, "manual_wechat validation failed"
    if coverage != 0:
        return False, "coverage command failed"
    if readiness != 0:
        return False, "phase2 readiness gate failed"
    return True, "ok"


def build_commands(args: argparse.Namespace) -> tuple[list[str], list[str], list[str]]:
    scan_id = f"manual-{args.start}-{args.end}-{args.run_version}"
    output_root = str(Path(args.output_root).expanduser())
    diagnostics_dir = str(Path(output_root) / "diagnostics")
    scan_dir = str(Path(output_root) / "scans" / scan_id)
    validation_cmd = [
        sys.executable,
        "scripts/validate_manual_wechat_articles.py",
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
        "--articles-root",
        args.articles_root,
        "--output-root",
        output_root,
    ]
    coverage_cmd = [
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
        coverage_cmd.extend(["--env-file", args.env_file])
    if getattr(args, "allow_single_wechat_provider", False):
        coverage_cmd.append("--allow-single-wechat-provider")
    if getattr(args, "allow_empty_wewe_feeds", False):
        coverage_cmd.append("--allow-empty-wewe-feeds")
    readiness_cmd = [
        sys.executable,
        "scripts/check_phase2_readiness.py",
        "--scan-dir",
        scan_dir,
        "--diagnostics-dir",
        diagnostics_dir,
    ]
    return validation_cmd, coverage_cmd, readiness_cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full Phase 1 manual_wechat check and P2 readiness gate.")
    parser.add_argument("--mode", choices=["manual"], default="manual")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--max-teams", type=int, default=3)
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--run-version", default="v1")
    parser.add_argument("--sources", default="manual_wechat,wechat_opencli,bocha,exa,web_search")
    parser.add_argument("--env-file", help="Optional env file with ir_search credentials.")
    parser.add_argument("--articles-root", default="~/macro-strategy/manual_wechat_articles")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--source-whitelist", default="data/source_whitelist.yaml")
    parser.add_argument("--source-matrix", default="broker_wechat_matrix.md")
    parser.add_argument("--allow-single-wechat-provider", action="store_true", help="Allow live WeChat retrieval when an account lacks dajiala or wewe config.")
    parser.add_argument("--allow-empty-wewe-feeds", action="store_true", help="Allow empty wewe feeds without dajiala fallback.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
