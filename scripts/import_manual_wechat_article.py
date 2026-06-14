#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_analyst_list


def main() -> int:
    args = parse_args()
    team = find_team(args.analyst_id, args.analyst_list)
    body = read_body(args)
    if not body.strip():
        raise SystemExit("body is empty; refusing to create manual_wechat article")

    week_dir = Path(args.output_dir).expanduser()
    week_dir.mkdir(parents=True, exist_ok=True)
    member = team["team_members"][0] if team["team_members"] else team["institution"]
    path = week_dir / args.filename if args.filename else week_dir / default_filename(team, member, args.published_at)
    if path.exists() and not args.overwrite:
        raise SystemExit(f"file already exists: {path}")

    account = args.account_name or (team["official_accounts"][0] if team["official_accounts"] else "")
    text = render_article(
        title=args.title,
        url=args.url,
        published_at=args.published_at,
        account_name=account,
        institution=team["institution"],
        role=team["role"],
        analyst_id=team["analyst_id"],
        team_members=team["team_members"],
        body=body,
        source_note=args.source_note,
        source_type=args.source_type,
    )
    path.write_text(text, encoding="utf-8")
    print(f"written={path}")
    print(f"body_chars={len(body.strip())}")
    print(f"analyst_id={team['analyst_id']}")
    return 0


def find_team(analyst_id: str, analyst_list: str) -> dict:
    teams = load_analyst_list(analyst_list)
    for team in teams:
        if team["analyst_id"] == analyst_id:
            return team
    raise SystemExit(f"analyst_id not found in {analyst_list}: {analyst_id}")


def read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).expanduser().read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("provide --body-file or pipe article body via stdin")


def default_filename(team: dict, member: str, published_at: str) -> str:
    safe_date = published_at[:10]
    return f"{team['institution']}_{team['role']}_{member}_{safe_date}.md"


def render_article(
    *,
    title: str,
    url: str,
    published_at: str,
    account_name: str,
    institution: str,
    role: str,
    analyst_id: str,
    team_members: list[str],
    body: str,
    source_note: str | None,
    source_type: str | None,
) -> str:
    lines = [
        "---",
        f'title: "{escape_yaml_string(title)}"',
        f'url: "{escape_yaml_string(url)}"',
        f'published_at: "{escape_yaml_string(published_at)}"',
        f'account_name: "{escape_yaml_string(account_name)}"',
        f'institution: "{escape_yaml_string(institution)}"',
        f'role: "{escape_yaml_string(role)}"',
        f'analyst_id: "{escape_yaml_string(analyst_id)}"',
        "team_members:",
    ]
    for member in team_members:
        lines.append(f'  - "{escape_yaml_string(member)}"')
    if source_note:
        lines.append(f'source_note: "{escape_yaml_string(source_note)}"')
    if source_type:
        lines.append(f'source_type: "{escape_yaml_string(source_type)}"')
    lines.extend(["---", "", body.strip(), ""])
    return "\n".join(lines)


def escape_yaml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create one real manual_wechat Markdown article from stdin or a body file.")
    parser.add_argument("--analyst-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--account-name")
    parser.add_argument("--body-file")
    parser.add_argument("--filename")
    parser.add_argument("--source-note")
    parser.add_argument(
        "--source-type",
        choices=["official_wechat", "broker_website", "research_platform", "financial_media", "aggregator", "unknown"],
    )
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--output-dir", default="~/macro-strategy/manual_wechat_articles/2026-W23")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
