---
name: ir-history-backfill
description: Archive query-scoped historical material from explicitly selected ZSXQ, IMA, and Wisburg sources, a bounded ZSXQ timeline, or full keyword-free collection exports (with optional comments and attachment bytes), into local daily files with coverage diagnostics, deduplication, and resumable checkpoints.
---

# IR history backfill

Use `scripts/download_history.py` for keyword-scoped work and `scripts/archive_export.py` for full-enumeration export work. A worker agent chooses the authorized scope, runs the downloader, and interprets its manifest; it need not read every article into its context. Downloading and normalization use no LLM calls.

Read [archive-and-limits.md](references/archive-and-limits.md) before the first run. Normal searches remain keyword-scoped. The explicit `--zsxq-timeline-export` mode uses the public `ir_search` bounded ZSXQ timeline contract; it is not available for IMA or Wisburg and never implies hidden/deleted content or attachment coverage.

1. Use a Python environment with `ir_search` installed and the existing private `IR_SEARCH_CREDENTIALS_FILE`. Never print or copy credentials. Keep the archive outside source repositories.
2. Honor the selected providers, literal queries, star/knowledge-base IDs, and Wisburg categories. Do not invent keywords to simulate an all-content export. For an explicitly authorized ZSXQ timeline archive, require exact star IDs and use `--zsxq-timeline-export` without a ZSXQ query. Keep `--candidates` equal to or below `--text-reads` so each returned topic gets a bounded detail attempt.
3. Preview without `--execute`; this creates no files and imports no SDK. Default dates are the 365 complete Asia/Shanghai days ending yesterday. Explicit start/end dates are inclusive.
4. Execute the same scope with `--execute`. Verify a small authorized live slice before a long backfill. Re-run the same scope to resume; changing invocation budgets does not reset checkpoints. Exit code 2 means failed or unfinished work: inspect the manifest before resuming. Escalate repeated authentication/permission failures for operator attention.
5. Report records saved, unknown dates, unfinished/failed jobs, and coverage limits. `all_jobs_attempted=true` means the defined query slices were processed, never complete source coverage. Preserve diagnostics and do not silently switch sources.

Example (run from this skill's directory, or use the absolute script path; substitute user-selected queries and real collection IDs):

```sh
python scripts/download_history.py --archive-root /ABSOLUTE/PATH/ir_archive \
  --provider zsxq --provider ima --provider wisburg \
  --query 'zsxq=宏观' --query 'ima=宏观' --query 'wisburg=美联储' \
  --collection 'zsxq=123456' --collection 'ima=REAL_KB_ID' \
  --category archive --category article \
  --start 2025-09-25 --end 2026-09-24 --retrieve-details
```

`--retrieve-details` attempts the detail API for returned records. Abstracts, truncation, and access failures stay explicit. Attachments remain metadata; original binaries, images, audio, and hidden comments are not downloaded. Offline validation: `python -m unittest discover -s scripts -p 'test_*.py'` from this skill directory.

Bounded ZSXQ timeline example:

```sh
python scripts/download_history.py --archive-root /ABSOLUTE/PATH/ir_archive \
  --provider zsxq --zsxq-timeline-export \
  --collection 'zsxq=123456' --start 2026-08-25 --end 2026-09-24 \
  --slice-days 1 --candidates 5 --text-reads 5
```

## Full-enumeration export (`archive_export.py`)

Use `scripts/archive_export.py` for keyword-free collection export via the public
`ir_search` collection-export API (`export_collection_timeline`, `list_topic_comments`,
`retrieve_asset`). Job = provider × collection × date slice with
`mode:"export"` checkpoint IDs, so export jobs never collide with keyword jobs in the
same SQLite index. Read the capability matrix in
[archive-and-limits.md](references/archive-and-limits.md) first: IMA has **no**
keywordless enumeration upstream, so export mode archives only the knowledge-base
directory snapshot plus `daily/unknown` records with `provider_full_export_supported=false`
and explicit gap records — never use a keyword matrix to fake full coverage.

1. Re-scan subscriptions first (outside this skill) so
   `<archive-root>/subscriptions/latest.json` is fresh. Export mode reads collections
   from it by default (`zsxq.groups[].group_id`, `ima.knowledge_bases[].collection_id`,
   `wisburg.categories[].category`); explicit `--collection` overrides. Collections
   present in older SQLite export jobs but absent from the scan are reported as
   `collections_missing` and skipped.
2. Preview without `--execute` (no writes, no SDK import), then execute the same scope.
   `--slice-days 3` bounds each job's window; `--max-calls` bounds SDK calls per
   invocation. Re-run the same scope to resume: continuation cursors live in the SQLite
   job payloads and cached raw envelopes replay without re-charging the budget.
3. A page diagnosed `rate_limit` (or upstream-stopped coverage) saves the cursor,
   emits `rate_limit_stopped`, and stops that provider for the rest of the run;
   `entitlement_denied` stops only that collection. Exit code 2 means failed or
   unfinished work: inspect the run manifest before resuming.
4. `--comments` (zsxq only) paginates every exported topic's comments into
   `daily/<day>/zsxq/comments/<topic>.jsonl`; nested replies are not provided upstream
   and are recorded as `comments_nested: "not_provided_upstream"`. `--assets` downloads
   attachment bytes into content-addressed `objects/` with per-item manifests under
   `assets/`; zsxq/wisburg original images are metadata-only (`unsupported` upstream),
   wisburg original files are never provided. `--asset-max-bytes` and
   `--size-guard-bytes` are positive caller budgets with no fixed upper ceiling; the
   cumulative guard defaults to 20 GiB and trips as `size_guard_tripped` before the
   volume grows further.
5. `coverage_complete` is job-level evidence, not hope: true only when the enumeration
   reached the date floor, enabled comment/asset sub-tasks are all resolved, and the
   provider supports full export at all (never for IMA). Daily manifests and checkpoints
   reflect it per day; the run-level summary keeps `coverage_complete=false` unless every
   job proves it.

Example (run from this skill's directory; substitute real collection IDs or rely on the
subscription scan):

```sh
# preview first: no writes, no SDK import
python scripts/archive_export.py --archive-root /ABSOLUTE/PATH/ir_archive \
  --provider zsxq --start 2026-08-25 --end 2026-09-24 --slice-days 3

# execute enumeration for every subscribed collection
python scripts/archive_export.py --archive-root /ABSOLUTE/PATH/ir_archive \
  --provider zsxq --start 2026-08-25 --end 2026-09-24 --slice-days 3 --execute

# add zsxq comments and attachment bytes on resume (idempotent, cursor-based)
python scripts/archive_export.py --archive-root /ABSOLUTE/PATH/ir_archive \
  --provider zsxq --collection 452558581448 \
  --start 2026-08-25 --end 2026-09-24 --comments --assets --max-assets 20 \
  --asset-max-bytes 134217728 --size-guard-bytes 137438953472 --execute

# ima: directory snapshot + unknown-day records only; gaps are explicit
python scripts/archive_export.py --archive-root /ABSOLUTE/PATH/ir_archive \
  --provider ima --start 2026-08-25 --end 2026-09-24 --execute
```

Offline validation: `python -m unittest discover -s scripts -p 'test_*.py'` from this
skill directory (covers both downloader families).
