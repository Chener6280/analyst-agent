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

## Derivatives analytics adapter

`adapters/ir_derivatives/` is a computation-only package next to the bridge: the EQ Futures page (index-futures basis monitor) and the EQ Options page (model-free VIX per equity underlying, CBOE white-paper variance-swap formula over the two nearest expiries with ≥8 calendar days to expiry) are served through the versioned methods `derivatives.basis`, `derivatives.options_vix`, `derivatives.options_catalog` and `derivatives.options_surface` (the last two keep the eSSVI/SVI surface engine available without a mounted UI). The package never imports `ir_search`; the bridge injects a bounded `fetch` callable built on the public SDK, so analytics stay unit-testable with fakes and the SDK boundary remains single. These methods run longer subprocess timeouts (180s) and cache historical chains / estimated non-trading-day weights under the per-install `userData/derivatives-cache` directory — never in persisted config or the archive. The basis monitor builds the full EOD history once (from each product's listing date: IF 2010-04-16, IH/IC 2015-04-16, IM 2022-07-22; index series from 2010-04-01) into a single cache file that records the covered products/index symbols — a request beyond that set triggers a full rebuild, and afterwards only a short tail is re-fetched per call; `futures_daily` caps each request at 20 symbols so contracts are batched per product. The renderer charts the full history behind a per-product dual-handle brush whose default window equals the table's percentile window ("past N years", reset on manual refresh). VIX covers all 12 listed equity-option underlyings (5 SSE ETFs, 4 SZSE ETFs, HO/IO/MO index options), grouped in the table by tracked asset （上证50/沪深300/中证500/中证1000/科创板50/创业板/深证100; each row carries code/kind/VIX/dVIX/percentile); history is cached per underlying per day (`vix-v1-*.json`) and built from each product's option listing date (510050 from 2015-02-09, IO/159919 from 2019-12-23, MO from 2022-07-22, …) — the "past N years" input only sets the percentile/dVIX statistics window and the default brush window over the full-history chart (per-underlying dual-handle brush, reset on manual refresh, same semantics as the futures rows). Chain chunks are fetched per exchange and shared across that exchange's products (at most 2 chunks per call, rotated across exchanges; the renderer auto-continues while `building` is true). Empty chunks before an exchange's options business began (SSE 2015-02-09, SZSE/CFFEX 2019-12-23) are persisted as null days so long windows converge; later empty chunks are treated as fetch failures and retried, never cached. A trading-calendar outage raises an explicit error instead of letting an empty expected-days set masquerade as build completion (regression: a mid-build calendar hiccup once reported `building=false` with 2021–2022 still missing). `IR_SYSTEM_VIX_UNDERLYINGS` (comma-separated codes) and `IR_SYSTEM_VIX_SINCE` (YYYY-MM-DD build floor) narrow the build set for tests/diagnostics only. `derivatives.basis` accepts `years` plus per-product `rf_<P>`/`div_<P>`/`years_<P>` overrides; by default the risk-free rate is the latest `SHIBOR_3M(10)` fixing (`benchmark_rate`) and the dividend yield is the latest Wind index trailing dividend yield (`index_valuation`), each per product. Responses carry both carry-adjusted and raw basis/annualized/history/percentiles, so the renderer's per-row "use" toggle is an instant local switch. Auto-refresh in the renderer runs 09:30–15:10 Asia/Shanghai only. Vendor IV/Greeks fields are not read; implied vols and Greeks are computed locally and every response carries its conventions and diagnostics for the renderer to display.

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
