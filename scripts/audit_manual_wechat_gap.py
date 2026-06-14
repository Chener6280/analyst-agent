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

from core.config import load_analyst_list, resolve_window
from scripts.validate_manual_wechat_articles import validate_articles


def main() -> int:
    args = parse_args()
    window = resolve_window(args.mode, args.start, args.end, args.tz)
    teams = [team for team in load_analyst_list(args.analyst_list) if team["active"]]
    if args.max_teams:
        teams = teams[: args.max_teams]

    validation = validate_articles(teams, window, Path(args.articles_root).expanduser())
    report = build_gap_report(validation, min_teams=args.min_teams, min_extracted=args.min_extracted)

    output_dir = Path(args.output_root).expanduser() / "diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "manual_wechat_gap.json"
    md_path = output_dir / "manual_wechat_gap.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"manual_wechat_gap={md_path}")
    print(f"json={json_path}")
    print(f"ready_for_global_acceptance_inputs={report['ready_for_global_acceptance_inputs']}")
    return 0 if report["ready_for_global_acceptance_inputs"] else 1


def build_gap_report(validation: dict[str, Any], *, min_teams: int, min_extracted: int) -> dict[str, Any]:
    eligible = [team for team in validation["teams"] if team["status"] in {"covered", "partial"}]
    missing = [team for team in validation["teams"] if team["status"] not in {"covered", "partial"}]
    ready = len(validation["teams"]) >= min_teams and len(eligible) >= min_extracted and not missing
    return {
        "ready_for_global_acceptance_inputs": ready,
        "window": validation["window"],
        "articles_root": validation["articles_root"],
        "week_dir": validation["week_dir"],
        "total_teams": validation["total_teams"],
        "eligible_samples": len(eligible),
        "missing_samples": len(missing),
        "min_teams": min_teams,
        "min_extracted": min_extracted,
        "eligible": [
            {
                "analyst_id": team["analyst_id"],
                "status": team["status"],
                "content_path": (team.get("best") or {}).get("path"),
                "text_access": (team.get("best") or {}).get("text_access"),
                "attribution_confidence": (team.get("best") or {}).get("attribution_confidence"),
            }
            for team in eligible
        ],
        "missing": [
            {
                "analyst_id": team["analyst_id"],
                "institution": team["institution"],
                "role": team["role"],
                "official_accounts": team.get("official_accounts", []),
                "issue": team.get("issue"),
            }
            for team in missing
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Manual WeChat Gap Audit",
        "",
        f"Ready for global acceptance inputs: **{'yes' if report['ready_for_global_acceptance_inputs'] else 'no'}**",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| total_teams | {report['total_teams']} |",
        f"| eligible_samples | {report['eligible_samples']} |",
        f"| missing_samples | {report['missing_samples']} |",
        f"| min_teams | {report['min_teams']} |",
        f"| min_extracted | {report['min_extracted']} |",
        "",
        f"Target directory: `{report['week_dir']}`",
        "",
        "## Eligible Samples",
        "",
        "| analyst_id | status | text_access | attribution | content_path |",
        "|---|---|---|---|---|",
    ]
    for item in report["eligible"]:
        lines.append(
            f"| {item['analyst_id']} | {item['status']} | {item.get('text_access') or ''} | {item.get('attribution_confidence') or ''} | {item.get('content_path') or ''} |"
        )
    if not report["eligible"]:
        lines.append("|  |  |  |  |  |")

    lines.extend(
        [
            "",
            "## Missing Samples",
            "",
            "| analyst_id | role | official_accounts | issue |",
            "|---|---|---|---|",
        ]
    )
    for item in report["missing"]:
        accounts = ", ".join(item.get("official_accounts") or [])
        issue = (item.get("issue") or "").replace("|", "\\|")
        lines.append(f"| {item['analyst_id']} | {item['role']} | {accounts} | {issue} |")
    if not report["missing"]:
        lines.append("|  |  |  |  |")

    lines.extend(["", "## Next Commands", ""])
    if report["ready_for_global_acceptance_inputs"]:
        lines.extend(
            [
                "The candidate list has enough eligible real samples for the global MVP gate. Run the full pipeline:",
                "",
                "```bash",
                "python3 scripts/run_mvp_pipeline.py \\",
                "  --analyst-list data/analyst-list-acceptance-candidates.md \\",
                "  --max-teams 10",
                "```",
            ]
        )
    else:
        lines.extend(
            [
                "Generate templates for the candidate list:",
                "",
                "```bash",
                "python3 scripts/scaffold_manual_wechat_templates.py \\",
                "  --analyst-list data/analyst-list-acceptance-candidates.md \\",
                "  --max-teams 10 \\",
                "  --output-dir ~/macro-strategy/manual_wechat_articles/2026-W23",
                "```",
                "",
                "After adding real article bodies, rerun this audit and then the MVP pipeline with the same analyst list.",
            ]
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit real manual_wechat samples needed for global MVP acceptance.")
    parser.add_argument("--mode", choices=["manual", "weekly"], default="manual")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--tz", default="Asia/Shanghai")
    parser.add_argument("--analyst-list", default="data/analyst-list-acceptance-candidates.md")
    parser.add_argument("--articles-root", default="~/macro-strategy/manual_wechat_articles")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--max-teams", type=int, default=10)
    parser.add_argument("--min-teams", type=int, default=10)
    parser.add_argument("--min-extracted", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
