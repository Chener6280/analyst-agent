# WeChat Source Lessons 2026-W24

## What Went Wrong

The first full weekly run mixed three different states that looked similar in
the final coverage report:

- account exists in `accounts.json`, but only has `wewe`;
- `wewe` feed exists, but has zero imported articles;
- `dajiala` would have recovered the account, but no `dajiala.name` was
  configured.

The clearest example was `中信建投证券:macro`: `CSC研究 宏观团队` had a
valid `wewe.mp_id`, but the local feed was empty and the account had no
`dajiala` fallback. By contrast, `CSC研究 策略团队` also had an empty `wewe`
feed, but it passed because `dajiala` was configured and returned window
articles.

## Production Rules

Every account selected from `broker_wechat_matrix.md` for live weekly retrieval
must have both:

- `dajiala.name`
- `wewe.mp_id`

For account selection:

- if a macro/strategy personal or team account is listed, search only that
  account for the role;
- `中信证券` and `中国银河证券` may use the official research account when the
  role account is blank;
- other firms without a role account are not searched through the official
  account.

For provider results:

- use the union of `dajiala` and `wewe` rows;
- when `dajiala` has a row missing from `wewe`, keep the `dajiala` row and try
  full-text recovery from the WeChat URL;
- when both providers have no window rows, mark the account as not ready;
- do not silently fall back to generic web search for WeChat-only production
  runs.

## Guardrails Added

`scripts/ensure_wechat_dual_source_accounts.py` checks the exact live account
set implied by the analyst list and `broker_wechat_matrix.md`.

Use it after changing the matrix or adding a new public account:

```bash
python3 scripts/ensure_wechat_dual_source_accounts.py \
  --analyst-list data/analyst-list-full-2026w24.md \
  --source-matrix broker_wechat_matrix.md \
  --fail-on-missing
```

To add missing `dajiala.name` entries using the account name:

```bash
python3 scripts/ensure_wechat_dual_source_accounts.py \
  --analyst-list data/analyst-list-full-2026w24.md \
  --source-matrix broker_wechat_matrix.md \
  --apply
```

The live MVP pipeline now runs this check before `wewe` login preparation and
before network retrieval. `scripts/run_coverage_check.py` also fails before
retrieval if a searched account lacks either provider config, unless
`--allow-single-wechat-provider` is explicitly passed.

The live MVP pipeline also uses a two-pass delivery closeout:

1. write initial `weekly_brief`, `agent_handoff`, and `project_package`;
2. run MVP acceptance;
3. refresh `weekly_brief`, `agent_handoff`, and `project_package` so final
   artifacts include the scan-specific acceptance status.

This avoids the false failure mode where acceptance runs before
`project_completion.json` exists, and it avoids final reports showing stale
`acceptance_passed: None`.

Additional hardening from review:

- SQL table/column identifiers used by SQLite helper functions are validated
  before interpolation.
- `WECHAT_OPENCLI_COMMAND` must explicitly invoke `gzh_fetch.py`, and invalid
  `WECHAT_OPENCLI_TIMEOUT` values are reported as provider diagnostics.
- generated article-cache source ids are sanitized before being used in file
  names.
- account and matrix mirror paths can be supplied with `WECHAT_ACCOUNTS_PATH`
  and `BROKER_WECHAT_MATRIX_MIRROR`, while preserving local defaults.

## 2026-W24 Baseline After Fix

For 2026-06-08 through 2026-06-14:

- searchable accounts: 43
- dual-source configured accounts: 43
- `dajiala` accounts with window rows: 39
- `wewe` accounts with window rows: 22
- accounts with both providers returning window rows: 22
- team ready: 37 / 38
- account ready: 39 / 43

The remaining not-ready accounts had no window rows in either provider after
dual-source configuration, so they are real source-coverage gaps rather than
configuration gaps.
