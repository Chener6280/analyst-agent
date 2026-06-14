#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_analyst_list, resolve_window


def main() -> int:
    args = parse_args()
    window = resolve_window(args.mode, args.start, args.end, args.tz)
    target_dir = Path(args.output_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    teams = [team for team in load_analyst_list(args.analyst_list) if team["active"]]
    if args.max_teams:
        teams = teams[: args.max_teams]

    written = []
    skipped = []
    for team in teams:
        template = template_context(team, window)
        path = target_dir / template["filename"]
        if path.exists() and not args.overwrite:
            skipped.append(str(path))
            continue
        path.write_text(render_template(template), encoding="utf-8")
        written.append(str(path))

    readme = target_dir / "README_manual_wechat_templates.md"
    if args.overwrite or not readme.exists():
        readme.write_text(render_readme(target_dir), encoding="utf-8")
        written.append(str(readme))

    print("target_dir=" + str(target_dir))
    for path in written:
        print("written=" + path)
    for path in skipped:
        print("skipped_existing=" + path)
    return 0


def template_context(team: dict, window: dict) -> dict[str, str]:
    member = team["team_members"][0] if team.get("team_members") else team["institution"]
    account = team["official_accounts"][0] if team.get("official_accounts") else team["institution"]
    published_at = window["end"]
    return {
        "filename": f"{team['institution']}_{team['role']}_{member}_{published_at}.md.template",
        "title_hint": "文章标题",
        "published_at": published_at,
        "account_name": account,
        "institution": team["institution"],
        "role": team["role"],
        "analyst_id": team["analyst_id"],
        "team_member": member,
    }


def render_template(team: dict[str, str]) -> str:
    return f'''---
title: "{team["title_hint"]}"
url: "https://mp.weixin.qq.com/..."
published_at: "{team["published_at"]}"
account_name: "{team["account_name"]}"
institution: "{team["institution"]}"
role: "{team["role"]}"
analyst_id: "{team["analyst_id"]}"
team_members:
  - "{team["team_member"]}"
---

这里粘贴公众号正文。

使用说明：
1. 将 title/url/published_at 改为真实文章信息。
2. 将本段说明删除，粘贴真实公众号正文。
3. 正文建议不少于 500 个中文字符；少于 500 字会被识别为 partial_text。
4. 完成后把文件名后缀从 .md.template 改为 .md，coverage 才会读取。
'''


def render_readme(target_dir: Path) -> str:
    return f"""# Manual WeChat Templates

This directory is for real manually saved WeChat article Markdown files.

Target directory:

```text
{target_dir}
```

The `.md.template` files are ignored by coverage. For each template:

1. Fill in the real `title`, `url`, and `published_at`.
2. Replace the instructions with the real article body.
3. Rename the file from `.md.template` to `.md`.
4. Run:

```bash
python3 scripts/validate_manual_wechat_articles.py --mode manual --start 2026-06-01 --end 2026-06-07 --max-teams 3
```
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create .md.template files for manual_wechat real samples.")
    parser.add_argument("--output-dir", default="~/macro-strategy/manual_wechat_articles/2026-W23")
    parser.add_argument("--mode", choices=["manual", "weekly"], default="manual")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--tz", default="Asia/Shanghai")
    parser.add_argument("--analyst-list", default="data/analyst-list.md")
    parser.add_argument("--max-teams", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
