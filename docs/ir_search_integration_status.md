# ir-search Integration Status

Status: complete after review round 3.

## Closed Items

| item | status |
|---|---|
| Preserve `canonical_url`, `tier`, `evidence_type`, `matched_entities`, and `found_by` from ir-search hits | done |
| Deduplicate hits by `canonical_url` before raw URL | done |
| Use the ir-search entity CSV schema and canonical ID scheme | done |
| Declare ir-search as a pinned git dependency | done |
| Derive coarse freshness from the requested window | done |
| Use `noLimit` for windows longer than one year | done |

## Current Data Risks

The remaining risks are empirical, not integration defects:

- The selected WeChat provider must be tested against real weekly windows.
- Extraction accuracy needs a small gold set before production use.
- `data/*_sample.csv` should remain minimal fixtures; production vocabulary should come from the pinned ir-search package.

## Next Validation Steps

1. Run Phase 1 on a real current weekly window after confirming `broker_wechat_matrix.md`.
2. Record official-account coverage, full-text rate, and source quality.
3. Build a small gold set for stance extraction accuracy checks.
4. Use `who-mentioned-history` for cross-scan entity mention checks once at least two real scans exist.
