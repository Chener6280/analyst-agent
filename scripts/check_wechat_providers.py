#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_analyst_list, resolve_window
from core.retrieval.source_matrix import enrich_teams_with_source_matrix, load_source_matrix
from core.retrieval.wechat_provider_preflight import build_wechat_provider_preflight, write_wechat_provider_preflight
from scripts._env_utils import load_env_file


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    window = resolve_window(args.mode, args.start, args.end, args.tz)
    teams = [team for team in load_analyst_list(args.analyst_list) if team["active"]]
    if args.max_teams:
        teams = teams[: args.max_teams]
    matrix = load_source_matrix(args.source_matrix)
    teams = enrich_teams_with_source_matrix(teams, matrix)
    data = build_wechat_provider_preflight(
        teams,
        window,
        accounts_path=args.accounts,
        wewe_base=args.wewe_base,
        timeout=args.timeout,
        dajiala_max_pages=args.dajiala_max_pages,
    )
    output_dir = Path(args.output_root).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = write_wechat_provider_preflight(data, output_dir)
    print(f"wechat_provider_preflight={paths['md']}")
    print(f"json={paths['json']}")
    print(f"team_ready={data['summary']['team_ready']}/{data['summary']['teams']}")
    print(f"account_ready={data['summary']['ready']}/{data['summary']['accounts']}")
    return 0 if not args.strict or data["summary"]["team_not_ready"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check dajiala and wewe provider readiness before WeChat retrieval.")
    parser.add_argument("--mode", choices=["weekly", "manual"], default="manual")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--tz", default="Asia/Shanghai")
    parser.add_argument("--max-teams", type=int)
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--source-matrix", default="broker_wechat_matrix.md")
    parser.add_argument("--env-file")
    parser.add_argument("--accounts", help="Path to ir_search accounts.json. Defaults to WECHAT_OPENCLI_COMMAND --accounts or IR_SEARCH_PATH/accounts.json.")
    parser.add_argument("--wewe-base", help="Override WEWE_RSS_BASE.")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--dajiala-max-pages", type=int, default=1)
    parser.add_argument("--output-root", default="~/macro-strategy/provider_preflight")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any account has no window articles in dajiala or wewe.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
