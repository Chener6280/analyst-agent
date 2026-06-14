# Stance Schema

Phase 2 writes one JSON document per eligible analyst team under:

```text
~/macro-strategy/scans/{scan_id}/extracted/
```

Required top-level fields:

- `scan_id`
- `schema_version`
- `model_version`
- `mode`
- `institution`
- `role`
- `analyst_id`
- `team_members`
- `window`
- `coverage`
- `text_access`
- `attribution_confidence`
- `dimensions`
- `selections`
- `intra_window_changes`
- `sources`

Each `sources[]` item carries source provenance fields, including `source`,
`source_type`, `url`, `date`, and `adapter_mode`. `source_type` is preserved
from Phase 1 so downstream SQLite/reporting can distinguish official WeChat
captures from financial-media or research-platform excerpts.

Rules:

- Missing stance is `value=null`, not `0`.
- `0` means explicitly neutral.
- Every non-null ordinal stance needs `evidence_ref` and `verbatim`.
- Every selection needs `evidence_ref` and `verbatim`.
- `verbatim` must be found in the referenced source text.
- Phase 2 only extracts teams with covered/partial coverage, full/partial text access, and high/med attribution.

Extraction quality is summarized in:

```text
~/macro-strategy/scans/{scan_id}/extracted/extraction_summary.json
~/macro-strategy/scans/{scan_id}/extracted/extraction_report.md
```

Important quality fields:

- `documents_with_any_signal`: documents with at least one non-null ordinal stance or one categorical selection.
- `zero_signal_documents`: eligible documents that were written but had no extractable stance signal.
- `dimension_non_null_counts`: per-role counts by dimension.
- `source_type_counts`: source provenance distribution for extracted documents.
