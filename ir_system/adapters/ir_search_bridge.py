#!/usr/bin/env python3
"""Optional ir_search adapter for the stable IR System provider protocol.

This file is the only place in IR System that imports ir_search. The Electron
application communicates with it through one request and one JSON response on
stdio, so upstream SDK changes remain contained here.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, datetime, timezone
from typing import Any

PROTOCOL = "ir-system-provider/v1"

COMPANY_MARKETS = ("A_SHARE", "HK", "US")
COMPANY_SECTIONS = ("search", "financials", "filings", "events", "research")
COMPANY_SECTION_DATASETS = {
    "search": ("securities",),
    "financials": ("financial_statements", "financial_statements_standardized"),
}
# Material capabilities carry no market field, so their scope is reviewed here
# per provider. company_ir covers individual issuers from its directory
# catalog, never a whole market.
COMPANY_MATERIAL_SCOPE = {
    "jydb": ("filings", ("A_SHARE",), "market"),
    "hkex": ("filings", ("HK",), "market"),
    "sec": ("filings", ("US",), "market"),
    "company_ir": ("filings", COMPANY_MARKETS, "issuer_catalog"),
    "tushare_corpus": ("research", ("A_SHARE",), "market"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bootstrap_import_path() -> None:
    configured = os.environ.get("IR_SEARCH_PATH", "").strip()
    if configured:
        absolute = os.path.abspath(os.path.expanduser(configured))
        if absolute not in sys.path:
            sys.path.insert(0, absolute)


def _load_catalog() -> tuple[dict[str, Any], Any]:
    _bootstrap_import_path()
    from ir_search import list_capabilities, source_configuration_status

    catalog = list_capabilities()
    return catalog, source_configuration_status()


def _company_markets(numeric: list[dict[str, Any]], materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: dict[tuple[str, str], list[dict[str, Any]]] = {
        (market, section): [] for market in COMPANY_MARKETS for section in COMPANY_SECTIONS
    }

    def notes(item: dict[str, Any]) -> list[str]:
        return [str(note) for note in (item.get("coverage_notes") or [])][:6]

    for item in numeric:
        dataset = str(item.get("dataset") or "")
        for section, datasets in COMPANY_SECTION_DATASETS.items():
            if dataset not in datasets:
                continue
            for market in item.get("markets") or []:
                if (str(market), section) in found:
                    found[(str(market), section)].append({
                        "provider": str(item.get("provider")),
                        "capability": dataset,
                        "frequencies": [str(value) for value in (item.get("frequencies") or [])],
                        "scope": "market",
                        "notes": notes(item),
                    })
    for item in materials:
        provider = str(item.get("provider") or "")
        if provider not in COMPANY_MATERIAL_SCOPE:
            continue
        section, markets, scope = COMPANY_MATERIAL_SCOPE[provider]
        for market in markets:
            found[(market, section)].append({
                "provider": provider,
                "capability": ", ".join(str(value) for value in (item.get("material_types") or [])),
                "frequencies": [],
                "scope": scope,
                "notes": notes(item),
            })

    result = []
    for market in COMPANY_MARKETS:
        sections = []
        for section in COMPANY_SECTIONS:
            sources = sorted(found[(market, section)], key=lambda source: source["scope"] != "market")
            sections.append({"id": section, "status": "partial" if sources else "unavailable", "sources": sources})
        result.append({
            "id": market,
            "status": "partial" if any(section["sources"] for section in sections) else "unavailable",
            "sections": sections,
        })
    return result


def _capability_modules(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    numeric = catalog.get("capabilities") or []
    materials = (catalog.get("materials") or {}).get("capabilities") or []
    datasets = {str(item.get("dataset")) for item in numeric if item.get("dataset")}
    markets = {
        str(market)
        for item in numeric
        for market in (item.get("markets") or [])
    }
    material_providers = {str(item.get("provider")) for item in materials if item.get("provider")}

    def module(module_id: str, label: str, status: str, summary: str, **details: Any) -> dict[str, Any]:
        return {
            "id": module_id,
            "label": label,
            "status": status,
            "summary": summary,
            "details": details,
        }

    macro_status = "partial" if "macro_series" in datasets else "unavailable"
    eq_markets = sorted(markets.intersection({"A_SHARE", "US", "HK"}))
    eq_status = "partial" if eq_markets else "unavailable"
    commodity_status = "partial" if markets.intersection({"CN_FUTURES", "CN_OPTIONS"}) else "unavailable"
    company_sources = sorted(material_providers.intersection({"jydb", "sec", "hkex", "company_ir"}))
    company_status = "partial" if company_sources or "financial_statements" in datasets else "unavailable"
    research_status = "ready" if materials else "unavailable"
    fx_status = "partial" if "macro_series" in datasets else "unavailable"
    fund_status = "partial" if datasets.intersection({"fund_profile", "fund_nav", "fund_holdings", "fund_exchange_daily"}) else "unavailable"

    return [
        module("overview", "Overview", "partial", "Capability-aware overview; live dashboard widgets are mapped separately."),
        module("macro", "Macro", macro_status, "Global macro series and macro-to-asset research surface.", datasets=sorted(datasets.intersection({"macro_series"}))),
        module("sector", "Sector", "planned", "Shenwan industry workspace; structure and constituents are not yet registered."),
        module("eq", "Equities", eq_status, "Equity coverage is market-specific and not a full market terminal.", markets=eq_markets, fundCoverage=fund_status),
        module("fi", "Fixed Income", "unavailable", "No unified fixed-income dataset is registered in the current ir_search catalog."),
        module("fx", "FX", fx_status, "FX observations may be available through curated macro series; spot/forward/option coverage is not unified."),
        module("comdty", "Comdty", commodity_status, "Current coverage is concentrated in Chinese futures and options.", markets=sorted(markets.intersection({"CN_FUTURES", "CN_OPTIONS"}))),
        module("companies", "Companies", company_status, "Financial statements and official/company materials vary by market.", sources=company_sources, markets=_company_markets(numeric, materials)),
        module("research", "Research", research_status, "Material search and retrieval are available through explicit user-selected providers.", providers=sorted(material_providers)),
        module("calendar", "Calendar", "planned", "A unified macro, earnings, policy and contract calendar is not yet registered."),
        module("watchlists", "Watchlists", "local", "Watchlists belong to IR System and remain independent of ir_search."),
        module("data", "Data Center", "ready", "Capability and source diagnostics are available.", datasets=sorted(datasets), providers=sorted(material_providers)),
    ]


def _capabilities() -> dict[str, Any]:
    catalog, configuration = _load_catalog()
    return {
        "protocol": PROTOCOL,
        "provider": "ir_search",
        "label": "ir_search Adapter",
        "status": "ready",
        "mode": "external",
        "fetchedAt": _now(),
        "upstreamSchemaVersion": catalog.get("schema_version"),
        "modules": _capability_modules(catalog),
        "configuration": configuration,
        "diagnostics": [
            "Capability registration does not prove that credentials, network access, or a live request will succeed.",
            "Material providers remain opt-in and must be explicitly selected for each research workflow.",
        ],
    }


DERIVATIVES_METHODS = {"derivatives.basis", "derivatives.options_catalog", "derivatives.options_surface", "derivatives.options_vix"}


def _derivatives_fetch():
    """ir_search access for ir_derivatives; one registry per process, cursor paging to completion.

    返回 {records, diagnostics, status, truncated, failed}：
    - truncated：行级截断——游标 12 页预算耗尽仍有剩余，或续页因无显式 provider 被拒。
      注意 ir_search 的 incomplete_page 覆盖「页满待续」和「页含 UPSTREAM_SCHEMA 诊断（如部分
      标的无行）」两种情况，不能等同截断；中间页满页噪音不上报。
    - failed：运营性失败（网络/超时/预算/凭证/配额等 failure_kind，或页状态 error/unavailable）。
      UPSTREAM_SCHEMA 与 NONE 属内容信息（如上市前合约无行），不算失败。
    消费方据 truncated/failed 决定可否落缓存；status 保留最差页状态用于诊断展示。"""
    _bootstrap_import_path()
    from ir_search import DataRequest, get_data
    from ir_search.context import RequestContext
    from ir_search.models import FailureKind
    from ir_search.registry import build_data_registry

    registry = build_data_registry()
    CONTENT_KINDS = {FailureKind.NONE, FailureKind.UPSTREAM_SCHEMA}
    SEVERITY = {"ok": 0, "partial": 1, "unavailable": 2, "error": 3}

    def fetch(dataset, symbols, start, end, *, market, provider=None, frequency=None, adjustment=None):
        records, diagnostics, cursor = [], [], None
        worst, truncated, failed = "ok", False, False
        for _ in range(12):
            result = get_data(
                DataRequest(dataset, symbols=list(symbols), start=start, end=end, market=market, frequency=frequency,
                            adjustment=adjustment, provider=provider, limit=5000, cursor=cursor),
                registry=registry, context=RequestContext(timeout_seconds=60, max_operations=40))
            records.extend(result.records)
            page_codes = [d.code for d in result.diagnostics]
            diagnostics.extend(page_codes)
            if "pagination_requires_explicit_provider" in page_codes:
                truncated = True  # 请求了续页但被拒：此前各页必然不完整
            if any(d.failure_kind not in CONTENT_KINDS for d in result.diagnostics):
                failed = True
            page_status = result.status.value
            if page_status in ("error", "unavailable"):
                failed = True
            if SEVERITY.get(page_status, 3) > SEVERITY[worst]:
                worst = page_status
            cursor = result.next_cursor
            if not cursor:
                break
        else:
            truncated = True  # 页预算耗尽仍有余页
        if truncated and worst == "ok":
            worst = "partial"
        return {"records": records, "diagnostics": sorted(set(diagnostics)), "status": worst,
                "truncated": truncated, "failed": failed}

    return fetch


def _derivatives(method: str, params: dict[str, Any]) -> dict[str, Any]:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from ir_derivatives import service

    allowed = {
        "derivatives.basis": {"years"} | {f"{k}_{p}" for k in ("rf", "div", "years") for p in ("IH", "IF", "IC", "IM")},
        "derivatives.options_catalog": {"exchange", "date"},
        "derivatives.options_surface": {"exchange", "product", "date", "rate"},
        "derivatives.options_vix": {"years"},
    }[method]
    if set(params) - allowed:
        raise ValueError("Unsupported derivatives parameter")
    cache = os.environ.get("IR_SYSTEM_DERIVATIVES_CACHE", "").strip() or None
    ctx = service.Context(_derivatives_fetch(), cache_dir=cache)
    if method == "derivatives.basis":
        # 每个品种可用 rf_<P>/div_<P>/years_<P> 覆盖；缺省 = Shibor3M(10) / Wind 指数股息率 / 全局 years。
        overrides = {}
        for p in ("IH", "IF", "IC", "IM"):
            ov = {k: params[f"{k}_{p}"] for k in ("rf", "div", "years") if params.get(f"{k}_{p}") is not None}
            if ov:
                overrides[p] = ov
        return service.basis_monitor(ctx, years=params.get("years", 3.0), overrides=overrides)
    if method == "derivatives.options_catalog":
        return service.options_catalog(ctx, str(params.get("exchange") or ""), params.get("date"))
    if method == "derivatives.options_vix":
        # IR_SYSTEM_VIX_UNDERLYINGS（逗号分隔标的代码）与 IR_SYSTEM_VIX_SINCE（YYYY-MM-DD，构建起点上移）
        # 是测试/诊断钩子：限定 VIX 构建范围，生产界面不传，默认全历史（自各品种上市日）全标的。
        sel = os.environ.get("IR_SYSTEM_VIX_UNDERLYINGS", "").strip()
        picked = [s.strip() for s in sel.split(",") if s.strip()] or None
        since_raw = os.environ.get("IR_SYSTEM_VIX_SINCE", "").strip()
        since = date.fromisoformat(since_raw) if since_raw else None
        return service.options_vix(ctx, years=params.get("years", 3.0), underlyings=picked, since=since)
    return service.options_surface(ctx, str(params.get("exchange") or ""), str(params.get("product") or ""),
                                   params.get("date"), params.get("rate", 0.015))


def handle(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("protocol") != PROTOCOL:
        raise ValueError("provider protocol mismatch")
    method = request.get("method")
    if method == "system.capabilities":
        return _capabilities()
    if method in DERIVATIVES_METHODS:
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("Invalid derivatives parameters")
        return _derivatives(method, params)
    if method in {"archive.status", "archive.index", "archive.search", "archive.read", "archive.parse", "archive.asset", "archive.audio_list"}:
        _bootstrap_import_path()
        import ir_search
        root = os.environ.get("IR_SEARCH_LOCAL_ARCHIVE_ROOT", "").strip()
        if not root:
            raise ValueError("请先在 Data Center 设置本地归档目录")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("Invalid archive parameters")
        def envelope(result):
            return {"archiveSchemaVersion": 1, **result}
        if method == "archive.audio_list":
            return envelope(ir_search.list_local_audio(root, limit=30))
        if method == "archive.status":
            return envelope(ir_search.local_archive_status(root))
        if method == "archive.index":
            return envelope(ir_search.index_local_archive(root))
        if method == "archive.search":
            allowed = {"query", "source", "collection_id", "start", "end", "kind", "limit", "offset", "include_unknown_dates"}
            if set(params) - allowed:
                raise ValueError("Unsupported archive filter")
            return envelope(ir_search.search_local_archive(root, **params))
        if method == "archive.read":
            return envelope(ir_search.read_local_archive(root, params.get("id"), offset=params.get("offset", 0)))
        if method == "archive.parse":
            # One file per desktop request: timeouts cannot abandon a long batch.
            return envelope(ir_search.parse_local_archive(root, limit=1))
        if method == "archive.asset":
            return envelope(ir_search.resolve_local_archive_asset(root, params.get("id")))
    raise ValueError(f"unsupported method: {method}")


def main() -> int:
    try:
        raw = sys.stdin.readline()
        request = json.loads(raw)
        response = {"protocol": PROTOCOL, "ok": True, "result": handle(request)}
    except Exception as exc:  # Adapter boundary must return a structured error.
        response = {
            "protocol": PROTOCOL,
            "ok": False,
            "error": {
                "code": "adapter_error",
                "message": str(exc),
                "type": type(exc).__name__,
            },
        }
        if os.environ.get("IR_SYSTEM_ADAPTER_DEBUG") == "1":
            response["error"]["traceback"] = traceback.format_exc(limit=8)
    sys.stdout.write(json.dumps(response, ensure_ascii=False, default=str))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
