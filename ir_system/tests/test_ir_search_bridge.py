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
