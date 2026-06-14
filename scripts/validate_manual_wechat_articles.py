#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_analyst_list, make_scan_id, resolve_window
from core.retrieval.manual_wechat import (
    article_matches_team,
    attribution_confidence,
    classify_manual_text_access,
    infer_source_completeness,
    in_window,
    iter_article_files,
    parse_manual_wechat_article,
)
from scripts.diagnostic_io import write_diagnostic_pair


def main() -> int:
    args = parse_args()
    window = resolve_window(args.mode, args.start, args.end, args.tz)
    scan_id = make_scan_id(window, args.mode, args.run_version)
    teams = [team for team in load_analyst_list(args.analyst_list) if team["active"]]
    if args.max_teams:
        teams = teams[: args.max_teams]

    result = validate_articles(teams, window, Path(args.articles_root).expanduser(), scan_id=scan_id)
    output_dir = Path(args.output_root).expanduser() / "diagnostics"
    json_path, md_path, scan_json_path, scan_md_path = write_diagnostic_pair(
        output_dir,
        stem="manual_wechat_validation",
        scan_id=scan_id,
        data=result,
        markdown=render_markdown(result),
    )

    print(f"manual_wechat_validation={md_path}")
    print(f"json={json_path}")
    if scan_md_path:
        print(f"manual_wechat_validation_scan={scan_md_path}")
    if scan_json_path:
        print(f"json_scan={scan_json_path}")
    print(f"passed={result['passed']}")
    return 0 if result["passed"] else 1


def validate_articles(teams: list[dict[str, Any]], window: dict[str, Any], root: Path, *, scan_id: str | None = None) -> dict[str, Any]:
    week_dir = root / f"{window['iso_year']}-W{int(window['iso_week']):02d}"
    files = iter_article_files(week_dir) if week_dir.exists() else []
    template_files = sorted(week_dir.glob("*.md.template")) if week_dir.exists() else []
    parsed = [parse_file(path) for path in files]

    team_results = []
    for team in teams:
        team_results.append(validate_team(team, window, parsed))

    passed_teams = sum(1 for item in team_results if item["status"] in {"covered", "partial"})
    return {
        "scan_id": scan_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "window": {key: window[key] for key in ["start", "end", "iso_year", "iso_week"]},
        "articles_root": str(root),
        "week_dir": str(week_dir),
        "week_dir_exists": week_dir.exists(),
        "file_count": len(files),
        "template_count": len(template_files),
        "template_files": [str(path) for path in template_files],
        "total_teams": len(teams),
        "passed_teams": passed_teams,
        "passed": passed_teams == len(teams) and len(teams) > 0,
        "teams": team_results,
    }


def parse_file(path: Path) -> dict[str, Any]:
    try:
        article = parse_manual_wechat_article(path)
        return {"path": str(path), "ok": True, "article": article, "error": None}
    except ValueError as exc:
        return {"path": str(path), "ok": False, "article": None, "error": str(exc)}


def validate_team(team: dict[str, Any], window: dict[str, Any], parsed_files: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    issues = []

    for parsed in parsed_files:
        if not parsed["ok"]:
            issues.append(f"{Path(parsed['path']).name}: {parsed['error']}")
            continue
        article = parsed["article"]
        meta = article["metadata"]
        body = article["body"]
        team_match = article_matches_team(article, team)
        date_ok = False
        date_error = None
        try:
            date_ok = in_window(meta["published_at"], window)
        except ValueError as exc:
            date_error = str(exc)

        attr = attribution_confidence(meta, team)
        source_completeness = str(meta.get("source_completeness") or infer_source_completeness(body))
        text_access = classify_manual_text_access(body, source_completeness)
        candidate = {
            "path": parsed["path"],
            "title": meta.get("title"),
            "published_at": meta.get("published_at"),
            "account_name": meta.get("account_name"),
            "institution": meta.get("institution"),
            "role": meta.get("role"),
            "analyst_id": meta.get("analyst_id"),
            "team_match": team_match,
            "date_ok": date_ok,
            "date_error": date_error,
            "body_chars": len(body),
            "source_completeness": source_completeness,
            "source_origin": meta.get("source_origin"),
            "text_access": text_access,
            "attribution_confidence": attr,
            "eligible": team_match and date_ok and attr in {"high", "med"} and len(body) > 0,
        }
        candidates.append(candidate)

    eligible = [item for item in candidates if item["eligible"]]
    best = eligible[0] if eligible else None
    if best:
        status = "covered" if best["text_access"] == "full_text" and best["attribution_confidence"] == "high" else "partial"
        issue = None if status == "covered" else "eligible article is partial_text or attribution is below high"
    else:
        status = "missing"
        issue = explain_missing(team, candidates, issues)

    return {
        "analyst_id": team["analyst_id"],
        "institution": team["institution"],
        "role": team["role"],
        "official_accounts": team.get("official_accounts", []),
        "status": status,
        "issue": issue,
        "best": best,
        "candidates": candidates,
        "parse_issues": issues,
    }


def explain_missing(team: dict[str, Any], candidates: list[dict[str, Any]], issues: list[str]) -> str:
    if issues and not candidates:
        return "; ".join(issues[:3])
    if not candidates:
        return "no Markdown file parsed for this team"
    if not any(item["team_match"] for item in candidates):
        return "no file has matching analyst_id, institution/role, or official account"
    if not any(item["date_ok"] for item in candidates if item["team_match"]):
        return "matching file exists but published_at is outside target window or invalid"
    if not any(item["body_chars"] > 0 for item in candidates if item["team_match"] and item["date_ok"]):
        return "matching in-window file has empty body"
    return "matching file exists but attribution is below med"


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Manual WeChat Validation",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| week_dir_exists | {'yes' if result['week_dir_exists'] else 'no'} |",
        f"| file_count | {result['file_count']} |",
        f"| template_count | {result['template_count']} |",
        f"| total_teams | {result['total_teams']} |",
        f"| passed_teams | {result['passed_teams']} |",
        f"| passed | {'yes' if result['passed'] else 'no'} |",
        "",
        f"Target directory: `{result['week_dir']}`",
        "",
        "## Per-Team Result",
        "",
        "| analyst_id | status | text_access | attribution | content_path | issue |",
        "|---|---|---|---|---|---|",
    ]
    for team in result["teams"]:
        best = team.get("best") or {}
        path = best.get("path", "")
        issue = (team.get("issue") or "").replace("|", "\\|")
        lines.append(
            f"| {team['analyst_id']} | {team['status']} | {best.get('text_access', '')} | {best.get('attribution_confidence', '')} | {path} | {issue} |"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate real manual_wechat Markdown samples before Phase 2.")
    parser.add_argument("--mode", choices=["weekly", "manual"], required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--tz", default="Asia/Shanghai")
    parser.add_argument("--max-teams", type=int, default=3)
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--articles-root", default="~/macro-strategy/manual_wechat_articles")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--run-version", default="v1")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
