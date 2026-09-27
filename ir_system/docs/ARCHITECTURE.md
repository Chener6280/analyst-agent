# ir_system architecture

## Product boundary

`ir_system` owns the desktop experience and user-local state:

- navigation and workspaces;
- entity presentation;
- watchlists and saved screens;
- local settings and provider selection;
- cross-provider normalization;
- data freshness, coverage and diagnostics presentation.

It does not own vendor credentials, source-specific queries, document extraction, or the implementation of financial databases. Those belong to providers such as `ir_search`.

## Stable provider boundary

The desktop core speaks `ir-system-provider/v1`. A provider response must include:

- provider identity;
- provider status;
- fetch time;
- module-level readiness;
- user-facing diagnostics.

The JSON schema is stored in `contracts/provider-v1.schema.json`. Provider-specific payloads may add details, but desktop modules must not depend on raw upstream class names or database fields.

## ir_search adapter

`adapters/ir_search_bridge.py` is deliberately outside the Electron application code. It imports only public `ir_search` exports and maps the current capability catalog into IR System modules.

The current mapping is conservative:

| IR System module | Current mapping |
|---|---|
| Macro | `macro_series` |
| EQ | A-share and US registered price/security datasets; fund coverage reported separately |
| FI | unavailable until a unified fixed-income dataset exists |
| FX | partial through macro series only |
| COMDTY | Chinese futures/options capabilities |
| Companies | per market (A_SHARE / HK / US): `securities`, financial statements, JYDB/HKEX/SEC filings, company IR issuer catalog, Tushare research abstracts; material providers are mapped to markets explicitly in the bridge |
| Research | material providers exposed by `list_capabilities` |
| Calendar | planned |
| Watchlists | local to IR System |

Registration is not treated as live verification. The bridge reports capability state without making network or database calls.

## Future providers

Additional local data systems should implement the same subprocess protocol instead of being added directly to the renderer. Examples:

- a local SQLite or DuckDB warehouse;
- a licensed market-data SDK;
- a document vault;
- a portfolio system;
- a separately deployed HTTP gateway wrapped by a local adapter.

This keeps provider lifecycle and licensing independent from the desktop release.

## ZSXQ web archive adapter

`adapters/zsxq_web/` is an auxiliary ingestion adapter, not an `ir_search` implementation. Its boundaries are intentionally narrow:

- `zsxq-cli` performs sanitized group discovery, membership checks and one-topic Skill probes;
- a dedicated persistent Chrome profile holds the user's normal web session;
- the planner routes active Skill-enabled groups back to `ir_search`, active Skill-disabled/download-enabled groups to the web executor, and all other states to an explicit block;
- the executor follows visible member pages and official download controls only;
- web records and content-addressed objects live under `<archive-root>/zsxq_web/`, with resumable per-job checkpoints and no credentials or signed URLs.

The CLI, rather than the calling model, owns validation, fresh-scan expiry, pacing, file-name sanitization, locking and failure classification. Incomplete scans never replace the last complete snapshot or produce a plan. This makes the workflow usable by inexpensive workers while preserving the same access boundaries.

## Local storage plan

Version 0.1 stores only application/provider settings in Electron `userData`. Planned application-owned records include:

- watchlists;
- saved screens;
- notes and document annotations;
- entity aliases;
- research workflow state;
- cached normalized observations with provenance.

SQLite is appropriate for application records and evidence metadata. Larger analytical time series can later use Parquet with DuckDB. Neither choice should leak into provider contracts.

## Packaging

Electron Builder creates target-specific packages. `adapters/` is copied as an external resource rather than bundled into the application archive, allowing the adapter to be patched or replaced independently of the renderer and main-process code.

`ir_search` remains an optional installation on each computer. Paths and credentials are never embedded in the package.
