# Production Smoke Run - 2026-W24

Date run: 2026-06-14.

Scope: five user-confirmed latest WeChat accounts from
`data/analyst-list-production-sample.md`, window `2026-06-08` to `2026-06-14`.

## Commands

Preflight source confirmation:

```bash
python3 scripts/run_coverage_check.py \
  --mode manual \
  --start 2026-06-08 \
  --end 2026-06-14 \
  --run-version prod-smoke \
  --max-teams 5 \
  --analyst-list data/analyst-list-production-sample.md \
  --output-root /private/tmp/analyst_agent_prod_smoke \
  --preflight-only \
  --source-matrix broker_wechat_matrix.md
```

Production gate:

```bash
WECHAT_OPENCLI_COMMAND='python3 /Users/chen/Documents/ir_search/tools/gzh_fetch.py --accounts /Users/chen/Documents/ir_search/accounts.json --opencli --providers dajiala,wewe,rss --default-days 30 --fulltext' \
python3 scripts/run_mvp_pipeline.py \
  --retrieval-profile live \
  --start 2026-06-08 \
  --end 2026-06-14 \
  --run-version prod-pipeline \
  --max-teams 5 \
  --analyst-list data/analyst-list-production-sample.md \
  --sources wechat_opencli,bocha,exa,web_search \
  --env-file /Users/chen/Documents/ir_search/ir_search.env \
  --output-root /private/tmp/analyst_agent_prod_pipeline \
  --db-path /private/tmp/analyst_agent_prod_pipeline/analyst_views.db \
  --source-matrix broker_wechat_matrix.md \
  --min-teams 5 \
  --min-extracted 5 \
  --quality-profile production
```

## Results

The source preflight matched all 5 teams to `broker_wechat_matrix.md`.

The live production gate intentionally stopped before Phase 2 because Phase 1
coverage was insufficient:

| metric | result |
|---|---:|
| total_teams | 5 |
| covered | 2 |
| source_lost | 3 |
| covered_plus_partial_rate | 40% |
| full_text_rate | 40% |
| production_coverage_rate | 40% |
| high_or_med_attribution_rate | 40% |
| mock_or_placeholder_count | 0 |

Covered full-text official WeChat teams:

| analyst_id | account | latest in-window article |
|---|---|---|
| 国金证券:strategy | 一凌策略研究 | 推开旧世界的门 \| 国金策略 |
| 广发证券:macro | 郭磊宏观茶座 | 【广发宏观团队】目前处于周期叠加的什么阶段？ |

Source-lost teams:

| analyst_id | account | observed blocker |
|---|---|---|
| 华创证券:macro | 一瑜中的 | `gzh_fetch` / `wewe` returned 404 or no valid rows |
| 中信建投证券:strategy | CSC研究 策略团队 | `gzh_fetch` / `wewe` returned 404 or no valid rows |
| 兴业证券:strategy | XYSTRATEGY | `gzh_fetch` / `wewe` returned 404 or no valid rows |

## End-To-End Continuation

For diagnostic purposes, the two covered teams were manually continued through
P2-P8. That partial run passed P2 extraction and P3 readiness, wrote SQLite
rows, generated cross-section and weekly brief reports, exported agent handoff,
history readiness, visual pack, and project package. The package correctly
reported `production_ready=false` because only 2 of 5 teams had production-grade
full-text official WeChat coverage.

## Fixes Applied

- `scripts/_env_utils.py` now accepts shell-style `export KEY=value` lines.
- `scripts/_env_utils.py` infers `IR_SEARCH_PATH` when the env file lives at the
  root of an `ir_search` checkout.
- `core/retrieval/coverage.py` now materializes live `wechat_opencli` full text
  into parseable article cache files for P2 extraction.
- `scripts/run_mvp_pipeline.py` now supports `--retrieval-profile live` for
  ir_search-based production runs without requiring local manual WeChat files.
- `scripts/check_phase2_readiness.py` no longer requires manual validation when
  all eligible samples come from live `wechat_opencli`.
- `data/analyst-list-production-sample.md` defines the 5-account production
  smoke sample.

## Remaining Production Blocker

This project is now gating correctly, but the 5-account sample is not production
ready until the upstream `ir_search` account identifiers/providers are fixed for
`一瑜中的`, `CSC研究 策略团队`, and `XYSTRATEGY`, or equivalent manual/full-text
fallback articles are supplied for those accounts.

