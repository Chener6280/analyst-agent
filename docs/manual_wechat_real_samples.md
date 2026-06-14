# Manual WeChat Real Samples

Place real, manually saved WeChat article Markdown files under:

```text
~/macro-strategy/manual_wechat_articles/2026-W23/
```

Use this front matter format:

```markdown
---
title: "文章标题"
url: "https://mp.weixin.qq.com/..."
published_at: "2026-06-06"
account_name: "郭磊宏观茶座"
institution: "广发证券"
role: "macro"
analyst_id: "广发证券:macro"
source_type: "official_wechat"
team_members:
  - "郭磊"
---

这里粘贴公众号正文。
```

Expected accounts for the first three teams:

```text
广发证券:macro / 郭磊 / 郭磊宏观茶座
华创证券:macro / 张瑜 / 一瑜中的
国金证券:strategy / 牟一凌 / 一凌策略研究
```

Use `source_type: official_wechat` for direct public-account captures. For
source-verifiable excerpts from reposts or research platforms, prefer
`financial_media` or `research_platform` so coverage reports do not overstate
the source channel.

Validate the files before running coverage:

```bash
python3 scripts/validate_manual_wechat_articles.py \
  --mode manual \
  --start 2026-06-01 \
  --end 2026-06-07 \
  --max-teams 3
```

To create safe `.md.template` files in the target directory:

```bash
python3 scripts/scaffold_manual_wechat_templates.py
```

The templates are ignored by coverage until renamed from `.md.template` to `.md`.

To generate one real `.md` file from a body text file:

```bash
python3 scripts/import_manual_wechat_article.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --analyst-id "广发证券:macro" \
  --title "真实文章标题" \
  --url "https://mp.weixin.qq.com/..." \
  --published-at "2026-06-06" \
  --source-type official_wechat \
  --body-file /path/to/article_body.txt
```

You can also pipe body text through stdin:

```bash
pbpaste | python3 scripts/import_manual_wechat_article.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --analyst-id "华创证券:macro" \
  --title "真实文章标题" \
  --url "https://mp.weixin.qq.com/..." \
  --published-at "2026-06-05" \
  --source-type financial_media
```

After the real `.md` files exist, run the full Phase 1 gate:

```bash
python3 scripts/run_phase1_manual_check.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --max-teams 10
```

This refreshes validation, coverage, and the Phase 2 readiness report.
