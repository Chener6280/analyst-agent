#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_analyst_list, make_scan_id, resolve_window
from core.retrieval.coverage import (
    assess_team_coverage,
    summarize_coverages,
    write_coverage_report,
    write_source_link_inventory,
    write_team_cache,
)
from core.retrieval.source_matrix import (
    enrich_teams_with_source_matrix,
    load_source_matrix,
    render_source_matrix_review,
    source_matrix_review,
)
from core.retrieval.wechat_provider_preflight import build_wechat_provider_preflight, write_wechat_provider_preflight
from scripts._env_utils import load_env_file


def main() -> int:
    args = parse_args()
    env_file = load_env_file(args.env_file)
    os.environ.setdefault("IR_SEARCH_LIVE", "1")
    window = resolve_window(args.mode, args.start, args.end, args.tz)
    scan_id = make_scan_id(window, args.mode, args.run_version)
    output_dir = Path(args.output_root).expanduser() / "scans" / scan_id
    output_dir.mkdir(parents=True, exist_ok=True)

    teams = [team for team in load_analyst_list(args.analyst_list) if team["active"]]
    if args.max_teams:
        teams = teams[: args.max_teams]

    matrix = load_source_matrix(args.source_matrix)
    if args.preflight_only or not args.source_list_confirmed:
        review = source_matrix_review(teams, matrix)
        review_path = output_dir / "source_list_review.md"
        review_json_path = output_dir / "source_list_review.json"
        review_path.write_text(render_source_matrix_review(review), encoding="utf-8")
        review_json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"source_list_review={review_path}")
        print(f"json={review_json_path}")
        if args.preflight_only:
            print("preflight_only=done")
            return 0
        print("source_list_confirmation_required=true")
        print("rerun_with=--source-list-confirmed")
        return 2

    config = {
        "scan_id": scan_id,
        "mode": args.mode,
        "window": {key: window[key] for key in ["start", "end", "iso_year", "iso_week", "timezone"]},
        "run_version": args.run_version,
        "analyst_list": str(Path(args.analyst_list).resolve()),
        "source_matrix": str(Path(args.source_matrix).expanduser()),
        "max_teams": args.max_teams,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "env_file_loaded": str(env_file) if env_file else None,
    }
    (output_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    purge_search_cache(output_dir)
    teams = enrich_teams_with_source_matrix(teams, matrix)
    parsed_sources = parse_sources(args.sources)
    if should_run_wechat_provider_preflight(parsed_sources, args.skip_wechat_provider_preflight):
        provider_preflight = build_wechat_provider_preflight(
            teams,
            window,
            accounts_path=args.wechat_accounts,
            wewe_base=args.wewe_base,
            timeout=args.wechat_provider_timeout,
            dajiala_max_pages=args.dajiala_max_pages,
        )
        provider_paths = write_wechat_provider_preflight(provider_preflight, output_dir)
        print(f"wechat_provider_preflight={provider_paths['md']}")
        print(f"wechat_provider_preflight_json={provider_paths['json']}")
        if args.strict_wechat_provider_preflight and provider_preflight["summary"]["team_not_ready"]:
            print("wechat_provider_preflight=strict_failed")
            return 2

    coverages: list[dict[str, Any]] = []
    for idx, team in enumerate(teams, start=1):
        coverage = assess_team_coverage(team, window, scan_id, args.mode, sources=parsed_sources)
        write_team_cache(coverage, output_dir, idx)
        coverages.append(coverage)

    summary = summarize_coverages(coverages)
    (output_dir / "coverage_summary.json").write_text(
        json.dumps({"scan_id": scan_id, "summary": summary, "teams": coverages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_coverage_report(scan_id, coverages, output_dir / "coverage_report.md")
    source_links = write_source_link_inventory(scan_id, coverages, output_dir)

    print(f"scan_id={scan_id}")
    print(f"output_dir={output_dir}")
    print(f"coverage_report={output_dir / 'coverage_report.md'}")
    print(f"source_links_md={source_links['md']}")
    print(f"source_links_csv={source_links['csv']}")
    print(f"source_links_json={source_links['json']}")
    print(f"phase1_gate={json.dumps(summary['phase1_gate'], ensure_ascii=False, sort_keys=True)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run analyst-view retrieval coverage check.")
    parser.add_argument("--mode", choices=["weekly", "manual"], required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--tz", default="Asia/Shanghai")
    parser.add_argument("--run-version", default="v1")
    parser.add_argument("--max-teams", type=int)
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--sources", help="Comma-separated source order, e.g. manual_wechat,wechat_opencli,bocha,exa,web_search")
    parser.add_argument("--env-file", help="Optional env file with ir_search credentials.")
    parser.add_argument("--source-whitelist", default="data/source_whitelist.yaml")
    parser.add_argument("--source-matrix", default="broker_wechat_matrix.md")
    parser.add_argument("--preflight-only", action="store_true", help="Only write source-list review; do not run retrieval.")
    parser.add_argument("--source-list-confirmed", action="store_true", help="Confirm analyst/source list review before retrieval.")
    parser.add_argument("--skip-wechat-provider-preflight", action="store_true", help="Skip dajiala/wewe provider checks before retrieval.")
    parser.add_argument("--strict-wechat-provider-preflight", action="store_true", help="Fail before retrieval if any official account has no dajiala/wewe window articles.")
    parser.add_argument("--wechat-accounts", help="Path to ir_search accounts.json for dajiala/wewe preflight.")
    parser.add_argument("--wewe-base", help="Override WEWE_RSS_BASE for provider preflight.")
    parser.add_argument("--wechat-provider-timeout", type=int, default=8)
    parser.add_argument("--dajiala-max-pages", type=int, default=1)
    return parser.parse_args()


def parse_sources(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def should_run_wechat_provider_preflight(sources: list[str] | None, skip: bool) -> bool:
    if skip:
        return False
    selected = sources or ["manual_wechat", "wechat_opencli"]
    return "wechat_opencli" in selected


def purge_search_cache(output_dir: Path) -> None:
    cache_dir = output_dir / "search_cache"
    if not cache_dir.exists():
        return
    for pattern in ["*.json", "*.md"]:
        for path in cache_dir.glob(pattern):
            if path.is_file():
                path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
