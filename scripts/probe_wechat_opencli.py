#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.retrieval.coverage import classify_attribution, classify_text_access
from scripts._env_utils import load_env_file


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    result = run_probe(args)

    output_dir = Path(args.output_root).expanduser() / "probes"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"wechat_probe_{args.account}"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")

    print(f"wechat_probe={md_path}")
    print(f"json={json_path}")
    print(f"formal_candidate_count={result['formal_candidate_count']}")
    return 0


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    command = os.environ.get("WECHAT_OPENCLI_COMMAND")
    base = {
        "account": args.account,
        "query": args.query,
        "window": {"start": args.start, "end": args.end},
        "adapter_mode": "live",
        "command_set": bool(command),
        "command_ok": False,
        "stdout_summary": "",
        "stderr_summary": "",
        "parse_ok": False,
        "articles": [],
        "formal_candidate_count": 0,
    }
    if not command:
        base["error"] = "WECHAT_OPENCLI_COMMAND is not set"
        return base

    try:
        completed = subprocess.run(
            shlex.split(command) + [args.query],
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except Exception as exc:
        base["error"] = f"opencli command failed before completion: {exc}"
        return base

    base["command_ok"] = completed.returncode == 0
    base["returncode"] = completed.returncode
    base["stdout_summary"] = summarize_text(completed.stdout)
    base["stderr_summary"] = summarize_text(completed.stderr)
    if completed.returncode != 0:
        base["error"] = "WECHAT_OPENCLI_COMMAND is set but command failed"
        return base

    try:
        rows = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        base["error"] = f"stdout is not JSON: {exc}"
        return base

    if not isinstance(rows, list):
        base["error"] = "stdout JSON is not a list"
        return base

    base["parse_ok"] = True
    articles = [analyze_row(row, args) for row in rows if isinstance(row, dict)]
    base["articles"] = articles
    base["formal_candidate_count"] = sum(1 for article in articles if article["formal_coverage_candidate"])
    return base


def analyze_row(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    content = row.get("content") or row.get("text") or row.get("raw_content") or ""
    hit = {
        "source": "wechat_opencli",
        "title": row.get("title") or "",
        "url": row.get("url") or "",
        "snippet": row.get("snippet") or "",
        "published_at": row.get("published_at"),
        "adapter_mode": "live",
        "extra": {
            "account_name": row.get("account_name") or row.get("account") or args.account,
            "content": content,
        },
    }
    analyst, institution = query_parts(args.query)
    text_blob = " ".join(
        [
            str(row.get("title") or ""),
            str(row.get("snippet") or ""),
            str(content),
            str(row.get("account_name") or row.get("account") or ""),
        ]
    )
    text_access = classify_text_access(hit)
    attribution = classify_attribution(
        {
            "institution": institution,
            "role": "macro",
            "analyst_id": f"{institution}:macro",
            "team_members": [analyst] if analyst else [],
            "official_accounts": [args.account],
        },
        hit,
    )
    in_window = is_in_window(row.get("published_at"), args.start, args.end)
    formal = (
        bool(row.get("title"))
        and bool(row.get("published_at"))
        and text_access in {"full_text", "partial_text"}
        and attribution in {"high", "med"}
        and in_window
    )
    return {
        "title": row.get("title"),
        "url": row.get("url"),
        "published_at": row.get("published_at"),
        "has_title": bool(row.get("title")),
        "has_published_at": bool(row.get("published_at")),
        "has_content": bool(content),
        "content_chars": len(str(content)),
        "contains_account": args.account in text_blob,
        "contains_analyst": bool(analyst and analyst in text_blob),
        "contains_institution": bool(institution and institution in text_blob),
        "text_access": text_access,
        "attribution_confidence": attribution,
        "adapter_mode": "live",
        "in_window": in_window,
        "formal_coverage_candidate": formal,
    }


def query_parts(query: str) -> tuple[str, str]:
    parts = query.split()
    analyst = parts[0] if parts else ""
    institution = parts[1] if len(parts) > 1 else ""
    return analyst, institution


def is_in_window(value: Any, start: str, end: str) -> bool:
    if not value:
        return False
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            published = date.fromisoformat(str(value)[:10])
        except ValueError:
            return False
    return date.fromisoformat(start) <= published <= date.fromisoformat(end)


def summarize_text(value: str, limit: int = 1200) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# WeChat OpenCLI Probe: {data['account']}",
        "",
        "| field | value |",
        "|---|---|",
        f"| command_set | {'yes' if data['command_set'] else 'no'} |",
        f"| command_ok | {'yes' if data['command_ok'] else 'no'} |",
        f"| parse_ok | {'yes' if data['parse_ok'] else 'no'} |",
        f"| formal_candidate_count | {data['formal_candidate_count']} |",
    ]
    if data.get("error"):
        error = str(data["error"]).replace("|", "\\|")
        lines.append(f"| error | {error} |")

    lines.extend(
        [
            "",
            "## Articles",
            "",
            "| title | published_at | text_access | attribution | in_window | content_chars | formal |",
            "|---|---|---|---|---|---:|---|",
        ]
    )
    for article in data.get("articles", []):
        title = str(article.get("title") or "").replace("|", "\\|")
        lines.append(
            f"| {title} | {article.get('published_at') or ''} | {article['text_access']} | {article['attribution_confidence']} | {'yes' if article['in_window'] else 'no'} | {article['content_chars']} | {'yes' if article['formal_coverage_candidate'] else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## stdout summary",
            "",
            "```text",
            data.get("stdout_summary") or "",
            "```",
            "",
            "## stderr summary",
            "",
            "```text",
            data.get("stderr_summary") or "",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe WECHAT_OPENCLI_COMMAND for one official account.")
    parser.add_argument("--account", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
