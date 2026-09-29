"""Unit tests for the derivatives engine (adapters/ir_derivatives). No network or ir_search access."""
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'adapters'))

from ir_derivatives import basis, black76, chain, commodity, essvi, svi, surface  # noqa: E402
from ir_derivatives.timegrid import TradingCalendar, VarianceClock, estimate_omega_pooled  # noqa: E402


# ---------------------------------------------------------------- black76

def test_black76_put_call_parity():
    F, K, tau, sigma, D = 100.0, 95.0, 0.4, 0.25, 0.995
    call = black76.price(F, K, tau, sigma, D, True)
    put = black76.price(F, K, tau, sigma, D, False)
    assert abs((call - put) - D * (F - K)) < 1e-10


def test_implied_vol_roundtrip_and_bounds():
    F, tau, D = 3000.0, 0.1, 0.999
    K = np.array([2700.0, 3000.0, 3300.0])
    sigma = np.array([0.30, 0.22, 0.26])
    for flag in (True, False):
        price = black76.price(F, K, tau, sigma, D, flag)
        iv = black76.implied_vol(price, F, K, tau, D, flag)
        assert np.max(np.abs(iv - sigma)) < 1e-8
    # 低于内在价值或高于上界的价格必须返回 NaN，不能给出假 IV
    intrinsic = D * max(F - 3000.0, 0.0)
    assert np.isnan(black76.implied_vol(np.array([intrinsic * 0.5]), F, np.array([3000.0]), tau, D, True)[0])
    assert np.isnan(black76.implied_vol(np.array([D * F * 1.01]), F, np.array([3000.0]), tau, D, True)[0])


def test_greeks_finite_difference():
    F, K, tau, sigma, D, t_cal = 100.0, 105.0, 0.3, 0.2, 0.994, 0.3
    g = black76.greeks(F, K, tau, sigma, D, True, t_cal)
    h = 1e-4
    fd_delta = (black76.price(F + h, K, tau, sigma, D, True) - black76.price(F - h, K, tau, sigma, D, True)) / (2 * h)
    fd_vega = (black76.price(F, K, tau, sigma + h, D, True) - black76.price(F, K, tau, sigma - h, D, True)) / (2 * h)
    fd_gamma = (black76.price(F + 1e-2, K, tau, sigma, D, True) - 2 * black76.price(F, K, tau, sigma, D, True)
                + black76.price(F - 1e-2, K, tau, sigma, D, True)) / 1e-4
    assert abs(g["delta"] - fd_delta) < 1e-7
    assert abs(g["vega"] - fd_vega) < 1e-4
    assert abs(g["gamma"] - fd_gamma) < 1e-6
    # 期货 rho（持有远期不变）= -t_cal * price
    assert abs(g["rho_forward"] + t_cal * g["price"]) < 1e-10


def test_american_premium_and_roundtrip():
    F, K, tau, sigma, t_cal, r = 100.0, 95.0, 0.5, 0.25, 0.5, 0.03
    tree = black76.crr_tree(np.array([F]), np.array([K]), np.array([tau]), np.array([sigma]), np.array([t_cal]), r,
                            np.array([False]), 300)
    assert tree.american[0] >= tree.european[0] - 1e-10
    assert tree.premium[0] > 0.01  # 期货美式看跌有明显的提前行权价值
    iv, premium = black76.american_implied_vol(tree.american, np.array([F]), np.array([K]), np.array([tau]),
                                               np.array([t_cal]), r, np.array([False]), 300)
    assert abs(iv[0] - sigma) < 5e-4
    assert premium[0] == pytest.approx(tree.premium[0], rel=0.02)
    g = black76.american_greeks(np.array([F]), np.array([K]), np.array([tau]), np.array([sigma]), np.array([t_cal]), r,
                                np.array([False]), 200)
    euro = black76.greeks(F, K, tau, sigma, math.exp(-r * t_cal), False, t_cal)
    assert g["price"][0] >= euro["price"]
    assert g["delta"][0] < euro["delta"]  # 美式看跌 delta 更负


# ---------------------------------------------------------------- timegrid

def weekdays(start, end):
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def test_variance_clock_counts_holidays():
    days = weekdays(date(2026, 9, 1), date(2027, 12, 31))
    cal = TradingCalendar(days)
    clock = VarianceClock(cal, date(2026, 9, 24), 0.1)
    tau = clock.tau(date(2026, 10, 16))
    trading, other = cal.count(date(2026, 9, 24), date(2026, 10, 16))
    assert trading > 0 and other == 6  # 合成日历只含周末
    assert tau == pytest.approx((trading + 0.1 * other) / clock.annual_weight)
    assert clock.tau(date(2026, 9, 24)) == 0.0
    dtau, dcal = clock.one_day_step()
    assert dtau > 0 and dcal >= 1 / 365 - 1e-9


def test_estimate_omega_recovers_known_weight():
    rng = np.random.default_rng(7)
    days = weekdays(date(2022, 1, 3), date(2025, 12, 31))
    # 在每个周五后人工插入 3 天空白，收益方差按 1 + omega*n 缩放
    dates, prev = [], days[0]
    closes = [100.0]
    omega_true = 0.4
    for d in days[1:]:
        gap = 3 if (d - prev).days > 3 and d.month % 3 == 0 else max((d - prev).days - 1, 0)
        var = 0.0004 * (1 + omega_true * gap)
        closes.append(closes[-1] * math.exp(rng.normal(0, math.sqrt(var))))
        dates.append(d)
        prev = d
    out = estimate_omega_pooled([(days, closes)])
    assert abs(out["omega"] - omega_true) < 0.35
    assert out["observations"] > 500


# ---------------------------------------------------------------- svi / essvi

def test_svi_zeliade_recovers_params():
    p_true = (0.01, 0.1, -0.4, 0.02, 0.15)
    k = np.linspace(-0.4, 0.3, 25)
    tau = 0.3
    sigma_mkt = np.sqrt(svi.raw_w(k, p_true) / tau)
    lam = np.full(len(k), 1 / 0.005 ** 2)
    p, _ = svi.fit_zeliade(k, sigma_mkt, lam, tau)
    assert np.max(np.abs(np.sqrt(svi.raw_w(k, p) / tau) - sigma_mkt)) < 1e-5
    check = svi.check_slice(p, (-0.5, 0.4))
    assert check["butterfly_ok"]
    assert all(c <= 2.0 + 1e-9 for c in check["wing_slopes"])  # Lee 翼部上界


def test_svi_check_flags_bad_slice():
    # 左翼斜率超过 Lee 界 2 的切片必须在 g(+/-inf) 上失败
    bad = (0.02, 2.6, 0.9, 0.0, 0.1)
    check = svi.check_slice(bad, (-0.5, 0.5))
    assert not check["butterfly_ok"]
    assert min(check["g_left_inf"], check["g_right_inf"]) < 0


def test_essvi_calendar_condition():
    # 同一 rho、phi 恒定（psi 随 theta 增长）的 SSVI 式切片对不交叉
    ok, _ = essvi.calendar_ok(0.04, -0.7, 0.20, 0.042, -0.7, 0.21)
    assert ok
    assert essvi.min_calendar_gap((0.04, -0.7, 0.20), (0.042, -0.7, 0.21)) > 0
    ok_decreasing, _ = essvi.calendar_ok(0.05, -0.7, 0.20, 0.04, -0.7, 0.30)
    assert not ok_decreasing  # theta 下降必然日历套利
    # psi 涨五成而 theta 只涨 5%：中段实际交叉（数值判据 min gap ≈ -0.0023），条件（3）必须拒绝
    crossing, _ = essvi.calendar_ok(0.04, -0.7, 0.20, 0.042, -0.7, 0.30)
    assert not crossing
    assert essvi.min_calendar_gap((0.04, -0.7, 0.20), (0.042, -0.7, 0.30)) < 0
    # tex 附录反例：psi 倒挂且 rho psi 差超限
    bad, _ = essvi.calendar_ok(0.04, -0.7, 0.30, 0.042, 0.9, 0.21)
    assert not bad


def test_essvi_surface_interpolation_properties():
    taus = np.array([0.1, 0.25])
    params = np.array([[0.004, -0.4, 0.05], [0.01, -0.4, 0.08]])
    surf = essvi.EquitySurface(taus, params)
    k = np.linspace(-0.3, 0.2, 15)
    # 节点上等于切片
    assert np.allclose(surf.w(k, 0.1), essvi.essvi_w(k, *params[0]), atol=1e-6)
    # 切片之间日历单调（价格空间插值的保证）
    w1, w_mid, w2 = surf.w(k, 0.1), surf.w(k, 0.17), surf.w(k, 0.25)
    assert np.all(w_mid >= w1 - 1e-6) and np.all(w2 >= w_mid - 1e-6)
    # 零期限外推到内在价值
    w0 = surf.w(np.array([-0.2, 0.2]), 1e-6)
    assert w0[0] < w1[0] and w0[1] < w1[1]


def test_essvi_delta_points_and_stats():
    stats = essvi.slice_stats(0.01, -0.5, 0.08, 0.25)
    assert stats["atm_vol"] == pytest.approx(math.sqrt(0.01 / 0.25))
    assert stats["atm_skew"] == pytest.approx(-0.5 * 0.08 / (2 * math.sqrt(0.01 * 0.25)))
    assert stats["vol_put_25d"] > stats["atm_vol"] > stats["vol_call_25d"]  # 负偏度
    assert stats["rr_25d"] == pytest.approx(stats["vol_call_25d"] - stats["vol_put_25d"])


# ---------------------------------------------------------------- chain

def option_row(contract, series, strike, call, close, month, size=10000.0, code=None, expiry="2026-12-23"):
    return {"symbol": "SSE", "contract": contract, "series_id": series, "option_type": "call" if call else "put",
            "strike": strike, "contract_size": size, "contract_month": month, "trading_code": code or contract,
            "listing_date": "2026-01-01", "last_trading_date": expiry, "trade_date": "2026-09-24", "open": None,
            "high": None, "low": None, "close": close, "settlement": close, "previous_settlement": None,
            "volume": 100.0, "open_interest": 10.0, "price_status": "traded"}


def test_chain_classify_and_normalize():
    assert chain.classify("510050OP.SH", "202612")["family"] == "etf"
    idx = chain.classify("MO.CFE", "202610")
    assert idx["family"] == "index" and idx["underlying"] == "IM2610.CFE"
    m = chain.classify("AO2701MS.DCE", None)
    assert m["serial"] and m["underlying"] == "A2701.DCE"
    ap = chain.classify("APO611.CZC", None)
    assert ap["underlying"] == "AP611.CZC"
    rows = [option_row("c1", "510050OP.SH", 2.8, True, 0.1, "202612"),
            option_row("c2", "510050OP.SH", 2.8, False, 0.05, "202612"),
            option_row("c3", "510050OP.SH", 2.7586, True, 0.12, "202612", size=10180.0, code="510050C2612A02758")]
    slices = chain.normalize(rows)
    assert len(slices) == 1 and len(slices[0].options) == 3
    adjusted = [o for o in slices[0].options if o.adjusted]
    assert len(adjusted) == 1


def test_tick_inference_and_quote_filter():
    assert chain.infer_tick([0.5, 1.0, 67.5, 120.0]) == 0.5
    assert chain.infer_tick([0.0901, 0.12, 0.1769]) == 0.0001
    assert chain.infer_tick([3.2, 4.6, 12.8]) == 0.2
    assert chain.infer_tick([]) is None


def test_pcp_forward_recovery():
    F_true, D = 3.0, 0.998
    rows = []
    for K in (2.8, 2.9, 3.0, 3.1, 3.2):
        call = max(F_true - K, 0) + 0.02
        put = call - (F_true - K)
        rows.append(option_row(f"c{K}", "510050OP.SH", K, True, call * D, "202612"))
        rows.append(option_row(f"p{K}", "510050OP.SH", K, False, put * D, "202612"))
    options = chain.normalize(rows)[0].options
    out = chain.pcp_forward(options, D)
    assert out and abs(out["forward"] - F_true) < 1e-6


# ---------------------------------------------------------------- basis

def test_basis_metrics_match_reference_screenshot():
    # 参考截图 2026-09-25 采样：000852.SH 收 7570.1448，IM2610 收 7528.0，天数 22 → 9.29%
    m = basis.metrics(7570.1448, 7528.0, 22)
    assert round(m["basis"], 4) == 42.1448
    assert round(m["annualized"] * 100, 2) == 9.29
    assert round(m["daily"], 2) == 1.92
    assert round(m["per_point"], 2) == 4.54
    assert m["basis"] == m["basis_raw"] and m["annualized"] == m["annualized_raw"]  # carry=0 时退化为原始口径


def test_basis_metrics_carry_adjustment():
    # carry = r − q = −1%：合理价 F* = S·(1−0.01·22/365)，显示基差 = F* − F = 原始基差 + S·carry·days/365
    m = basis.metrics(7570.1448, 7528.0, 22, carry=-0.01)
    shift = 7570.1448 * (-0.01) * 22 / 365
    assert m["basis_raw"] == pytest.approx(42.1448)
    assert m["basis"] == pytest.approx(42.1448 + shift)
    assert m["annualized"] == pytest.approx(m["basis"] / 7528.0 * 365 / 22)
    assert m["annualized"] < m["annualized_raw"]  # 股息率高于利率时，部分贴水被合理持有成本解释


def test_window_samples():
    assert basis.window_samples(3) == 750
    assert basis.window_samples(0.1) == 125  # clamp 到 0.5 年
    assert basis.window_samples(99) == 2500  # clamp 到 10 年


def test_third_friday_and_listed_months():
    assert basis.third_friday(2026, 10) == date(2026, 10, 16)
    cal = TradingCalendar(weekdays(date(2026, 9, 1), date(2027, 6, 30)))
    months = basis.listed_months(date(2026, 9, 24), cal)
    assert months == ["2610", "2611", "2612", "2703"]
    # 到期日当天切换到次月
    months = basis.listed_months(date(2026, 10, 17), cal)
    assert months == ["2611", "2612", "2703", "2706"]


def test_percentile_block_definition():
    samples = [{"date": f"2026-01-{d:02d}", "annualized": float(d)} for d in range(1, 21)]
    out = basis.percentile_block(samples, 15.0, "2026-01-21")
    assert out["percentile"] == 0.75
    assert out["previous"] == 20.0 and out["previous_date"] == "2026-01-20"
    assert out["min"] == 1.0 and out["max"] == 20.0
    assert out["label"] == "略高于中枢"
    # window 截断：只看最后 5 个样本（16..20），当前 15 全部在其之下
    out5 = basis.percentile_block(samples, 15.0, "2026-01-21", window=5)
    assert out5["percentile"] == 0.0 and out5["count"] == 5 and out5["target"] == 5
    assert out5["min"] == 16.0 and out5["first_date"] == "2026-01-16"


def test_build_product_uses_eod_fallback():
    today = datetime(2026, 9, 25, 15, 0)  # 中秋休市
    cal = TradingCalendar(weekdays(date(2026, 9, 1), date(2027, 6, 30)))
    index_eod = {date(2026, 9, 23): 7745.5576, date(2026, 9, 24): 7570.1448}
    futures_eod = {("IM2610", date(2026, 9, 23)): 7710.8, ("IM2610", date(2026, 9, 24)): 7528.0}
    out = basis.build_product("IM", now=today, calendar=cal, index_eod=index_eod, index_live=None,
                              futures_eod=futures_eod, futures_live={})
    contract = out["contracts"][0]
    assert contract["code"] == "IM2610" and contract["source"] == "wind_eod"
    assert round(contract["annualized"] * 100, 2) == 9.29
    assert round(contract["change"], 1) == -182.8
    assert out["index"]["source"] == "wind_eod"
    assert out["index_history"] == [["2026-09-23", 7745.5576], ["2026-09-24", 7570.1448]]


def test_build_product_carry_consistent_basis_change():
    today = datetime(2026, 9, 25, 15, 0)
    cal = TradingCalendar(weekdays(date(2026, 9, 1), date(2027, 6, 30)))
    index_eod = {date(2026, 9, 23): 7745.5576, date(2026, 9, 24): 7570.1448}
    futures_eod = {("IM2610", date(2026, 9, 23)): 7710.8, ("IM2610", date(2026, 9, 24)): 7528.0}
    out = basis.build_product("IM", now=today, calendar=cal, index_eod=index_eod, index_live=None,
                              futures_eod=futures_eod, futures_live={}, carry=0.01, samples=250)
    contract = out["contracts"][0]
    days, prev_days = 22, 24  # IM2610 到期 2026-10-16；9/25 采样 22 天，9/23 收盘对应 24 天
    cur = 42.1448 + 7570.1448 * 0.01 * days / 365
    prev = (7745.5576 - 7710.8) + 7745.5576 * 0.01 * prev_days / 365
    assert contract["basis"] == pytest.approx(cur)
    assert contract["basis_raw"] == pytest.approx(42.1448)
    assert contract["basis_change"] == pytest.approx(cur - prev)
    assert out["percentiles"]["当月"]["count"] >= 1  # 历史与当前同一调整口径


def test_basis_monitor_auto_rates_overrides_and_cache(tmp_path):
    """合成数据走 basis_monitor：自动 rf(Shibor3M-10)/div(指数股息率)、逐品种覆盖、EOD 缓存尾部刷新。"""
    from ir_derivatives import service
    cal_days = weekdays(date(2025, 1, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]
    calls = []

    def fetch(dataset, symbols, start, end, **kwargs):
        calls.append((dataset, start, end))
        if dataset == "trading_calendar":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat()} for d in cal_days if start <= d <= end],
                    "diagnostics": [], "status": "ok"}
        if dataset in ("index_daily", "futures_daily"):
            offset = 0.0 if dataset == "index_daily" else -20.0  # 期货长期贴水 20 点
            rows = [{"symbol": s, "trade_date": d.isoformat(), "close": 4000.0 + i + offset}
                    for s in symbols for i, d in enumerate(trade_days) if start <= d <= end]
            return {"records": rows, "diagnostics": [], "status": "ok"}
        if dataset == "benchmark_rate":
            return {"records": [{"symbol": symbols[0], "trade_date": "2026-09-24", "rate": 1.5}],
                    "diagnostics": [], "status": "ok"}
        if dataset == "index_valuation":
            return {"records": [{"symbol": s, "trade_date": "2026-09-24", "dividend_yield": 2.5} for s in symbols],
                    "diagnostics": [], "status": "ok"}
        return {"records": [], "diagnostics": [], "status": "ok"}  # snapshot / intraday 为空 → 回落 EOD

    now = datetime(2026, 9, 25, 10, 0)
    ctx = service.Context(fetch, now=now, cache_dir=tmp_path)
    out = service.basis_monitor(ctx, products=("IF",), years=1.0)
    prod = out["products"][0]
    carry = prod["carry"]
    assert carry["rf"] == pytest.approx(0.015) and carry["div"] == pytest.approx(0.025)
    assert carry["rf_source"] == {"code": "SHIBOR_3M(10)", "date": "2026-09-24"}
    contract = prod["contracts"][0]
    S, days = prod["index"]["last"], contract["days"]
    # carry = 1.5% − 2.5% = −1%：调整基差 = 原始基差 + S·(−0.01)·days/365
    assert contract["basis"] == pytest.approx(contract["basis_raw"] + S * (0.015 - 0.025) * days / 365)
    assert contract["basis"] < contract["basis_raw"]  # 股息率高于利率，部分贴水被合理解释
    assert all(len(p) == 4 for p in prod["history"]["当月"])  # [date, ann调整, code, ann原始]
    assert prod["percentiles"]["当月"] and prod["percentiles_raw"]["当月"]
    full_pulls = [c for c in calls if c[0] in ("index_daily", "futures_daily")]
    assert full_pulls and all(c[1] <= date(2025, 10, 1) for c in full_pulls)  # 首拉覆盖完整窗口

    calls.clear()
    ctx2 = service.Context(fetch, now=now, cache_dir=tmp_path)
    out2 = service.basis_monitor(ctx2, products=("IF",), years=1.0)
    assert out2["products"][0]["contracts"][0]["basis"] == pytest.approx(contract["basis"])
    refetch = [c for c in calls if c[0] in ("index_daily", "futures_daily")]
    assert refetch and all(c[1] >= date(2026, 9, 1) for c in refetch)  # 第二次只补最近几天尾部

    ctx3 = service.Context(fetch, now=now, cache_dir=tmp_path)
    out3 = service.basis_monitor(ctx3, products=("IF",), years=1.0, overrides={"IF": {"rf": 0.05, "div": 0.0}})
    c3 = out3["products"][0]["contracts"][0]
    assert c3["basis"] == pytest.approx(c3["basis_raw"] + S * 0.05 * c3["days"] / 365)
    assert out3["products"][0]["carry"]["rf_source"] == "override"


def _synthetic_market(trade_days, cal_days, calls, truncate_index=None):
    def fetch(dataset, symbols, start, end, **kwargs):
        calls.append((dataset, tuple(symbols), start, end))
        if dataset == "trading_calendar":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat()} for d in cal_days if start <= d <= end],
                    "diagnostics": [], "status": "ok"}
        if dataset in ("index_daily", "futures_daily"):
            offset = 0.0 if dataset == "index_daily" else -20.0
            rows = [{"symbol": s, "trade_date": d.isoformat(), "close": 4000.0 + i + offset}
                    for s in symbols for i, d in enumerate(trade_days) if start <= d <= end
                    and not (truncate_index == s and d < date(2026, 9, 10))]
            status = "unavailable" if truncate_index in symbols else "ok"
            return {"records": rows, "diagnostics": ["incomplete_page"] if status != "ok" else [], "status": status}
        if dataset == "benchmark_rate":
            return {"records": [{"symbol": symbols[0], "trade_date": "2026-09-24", "rate": 1.5}],
                    "diagnostics": [], "status": "ok"}
        if dataset == "index_valuation":
            return {"records": [{"symbol": s, "trade_date": "2026-09-24", "dividend_yield": 2.5} for s in symbols],
                    "diagnostics": [], "status": "ok"}
        return {"records": [], "diagnostics": [], "status": "ok"}
    return fetch


def test_basis_eod_partial_pull_is_never_cached(tmp_path):
    """被截断的拉取（incomplete_page/unavailable）不得写入缓存，更不能污染后续调用。"""
    from ir_derivatives import service
    cal_days = weekdays(date(2025, 1, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]
    calls = []
    fetch = _synthetic_market(trade_days, cal_days, calls, truncate_index="000300.SH")
    ctx = service.Context(fetch, now=datetime(2026, 9, 25, 10, 0), cache_dir=tmp_path)
    service.basis_monitor(ctx, products=("IF",), years=1.0)
    assert not (tmp_path / "basis-eod-v1.json").exists()  # 部分数据不落盘


def test_basis_eod_self_heals_truncated_cache(tmp_path):
    """缓存缺某指数早期历史时，对该标的单独全量补拉；补全后才写缓存。"""
    from ir_derivatives import service
    cal_days = weekdays(date(2025, 1, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]
    full_start = date(2026, 9, 25) - timedelta(days=int(250 * 1.5) + 40)
    # 预置"中毒"缓存：000016 全量、000300 只有尾部（期货历史完整，与真实截断场景一致）。
    # start 已是全历史锚点（否则直接触发整窗重拉，走不到逐标的补拉路径）。
    index_closes = {("000016.SH", d): 4000.0 + i for i, d in enumerate(trade_days)}
    index_closes.update({("000300.SH", d): 4000.0 + i for i, d in enumerate(trade_days) if d >= date(2026, 9, 18)})
    months = sorted({f"{d.year % 100:02d}{d.month:02d}" for d in trade_days if d >= full_start})
    futures_closes = {(f"IF{m}", d): 3980.0 + i for m in months for i, d in enumerate(trade_days)}
    (tmp_path / "basis-eod-v1.json").write_text(json.dumps(
        {"start": "2010-04-01", "products": ["IF"], "index_symbols": ["000016.SH", "000300.SH"],
         "index": service._encode_closes(index_closes), "futures": service._encode_closes(futures_closes)}))
    calls = []
    fetch = _synthetic_market(trade_days, cal_days, calls)
    ctx = service.Context(fetch, now=datetime(2026, 9, 25, 10, 0), cache_dir=tmp_path)
    out = service.basis_monitor(ctx, products=("IF",), years=1.0)
    healed = [c for c in calls if c[0] == "index_daily" and c[1] == ("000300.SH",)]
    assert any(c[2] <= date(2010, 4, 1) for c in healed)  # 单标的全量补拉
    assert len(out["products"][0]["history"]["当月"]) > 100  # 历史恢复
    assert (tmp_path / "basis-eod-v1.json").exists()


def test_basis_eod_cache_product_coverage(tmp_path):
    """缓存记录覆盖的 products/index_symbols；请求集合超出缓存集合时整窗重拉（子集缓存不能冒充全量）。"""
    from ir_derivatives import service
    cal_days = weekdays(date(2025, 1, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]
    calls = []
    fetch = _synthetic_market(trade_days, cal_days, calls)
    now = datetime(2026, 9, 25, 10, 0)
    service.basis_monitor(service.Context(fetch, now=now, cache_dir=tmp_path), products=("IF",), years=1.0)
    calls.clear()
    # 同集合：只补尾部
    service.basis_monitor(service.Context(fetch, now=now, cache_dir=tmp_path), products=("IF",), years=1.0)
    refetch = [c for c in calls if c[0] == "futures_daily"]
    assert refetch and all(c[2] >= date(2026, 9, 1) for c in refetch)
    calls.clear()
    # 超集合（IF+IC）：缓存不含 IC → 整窗重拉，IC 从上市日 2015-04-16 起
    service.basis_monitor(service.Context(fetch, now=now, cache_dir=tmp_path), products=("IF", "IC"), years=1.0)
    refetch = [c for c in calls if c[0] == "futures_daily"]
    assert any(c[2] <= date(2010, 5, 1) for c in refetch if any(s.startswith("IF") for s in c[1]))
    assert any(c[2] == date(2015, 4, 16) for c in refetch if any(s.startswith("IC") for s in c[1]))


def test_basis_full_history_anchors_and_untrimmed(tmp_path):
    """全历史锚点：IF 期货从 2010-04-16、IM 从 2022-07-22 起拉；指数从 2010-04-01 起；
    history/index_history 返回全历史（不再按分位数窗口截断），分位数仍按窗口。"""
    from ir_derivatives import service
    cal_days = weekdays(date(2024, 6, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]
    calls = []
    fetch = _synthetic_market(trade_days, cal_days, calls)
    now = datetime(2026, 9, 25, 10, 0)
    out = service.basis_monitor(service.Context(fetch, now=now, cache_dir=tmp_path), products=("IF", "IM"), years=1.0)
    fut = [c for c in calls if c[0] == "futures_daily"]
    assert min(c[2] for c in fut if any(s.startswith("IF") for s in c[1])) == date(2010, 4, 16)
    assert min(c[2] for c in fut if any(s.startswith("IM") for s in c[1])) == date(2022, 7, 22)
    idx = [c for c in calls if c[0] == "index_daily"]
    assert min(c[2] for c in idx) <= date(2010, 4, 1)
    prod = next(p for p in out["products"] if p["product"] == "IF")
    assert len(prod["history"]["当月"]) > 250  # 全历史 > 1 年分位窗口（合成数据自 2024-06 起）
    assert len(prod["index_history"]) > 250
    assert prod["percentiles"]["当月"]["count"] <= 250  # 分位数仍按「过去 1 年」窗口


# ---------------------------------------------------------------- vix

def test_vix_expiry_variance_recovers_flat_smile():
    """平面微笑：所有行权价同一 IV 时，方差互换公式应恢复 iv²，远期应恢复 PCP 远期。"""
    from ir_derivatives import vix
    F, days, iv, r = 3.0, 30, 0.20, 0.015
    T, D = days / 365, math.exp(-r * days / 365)
    points = []
    for i in range(11):
        K = 2.5 + i * 0.1
        call = float(black76.price(F, K, T, iv, D, True)[0])
        put = float(black76.price(F, K, T, iv, D, False)[0])
        points.append((K, call, put))
    out = vix.expiry_variance(points, days, r)
    assert out and out["forward"] == pytest.approx(F, abs=1e-6)
    assert out["k0"] == 3.0
    assert out["used"] == 11
    # ΔK=0.1（相对步长 3.3%）的黎曼和对凸被积函数有 ~5% 离散化偏差，属方法本身性质
    assert out["sigma2"] == pytest.approx(iv * iv, rel=0.10)
    # 细网格宽范围下公式应精确恢复（截断与离散化误差同时很小）
    fine = [(2.0 + i * 0.02, float(black76.price(F, 2.0 + i * 0.02, T, iv, D, True)[0]),
             float(black76.price(F, 2.0 + i * 0.02, T, iv, D, False)[0])) for i in range(101)]
    out_fine = vix.expiry_variance(fine, days, r)
    assert out_fine["sigma2"] == pytest.approx(iv * iv, rel=0.005)
    # 两个到期同一 IV → 插值后 VIX ≈ 20（含离散化偏差）
    v2 = vix.expiry_variance(points, 61, r)
    assert vix.vix_from_expiries([(30, out), (61, v2)]) == pytest.approx(20.0, abs=1.2)


def test_vix_roll_rule_and_gaps():
    from ir_derivatives import vix
    F, iv, r = 3.0, 0.20, 0.015
    day = date(2026, 9, 24)
    T, D = 30 / 365, math.exp(-r * 30 / 365)
    points = [(2.5 + i * 0.1, float(black76.price(F, 2.5 + i * 0.1, T, iv, D, True)[0]),
               float(black76.price(F, 2.5 + i * 0.1, T, iv, D, False)[0])) for i in range(11)]
    near = day + timedelta(days=5)   # 不足 8 天 → 跳过
    mid = day + timedelta(days=30)
    far = day + timedelta(days=61)
    v = vix.daily_vix(day, {near: points, mid: points, far: points}, r)
    assert v == pytest.approx(20.0, abs=1.2)
    assert vix.daily_vix(day, {near: points}, r) is None            # 全部不足 8 天 → 空
    assert vix.daily_vix(day, {mid: points[:4]}, r) is None         # 有效行权价 < 6 → 空


def test_vix_series_stats():
    from ir_derivatives import vix
    pts = [("2026-09-21", 20.0), ("2026-09-22", 18.0), ("2026-09-23", 22.0)]
    out = vix.series_stats(pts, "2026-09-23")
    assert out["d_vix"] == pytest.approx(4.0)
    assert out["percentile"] == pytest.approx(1.0)
    assert out["min"] == 18.0 and out["first_date"] == "2026-09-21"


def _patch_listing(monkeypatch, **listings):
    """测试用：把指定标的的上市日改到合成数据覆盖的范围（生产值为真实上市日）。"""
    from ir_derivatives import service
    for code, day in listings.items():
        monkeypatch.setitem(service.VIX_UNDERLYINGS, code, {**service.VIX_UNDERLYINGS[code], "listing": day})


def test_options_vix_service_builds_and_caches(tmp_path, monkeypatch):
    """合成 40 个交易日 ETF 期权链：VIX ≈ 20，第二次调用命中缓存不再拉链。"""
    from ir_derivatives import service, vix
    _patch_listing(monkeypatch, **{"510300.SH": date(2026, 1, 1)})
    cal_days = weekdays(date(2026, 1, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]  # 覆盖整个 0.5 年窗口
    F, iv, r = 3.0, 0.20, 0.015
    expiries = (date(2026, 10, 28), date(2026, 11, 25))
    calls = []

    def fetch(dataset, symbols, start, end, **kwargs):
        calls.append((dataset, start, end))
        if dataset == "trading_calendar":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat()} for d in cal_days if start <= d <= end],
                    "diagnostics": [], "status": "ok"}
        if dataset == "options_chain":
            rows = []
            for d in trade_days:
                if not (start <= d <= end):
                    continue
                for expiry in expiries:
                    t_e = (expiry - d).days / 365  # 每个到期用自己的剩余期限定价
                    d_e = math.exp(-r * t_e)
                    for i in range(11):
                        K = 2.5 + i * 0.1
                        for flag in (True, False):
                            price = float(black76.price(F, K, t_e, iv, d_e, flag)[0])
                            rows.append(option_row(f"{'c' if flag else 'p'}{K}{expiry}{d}", "510300OP.SH", K, flag,
                                                   round(price, 4), expiry.strftime("%Y%m"), expiry=expiry.isoformat())
                                        | {"trade_date": d.isoformat()})
            return {"records": rows, "diagnostics": [], "status": "ok"}
        if dataset == "benchmark_rate":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat(), "rate": 1.5} for d in trade_days],
                    "diagnostics": [], "status": "ok"}
        if dataset == "fund_exchange_daily":
            return {"records": [{"symbol": s, "trade_date": d.isoformat(), "close": 3.0} for s in symbols for d in trade_days],
                    "diagnostics": [], "status": "ok"}
        return {"records": [], "diagnostics": [], "status": "ok"}

    ctx = service.Context(fetch, now=datetime(2026, 9, 25, 10, 0), cache_dir=tmp_path)
    for _ in range(10):  # 每次调用最多补 2 块；续调到构建完成
        out = service.options_vix(ctx, years=0.5, underlyings=("510300.SH",))
        if not out["building"]:
            break
    assert not out["building"]
    u = out["underlyings"][0]
    assert u["stats"]["current"] == pytest.approx(20.0, abs=1.2)
    # 全历史返回（约 190 个交易日 > 0.5 年统计窗口 125），分位数仍按窗口
    assert len(u["vix"]) > 125 and u["stats"]["count"] == 125
    assert u["spot"] and u["group"] == "沪深300" and u["kind"] == "沪ETF"
    assert out["progress"]["done"] == out["progress"]["total"]
    n_chain = len([c for c in calls if c[0] == "options_chain"])
    assert n_chain >= 3  # 窗口分成 ≤31 天的块
    calls.clear()
    ctx2 = service.Context(fetch, now=datetime(2026, 9, 25, 10, 0), cache_dir=tmp_path)
    service.options_vix(ctx2, years=0.5, underlyings=("510300.SH",))
    assert not [c for c in calls if c[0] == "options_chain"]  # 全部命中逐日缓存


def test_options_vix_empty_chunk_is_retried_not_cached(tmp_path, monkeypatch):
    """整块无记录（拉取失败特征）：不缓存、保持 building、下轮重试；恢复后正常完成。"""
    from ir_derivatives import service
    _patch_listing(monkeypatch, **{"510300.SH": date(2026, 1, 1)})
    cal_days = weekdays(date(2026, 1, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]
    F, iv, r = 3.0, 0.20, 0.015
    expiries = (date(2026, 10, 28), date(2026, 11, 25))
    state = {"empty": True}

    def fetch(dataset, symbols, start, end, **kwargs):
        if dataset == "trading_calendar":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat()} for d in cal_days if start <= d <= end],
                    "diagnostics": [], "status": "ok"}
        if dataset == "options_chain":
            if state["empty"]:
                return {"records": [], "diagnostics": [], "status": "ok"}
            rows = []
            for d in trade_days:
                if not (start <= d <= end):
                    continue
                for expiry in expiries:
                    t_e = (expiry - d).days / 365
                    d_e = math.exp(-r * t_e)
                    for i in range(11):
                        K = 2.5 + i * 0.1
                        for flag in (True, False):
                            price = float(black76.price(F, K, t_e, iv, d_e, flag)[0])
                            rows.append(option_row(f"{'c' if flag else 'p'}{K}{expiry}{d}", "510300OP.SH", K, flag,
                                                   round(price, 4), expiry.strftime("%Y%m"), expiry=expiry.isoformat())
                                        | {"trade_date": d.isoformat()})
            return {"records": rows, "diagnostics": [], "status": "ok"}
        if dataset == "benchmark_rate":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat(), "rate": 1.5} for d in trade_days],
                    "diagnostics": [], "status": "ok"}
        if dataset == "fund_exchange_daily":
            return {"records": [{"symbol": s, "trade_date": d.isoformat(), "close": 3.0} for s in symbols for d in trade_days],
                    "diagnostics": [], "status": "ok"}
        return {"records": [], "diagnostics": [], "status": "ok"}

    ctx = service.Context(fetch, now=datetime(2026, 9, 25, 10, 0), cache_dir=tmp_path)
    out = service.options_vix(ctx, years=0.5, underlyings=("510300.SH",))
    assert out["building"] is True
    cache_file = tmp_path / "vix-v1-510300.SH.json"
    assert not cache_file.exists() or not json.loads(cache_file.read_text())["days"]  # 空块不落有效缓存
    state["empty"] = False
    for _ in range(8):
        out = service.options_vix(ctx, years=0.5, underlyings=("510300.SH",))
        if not out["building"]:
            break
    assert not out["building"]
    assert out["underlyings"][0]["stats"]["current"] == pytest.approx(20.0, abs=1.2)


def test_options_vix_calendar_outage_raises_not_fake_complete(tmp_path, monkeypatch):
    """交易日历取数失败（0 行）必须显式报错：expected 全空会被误算成 remaining=0/building=False 假完成。"""
    from ir_derivatives import service
    _patch_listing(monkeypatch, **{"510300.SH": date(2026, 1, 1)})

    def fetch(dataset, symbols, start, end, **kwargs):
        return {"records": [], "diagnostics": [], "status": "ok"}

    ctx = service.Context(fetch, now=datetime(2026, 9, 25, 10, 0), cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="trading calendar unavailable"):
        service.options_vix(ctx, years=0.5, underlyings=("510300.SH",))


def _synthetic_option_fetch(cal_days, trade_days, series_by_day, expiries, calls, F=3.0, iv=0.20, r=0.015):
    """series_by_day: func(day) -> [series_id,...]；模拟按交易所拉链、多个品种共存于同一分块。"""
    def fetch(dataset, symbols, start, end, **kwargs):
        if dataset == "trading_calendar":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat()} for d in cal_days if start <= d <= end],
                    "diagnostics": [], "status": "ok"}
        if dataset == "options_chain":
            calls.append((symbols[0], start, end))
            rows = []
            for d in trade_days:
                if not (start <= d <= end):
                    continue
                for series in series_by_day(d):
                    for expiry in expiries:
                        t_e = (expiry - d).days / 365
                        d_e = math.exp(-r * t_e)
                        for i in range(11):
                            K = 2.5 + i * 0.1
                            for flag in (True, False):
                                price = float(black76.price(F, K, t_e, iv, d_e, flag)[0])
                                rows.append(option_row(f"{series}{'c' if flag else 'p'}{K}{expiry}{d}", series, K, flag,
                                                       round(price, 4), expiry.strftime("%Y%m"), expiry=expiry.isoformat())
                                            | {"trade_date": d.isoformat()})
            return {"records": rows, "diagnostics": [], "status": "ok"}
        if dataset == "benchmark_rate":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat(), "rate": 1.5} for d in trade_days],
                    "diagnostics": [], "status": "ok"}
        if dataset == "fund_exchange_daily":
            return {"records": [{"symbol": s, "trade_date": d.isoformat(), "close": 3.0} for s in symbols for d in trade_days],
                    "diagnostics": [], "status": "ok"}
        return {"records": [], "diagnostics": [], "status": "ok"}
    return fetch


def test_options_vix_exchange_grouping_shares_chunks(tmp_path, monkeypatch):
    """同一交易所的多个标的共享链分块：SSE 一次拉取同时推进 510050 与 510300，不重复取数。"""
    from ir_derivatives import service
    _patch_listing(monkeypatch, **{"510050.SH": date(2026, 1, 1), "510300.SH": date(2026, 1, 1)})
    cal_days = weekdays(date(2026, 1, 1), date(2027, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2026, 9, 24)]
    calls = []
    fetch = _synthetic_option_fetch(cal_days, trade_days, lambda d: ("510050OP.SH", "510300OP.SH"),
                                    (date(2026, 10, 28), date(2026, 11, 25)), calls)
    ctx = service.Context(fetch, now=datetime(2026, 9, 25, 10, 0), cache_dir=tmp_path)
    for _ in range(10):
        out = service.options_vix(ctx, years=0.5, underlyings=("510050.SH", "510300.SH"))
        if not out["building"]:
            break
    assert not out["building"]
    assert len(calls) == len(set(calls))  # 每个分块只拉一次：两个标的共享
    for u in out["underlyings"]:
        assert u["stats"]["current"] == pytest.approx(20.0, abs=1.2)
    assert (tmp_path / "vix-v1-510050.SH.json").exists() and (tmp_path / "vix-v1-510300.SH.json").exists()


def test_options_vix_prelisting_empty_chunks_settle(tmp_path, monkeypatch):
    """长窗口伸到上市之前：交易所期权业务未开办（SZSE 2019-12-23 前）的空分块按 None 落盘并收敛；
    开办后某品种未上市的日期经由「块内逐日」路径同样记 None。"""
    from ir_derivatives import service
    # 虚构 159919 上市日 2018-09-01（真实为 2019-12-23），让期望窗口伸到交易所开办日之前
    _patch_listing(monkeypatch, **{"159919.SZ": date(2018, 9, 1), "159915.SZ": date(2021, 3, 1)})
    cal_days = weekdays(date(2018, 1, 1), date(2022, 6, 30))
    trade_days = [d for d in cal_days if d <= date(2021, 5, 31)]
    # 2019-12-23 交易所开办起有链（159919）；159915 2021-03-01 才上市；开办前整所无数据
    series_by_day = lambda d: (("159919OP.SZ", "159915OP.SZ") if d >= date(2021, 3, 1) else ("159919OP.SZ",)) \
        if d >= date(2019, 12, 23) else ()
    calls = []
    fetch = _synthetic_option_fetch(cal_days, trade_days, series_by_day, (date(2021, 7, 28), date(2021, 8, 25)), calls)
    ctx = service.Context(fetch, now=datetime(2021, 6, 1, 10, 0), cache_dir=tmp_path)
    for _ in range(40):
        out = service.options_vix(ctx, years=2.5, underlyings=("159919.SZ", "159915.SZ"))
        if not out["building"]:
            break
    assert not out["building"]  # 上市前空块落 None 后收敛，不无限重试
    cache915 = json.loads((tmp_path / "vix-v1-159915.SZ.json").read_text())["days"]
    assert all(d >= "2021-03-01" for d in cache915)  # 期望窗口自该品种上市日起，之前不建
    late = [v for d, v in cache915.items() if d >= "2021-03-01" and v is not None]
    # 两个固定到期在 2021-03~05 均 >30 天 → 短窗外推 + 离散化偏差，数值只作 sanity（精确性由专门测试覆盖）
    assert late and all(14.0 < v < 30.0 for v in late)
    cache919 = json.loads((tmp_path / "vix-v1-159919.SZ.json").read_text())["days"]
    assert all(cache919[d] is None for d in cache919 if d < "2019-12-23")  # 交易所未开办：空块落 None
    assert any(v is not None for d, v in cache919.items() if "2019-12-23" <= d < "2021-03-01")
    assert len(calls) == len(set(calls))


# ---------------------------------------------------------------- commodity theta

def test_theta_model_recovers_two_factor():
    To = np.array([0.1, 0.18, 0.27, 0.43, 0.6, 0.77, 0.85, 0.93])
    TF = To + 30 / 365
    theta = commodity.theta_closed(To, TF, 0.14, 0.30, 2.5, 0.2)
    out = commodity.fit_theta_model(To, TF, theta, np.ones(len(theta)), 0.74)
    assert out and out["model"] in ("two_factor", "two_factor_fixed", "two_factor_seasonal")
    assert out["log_rmse"] < 0.02
    # 时间齐次、间隔相同 → theta 严格递增（tex 命题 theta i）
    assert np.all(np.diff(theta) > 0)


# ---------------------------------------------------------------- service helpers

def test_clean_handles_nan_and_dates():
    from ir_derivatives import service
    out = service._clean({"a": float("nan"), "b": [date(2026, 9, 24), 1.5], "c": {"d": float("inf")}})
    assert out == {"a": None, "b": ["2026-09-24", 1.5], "c": {"d": None}}


def test_surface_smoke_on_synthetic_etf_chain():
    """合成链走一遍 ETF 流水线：eSSVI 标定、诊断与 Greeks 行都应当出现。"""
    from ir_derivatives import service
    rng = np.random.default_rng(3)
    F0, D_rate = 3.0, 0.015
    params_true = np.array([[0.002, -0.3, 0.045], [0.008, -0.3, 0.09]])
    rows = []
    days = weekdays(date(2026, 9, 1), date(2027, 12, 31))
    cal = TradingCalendar(days)
    clock = VarianceClock(cal, date(2026, 9, 24), 0.15)
    for expiry, (th, rho, psi) in zip((date(2026, 10, 28), date(2026, 12, 23)), params_true):
        tau = clock.tau(expiry)
        t_cal = clock.calendar_years(expiry)
        D = math.exp(-D_rate * t_cal)
        for K in np.arange(2.6, 3.45, 0.05):
            k = math.log(K / F0)
            vol = math.sqrt(essvi.essvi_w(np.array([k]), th, rho, psi)[0] / tau)
            for flag in (True, False):
                price = float(black76.price(F0, K, tau, vol, D, flag)[0])
                if price < 0.0004:
                    continue
                rows.append({"symbol": "SSE", "contract": f"{'c' if flag else 'p'}{K}{expiry}", "series_id": "510300OP.SH",
                             "option_type": "call" if flag else "put", "strike": float(K), "contract_size": 10000.0,
                             "contract_month": expiry.strftime("%Y%m"), "trading_code": "x", "listing_date": "2026-01-01",
                             "last_trading_date": expiry.isoformat(), "trade_date": "2026-09-24", "open": None, "high": None,
                             "low": None, "close": round(price + rng.normal(0, 0.0003), 4), "settlement": None,
                             "previous_settlement": None, "volume": 500.0, "open_interest": 100.0, "price_status": "traded"})
    slices = chain.normalize(rows)

    def fetch(dataset, symbols, start, end, **kwargs):
        if dataset == "trading_calendar":
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat()} for d in days], "diagnostics": [], "status": "ok"}
        if dataset == "fund_exchange_daily":
            dates = weekdays(date(2023, 1, 1), date(2026, 9, 24))
            closes = (3.0 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates))))).tolist()
            return {"records": [{"symbol": symbols[0], "trade_date": d.isoformat(), "close": c} for d, c in zip(dates, closes)],
                    "diagnostics": [], "status": "ok"}
        return {"records": [], "diagnostics": [], "status": "ok"}

    ctx = service.Context(fetch, now=datetime(2026, 9, 25, 8, 0))
    # 直接跑流水线（service.options_surface 的日期选择依赖最新链日，这里验证核心引擎）
    out = surface.equity_surface(slices, family="etf", valuation=date(2026, 9, 24), clock=clock, rate=D_rate, spot=F0)
    assert out["status"] == "ok"
    assert out["model"].startswith("essvi")
    assert out["diagnostics"]["butterfly_ok"] and out["diagnostics"]["calendar_ok"]
    fitted = [s for s in out["slices"] if "params" in s]
    assert len(fitted) == 2
    for s in fitted:
        market_iv = [o["iv_mkt"] for o in s["options"] if o["iv_mkt"] is not None]
        assert all(0.01 < iv < 2 for iv in market_iv)
        assert any(o["model"]["delta"] is not None for o in s["options"] if o.get("model"))
