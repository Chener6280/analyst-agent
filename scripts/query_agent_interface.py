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

from core.history.timeseries import build_consensus_series, build_history_readiness, build_tag_rotation, build_team_series
from core.interface.read_api import (
    build_agent_handoff,
    get_dimension_summary,
    get_entity_mentions,
    get_entity_mentions_history,
    get_team_stance,
)


def main() -> int:
    args = parse_args()
    try:
        result = run_query(args)
    except ValueError as exc:
        print(f"query_failed={exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_query(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "scan-context":
        return build_agent_handoff(args.scan_id, output_root=args.output_root, db_path=args.db_path)
    if args.command == "dim-summary":
        return get_dimension_summary(args.scan_id, args.role, args.dim_key, db_path=args.db_path)
    if args.command == "team-stance":
        return get_team_stance(args.scan_id, args.analyst_id, db_path=args.db_path)
    if args.command == "who-mentioned":
        return get_entity_mentions(args.scan_id, args.entity, db_path=args.db_path)
    if args.command == "who-mentioned-history":
        return get_entity_mentions_history(args.entity, db_path=args.db_path, weeks=args.weeks)
    if args.command == "history-readiness":
        return build_history_readiness(args.scan_id, db_path=args.db_path, min_scans=args.min_scans)
    if args.command == "consensus-series":
        return build_consensus_series(args.role, args.dim_key, db_path=args.db_path, limit=args.limit)
    if args.command == "team-series":
        return build_team_series(args.analyst_id, args.dim_key, db_path=args.db_path, limit=args.limit)
    if args.command == "tag-rotation":
        return build_tag_rotation(args.role, args.dim_key, db_path=args.db_path, limit=args.limit, top_n=args.top_n)
    raise ValueError(f"unsupported command: {args.command}")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the local P5 analyst-views read interface.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_context = subparsers.add_parser("scan-context", help="Return handoff context for one scan.")
    add_common(scan_context)
    scan_context.add_argument("--output-root", default="~/macro-strategy")

    dim_summary = subparsers.add_parser("dim-summary", help="Return a dimension summary.")
    add_common(dim_summary)
    dim_summary.add_argument("--role", required=True, choices=["macro", "strategy"])
    dim_summary.add_argument("--dim-key", required=True)

    team_stance = subparsers.add_parser("team-stance", help="Return one team's stance rows and sources.")
    add_common(team_stance)
    team_stance.add_argument("--analyst-id", required=True)

    who_mentioned = subparsers.add_parser("who-mentioned", help="Return teams that mentioned one canonical entity.")
    add_common(who_mentioned)
    who_mentioned.add_argument("--entity", required=True)

    who_mentioned_history = subparsers.add_parser(
        "who-mentioned-history",
        help="Return recent scans where teams mentioned one canonical entity.",
    )
    who_mentioned_history.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    who_mentioned_history.add_argument("--entity", required=True)
    who_mentioned_history.add_argument("--weeks", type=int)

    history_readiness = subparsers.add_parser("history-readiness", help="Return P6 history readiness for one scan.")
    add_common(history_readiness)
    history_readiness.add_argument("--min-scans", type=int, default=4)

    consensus_series = subparsers.add_parser("consensus-series", help="Return per-scan consensus for an ordinal dimension.")
    consensus_series.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    consensus_series.add_argument("--role", required=True, choices=["macro", "strategy"])
    consensus_series.add_argument("--dim-key", required=True)
    consensus_series.add_argument("--limit", type=int)

    team_series = subparsers.add_parser("team-series", help="Return one team's per-scan stance series.")
    team_series.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    team_series.add_argument("--analyst-id", required=True)
    team_series.add_argument("--dim-key", required=True)
    team_series.add_argument("--limit", type=int)

    tag_rotation = subparsers.add_parser("tag-rotation", help="Return per-scan categorical tag rotation.")
    tag_rotation.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    tag_rotation.add_argument("--role", required=True, choices=["macro", "strategy"])
    tag_rotation.add_argument("--dim-key", required=True)
    tag_rotation.add_argument("--limit", type=int)
    tag_rotation.add_argument("--top-n", type=int, default=10)

    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
