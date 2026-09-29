import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('ir_search_bridge', Path(__file__).parents[1] / 'adapters/ir_search_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def company_markets(catalog):
    module = next(m for m in bridge._capability_modules(catalog) if m['id'] == 'companies')
    return {market['id']: {s['id']: s for s in market['sections']} for market in module['details']['markets']}, module


def test_company_sections_follow_registered_market_scope():
    catalog = {
        'capabilities': [
            {'dataset': 'securities', 'provider': 'fmp', 'markets': ['US'], 'frequencies': ['snapshot'], 'coverage_notes': ['US tickers only']},
            {'dataset': 'financial_statements', 'provider': 'jydb', 'markets': ['A_SHARE'], 'frequencies': ['report']},
            {'dataset': 'prices_daily', 'provider': 'jydb', 'markets': ['A_SHARE'], 'frequencies': ['1d']},
            {'dataset': 'securities', 'provider': 'other', 'markets': ['CN_FUND']},
        ],
        'materials': {'capabilities': [
            {'provider': 'company_ir', 'material_types': ['document']},
            {'provider': 'hkex', 'material_types': ['announcement'], 'coverage_notes': ['exact HK code']},
            {'provider': 'wechat', 'material_types': ['article']},
        ]},
    }
    markets, module = company_markets(catalog)
    assert list(markets) == ['A_SHARE', 'HK', 'US']
    assert [m['status'] for m in module['details']['markets']] == ['partial', 'partial', 'partial']
    assert markets['US']['search']['sources'] == [{'provider': 'fmp', 'capability': 'securities', 'frequencies': ['snapshot'], 'scope': 'market', 'notes': ['US tickers only']}]
    assert markets['A_SHARE']['search']['status'] == 'unavailable'
    assert [s['provider'] for s in markets['A_SHARE']['financials']['sources']] == ['jydb']
    assert [(s['provider'], s['scope']) for s in markets['HK']['filings']['sources']] == [('hkex', 'market'), ('company_ir', 'issuer_catalog')]
    assert all(markets[m]['events']['status'] == 'unavailable' for m in markets)
    providers = {src['provider'] for market in markets.values() for section in market.values() for src in section['sources']}
    assert providers == {'fmp', 'jydb', 'hkex', 'company_ir'}


def test_empty_catalog_reports_every_market_unavailable():
    markets, module = company_markets({})
    assert module['status'] == 'unavailable'
    assert [m['status'] for m in module['details']['markets']] == ['unavailable'] * 3
    assert all(section['sources'] == [] for market in markets.values() for section in market.values())


# ---------------------------------------------------------------- derivatives fetch paging

import sys
import types


def _fake_sdk(monkeypatch, pages):
    """pages: [(records, codes, status, next_cursor)]；返回每次调用见到的 cursor 序列。"""
    calls = []

    class _Status:
        def __init__(self, value):
            self.value = value

    class _Diag:
        def __init__(self, code, failure_kind="none"):
            self.code = code
            self.failure_kind = failure_kind

    class _Result:
        def __init__(self, records, codes, status, cursor):
            self.records = records
            self.diagnostics = [_Diag(c) for c in codes]
            self.status = _Status(status)
            self.next_cursor = cursor

    class _Request:
        def __init__(self, dataset, **kwargs):
            self.dataset = dataset
            self.__dict__.update(kwargs)

    def get_data(request, registry=None, context=None):
        calls.append(request.cursor)
        records, codes, status, cursor = pages[len(calls) - 1]
        return _Result(records, codes, status, cursor)

    sdk = types.ModuleType("ir_search")
    sdk.DataRequest = _Request
    sdk.get_data = get_data
    models_mod = types.ModuleType("ir_search.models")
    models_mod.FailureKind = type("FailureKind", (), {"NONE": "none", "UPSTREAM_SCHEMA": "upstream_schema"})
    ctx_mod = types.ModuleType("ir_search.context")
    ctx_mod.RequestContext = type("RC", (), {"__init__": lambda self, **kw: None})
    reg_mod = types.ModuleType("ir_search.registry")
    reg_mod.build_data_registry = lambda: None
    monkeypatch.setitem(sys.modules, "ir_search", sdk)
    monkeypatch.setitem(sys.modules, "ir_search.context", ctx_mod)
    monkeypatch.setitem(sys.modules, "ir_search.registry", reg_mod)
    monkeypatch.setitem(sys.modules, "ir_search.models", models_mod)
    return calls


def test_derivatives_fetch_paging_noise_is_not_truncation(monkeypatch):
    """中间页满页（incomplete_page/partial）但游标走完：行完整，truncated/failed 都为 False。"""
    calls = _fake_sdk(monkeypatch, [
        ([{"r": 1}], ["incomplete_page"], "partial", "c1"),
        ([{"r": 2}], ["incomplete_page"], "partial", "c2"),
        ([{"r": 3}], [], "ok", None),
    ])
    fetch = bridge._derivatives_fetch()
    out = fetch("index_daily", ["000300.SH"], "2010-04-01", "2026-09-28", market="CN_INDEX")
    assert out["truncated"] is False and out["failed"] is False
    assert [r["r"] for r in out["records"]] == [1, 2, 3]
    assert calls == [None, "c1", "c2"]


def test_derivatives_fetch_incomplete_page_diag_is_not_truncation(monkeypatch):
    """末页 incomplete_page 但无游标剩余（ir_search 对「部分标的无行」也报 incomplete_page）：
    属内容信息，不是行级截断——truncated=False，消费方才敢落缓存。"""
    _fake_sdk(monkeypatch, [([{"r": 1}], ["incomplete_page", "requested_symbols_without_rows"], "partial", None)])
    out = bridge._derivatives_fetch()("futures_daily", ["IF1005.CFE"], "2010-04-16", "2010-05-21", market="CN_FUTURES")
    assert out["truncated"] is False and out["failed"] is False
    assert out["status"] == "partial"


def test_derivatives_fetch_refused_paging_is_truncation(monkeypatch):
    """续页因无显式 provider 被拒（0 行、无游标）：此前各页不完整，必须标记截断而不是静默完整。"""
    _fake_sdk(monkeypatch, [
        ([{"r": 1}], ["incomplete_page"], "partial", "c1"),
        ([], ["pagination_requires_explicit_provider"], "ok", None),
    ])
    out = bridge._derivatives_fetch()("index_daily", ["000300.SH"], "2010-04-01", "2026-09-28", market="CN_INDEX")
    assert out["truncated"] is True
    assert out["status"] == "partial"


def test_derivatives_fetch_propagates_error_status(monkeypatch):
    _fake_sdk(monkeypatch, [([], ["mysql_connection_failed"], "error", None)])
    out = bridge._derivatives_fetch()("index_daily", ["000300.SH"], "2010-04-01", "2026-09-28", market="CN_INDEX")
    assert out["status"] == "error" and out["failed"] is True
