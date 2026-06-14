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
from core.retrieval.source_matrix import load_source_matrix, render_source_matrix_review, source_matrix_review


def main() -> int:
    args = parse_args()
    teams = [team for team in load_analyst_list(args.analyst_list) if team["active"]]
    if args.max_teams:
        teams = teams[: args.max_teams]
    matrix = load_source_matrix(args.source_matrix)
    review = build_review(teams, matrix)
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(render_markdown(review))
    return 0


def build_review(teams: list[dict[str, Any]], matrix: dict[str, Any]) -> dict[str, Any]:
    return source_matrix_review(teams, matrix)


def render_markdown(review: dict[str, Any]) -> str:
    return render_source_matrix_review(review)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review analyst/source list before running retrieval search.")
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--source-whitelist", default="data/source_whitelist.yaml")
    parser.add_argument("--source-matrix", default="broker_wechat_matrix.md")
    parser.add_argument("--max-teams", type=int)
    parser.add_argument("--output-json")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
