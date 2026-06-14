# analyst-views MVP

This repository implements the first nine phases of the analyst-views MVP plan:

1. Phase 0: analyst-team list, window resolution, and scan ID generation.
2. Phase 1: retrieval coverage validation and report generation.
3. Phase 2: rule-based stance extraction MVP with schema validation.
4. Phase 3: SQLite ingestion and weekly cross-section aggregation.
5. Phase 4: deterministic weekly brief generation from accepted P1-P3 artifacts.
6. Phase 5: local read interface and agent handoff package for downstream tools.
7. Phase 6: guarded history readiness and simple time-series query functions.
8. Phase 7: deterministic SVG visual pack for report and agent reuse.
9. Phase 8: final project package, MCP-compatible stdio bridge, and scheduling template.

It intentionally does not install a hosted MCP service, docx, PDF output, or
multi-week trend interpretation yet. P6 exposes time-series queries, but marks
history as insufficient until enough real weekly scans are accumulated. P7
exports standalone SVG charts, and P8 packages the current artifacts for final
handoff.

## Coverage Check

By default, runtime outputs are written under `~/macro-strategy/scans/{scan_id}`.
Use `--output-root` to write elsewhere during local testing.

```bash
python scripts/run_coverage_check.py \
  --mode manual \
  --start 2026-06-01 \
  --end 2026-06-07 \
  --max-teams 10 \
  --run-version v1
```

The retrieval layer tries to import an existing `ir_search` package. If it is not
installed, set:

```bash
export IR_SEARCH_PATH=/path/to/ir-search-repo
export IR_SEARCH_LIVE=1
```

`mock` and `placeholder` adapter results are never counted as formal coverage.
They remain visible in diagnostics so source quality can be inspected directly.

## Manual WeChat Input

Until automated WeChat collection is available, local Markdown articles can be
used as a live, user-provided source:

```text
~/macro-strategy/manual_wechat_articles/2026-W23/
  广发证券_macro_郭磊_2026-06-06.md
```

Each file must include YAML front matter with `title`, `url`, `published_at`,
`account_name`, `institution`, `role`, and `analyst_id`, followed by non-empty
article body text. Run with:

```bash
python3 scripts/run_coverage_check.py \
  --mode manual \
  --start 2026-06-01 \
  --end 2026-06-07 \
  --max-teams 3 \
  --run-version v1 \
  --sources manual_wechat,wechat_opencli,bocha,exa,web_search
```

## Stance Extraction

After Phase 1 readiness passes, run:

```bash
python3 scripts/run_extract_mvp.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

Outputs are written under:

```text
~/macro-strategy/scans/{scan_id}/extracted/
```

Phase 2 is deliberately rule-based for the MVP. It only extracts from eligible
Phase 1 samples and validates every non-null stance against source-backed
`evidence_ref` and verbatim text.

The extraction report also records quality diagnostics such as
`documents_with_any_signal`, `zero_signal_documents`, per-dimension non-null
coverage, and `source_type_counts`. Passing extraction means the JSON is valid;
use these fields to judge how much of the run is analytically informative.

Before changing the extraction model or using a new prompt/model family, run the
gold-set accuracy gate:

```bash
python3 scripts/check_extract_accuracy.py \
  --gold tests/gold/extraction_gold.jsonl \
  --diagnostics-dir outputs/diagnostics
```

The seed gold rows only verify the harness. Production-quality accuracy checks
require human-labeled gold rows authored outside the model.

## SQLite And Cross Section

After Phase 2 extraction passes, ingest the stance JSON into SQLite:

```bash
python3 scripts/ingest_sqlite.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

Then generate the cross-section report:

```bash
python3 scripts/aggregate_cross_section.py \
  --scan-id manual-2026-06-01-2026-06-07-v1 \
  --output markdown
```

Outputs:

```text
~/macro-strategy/analyst_views.db
~/macro-strategy/scans/{scan_id}/reports/weekly_cross_section.md
~/macro-strategy/scans/{scan_id}/reports/weekly_cross_section.json
```

## Weekly Brief

After the cross-section report is available, generate the P4 analyst brief:

```bash
python3 scripts/generate_weekly_brief.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

Outputs:

```text
~/macro-strategy/scans/{scan_id}/reports/weekly_brief.md
~/macro-strategy/scans/{scan_id}/reports/weekly_brief.json
```

The brief is deterministic. It reads the cross-section JSON, coverage summary,
extraction summary, and acceptance diagnostics, then writes a Markdown report
with weekly conclusions, macro/strategy tables, data-quality notes, and an
evidence appendix with source links and source types. It does not call an LLM
or the network.

## Agent Read Interface

After the weekly brief is available, export the P5 handoff package:

```bash
python3 scripts/export_agent_handoff.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

Outputs:

```text
~/macro-strategy/scans/{scan_id}/reports/agent_handoff.md
~/macro-strategy/scans/{scan_id}/reports/agent_handoff.json
```

The handoff package is the local precursor to a future MCP interface. It
records stable artifact paths, supported query examples, the brief headline,
quality warnings, compact macro/strategy snapshots, and top entity mentions.

The same interface can be queried directly:

```bash
python3 scripts/query_agent_interface.py scan-context \
  --scan-id manual-2026-06-01-2026-06-07-v1

python3 scripts/query_agent_interface.py dim-summary \
  --scan-id manual-2026-06-01-2026-06-07-v1 \
  --role macro \
  --dim-key growth

python3 scripts/query_agent_interface.py team-stance \
  --scan-id manual-2026-06-01-2026-06-07-v1 \
  --analyst-id 广发证券:macro

python3 scripts/query_agent_interface.py who-mentioned \
  --scan-id manual-2026-06-01-2026-06-07-v1 \
  --entity INDUSTRY:AI算力

python3 scripts/query_agent_interface.py who-mentioned-history \
  --entity 300750.SZ \
  --weeks 4
```

## History Readiness

After the agent handoff is available, export the P6 history readiness report:

```bash
python3 scripts/export_history_readiness.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

Outputs:

```text
~/macro-strategy/scans/{scan_id}/reports/history_readiness.md
~/macro-strategy/scans/{scan_id}/reports/history_readiness.json
```

The default trend threshold is 4 real scans. With fewer scans, P6 reports
`insufficient_history` while still exposing query functions for the current
stored history:

```bash
python3 scripts/query_agent_interface.py history-readiness \
  --scan-id manual-2026-06-01-2026-06-07-v1

python3 scripts/query_agent_interface.py consensus-series \
  --role macro \
  --dim-key growth

python3 scripts/query_agent_interface.py team-series \
  --analyst-id 广发证券:macro \
  --dim-key growth

python3 scripts/query_agent_interface.py tag-rotation \
  --role strategy \
  --dim-key sector
```

## Visual Pack

After history readiness is available, export the P7 visual pack:

```bash
python3 scripts/export_visual_pack.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

Outputs:

```text
~/macro-strategy/scans/{scan_id}/reports/visual_pack.md
~/macro-strategy/scans/{scan_id}/reports/visual_pack.json
~/macro-strategy/scans/{scan_id}/reports/charts/macro_consensus.svg
~/macro-strategy/scans/{scan_id}/reports/charts/strategy_sector_tags.svg
~/macro-strategy/scans/{scan_id}/reports/charts/growth_history_series.svg
```

The charts are generated from local JSON and SQLite outputs. They are meant as
deterministic report assets that can be embedded later in docx, PDF, web, or
agent-facing summaries without rerunning extraction.

## Final Project Package

After the visual pack is available, export the final package:

```bash
python3 scripts/export_project_package.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

Outputs:

```text
~/macro-strategy/scans/{scan_id}/reports/project_package/project_completion.json
~/macro-strategy/scans/{scan_id}/reports/project_package/final_report.md
~/macro-strategy/scans/{scan_id}/reports/project_package/final_report.html
~/macro-strategy/scans/{scan_id}/reports/project_package/completion_checklist.md
~/macro-strategy/scans/{scan_id}/reports/project_package/com.local.analyst-views.weekly.plist
```

The launchd plist is a template only; it is not installed automatically.

## MCP-Compatible Server

The local stdio bridge exposes the same read interface as tool calls:

```bash
python3 mcp/analyst_views_server.py \
  --output-root ~/macro-strategy \
  --db-path ~/macro-strategy/analyst_views.db
```

It supports `initialize`, `tools/list`, and `tools/call` JSON-RPC messages for
scan context, dimension summaries, team stance, entity mentions, history
readiness, consensus series, team series, and tag rotation.

## Gates And Acceptance

To check the global MVP acceptance criteria:

```bash
python3 scripts/check_mvp_acceptance.py \
  --scan-id manual-2026-06-01-2026-06-07-v1
```

The global acceptance gate follows the project plan: at least 10 covered teams
and at least 5 extracted stance samples. Smaller local proof runs can pass
Phase 1-8 but still fail global acceptance because sample size is insufficient.

`mvp_acceptance.md` separates hard gates from non-blocking quality warnings.
`Passed: yes` means the MVP gate is satisfied; still inspect `Quality Warnings`
for analytical limitations such as zero-signal extracted documents, low
full-text coverage, non-official source mix, or dimensions with no non-null
stance.

The acceptance gate also checks P4-P8 generation by requiring
`weekly_brief.md`, `agent_handoff.json`, `history_readiness.json`,
`visual_pack.json`, and `project_completion.json` after the cross-section step
has completed.

Diagnostics write both latest files, such as `mvp_acceptance.md`, and
scan-specific files, such as `{scan_id}__mvp_acceptance.md`. Validation,
readiness, and acceptance diagnostics all keep scan-specific copies so later
runs do not erase the audit trail for a previous scan.

Current acceptance proof:

```text
scan_id: manual-2026-06-01-2026-06-07-v1
candidate list: data/analyst-list-acceptance-candidates.md
coverage teams: 10
extracted stance docs: 10
SQLite stance rows: 50
weekly brief: ~/macro-strategy/scans/manual-2026-06-01-2026-06-07-v1/reports/weekly_brief.md
agent handoff: ~/macro-strategy/scans/manual-2026-06-01-2026-06-07-v1/reports/agent_handoff.md
history readiness: ~/macro-strategy/scans/manual-2026-06-01-2026-06-07-v1/reports/history_readiness.md
visual pack: ~/macro-strategy/scans/manual-2026-06-01-2026-06-07-v1/reports/visual_pack.md
project package: ~/macro-strategy/scans/manual-2026-06-01-2026-06-07-v1/reports/project_package/project_completion.json
acceptance report: ~/macro-strategy/diagnostics/mvp_acceptance.md
```

To rerun the gated local pipeline:

```bash
python3 scripts/run_mvp_pipeline.py \
  --start 2026-06-01 \
  --end 2026-06-07 \
  --max-teams 3
```

For the 10-team acceptance candidate list:

```bash
python3 scripts/audit_manual_wechat_gap.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --max-teams 10

python3 scripts/run_mvp_pipeline.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --max-teams 10
```

The pipeline passes the computed `scan_id`, output root, diagnostics directory,
and SQLite path through every phase. For an isolated dry run:

```bash
python3 scripts/run_mvp_pipeline.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --max-teams 10 \
  --output-root /private/tmp/macro-strategy-pipeline-check \
  --db-path /private/tmp/macro-strategy-pipeline-check/views.db
```
