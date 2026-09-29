"""Request orchestration for the desktop bridge. Data access is injected as ``fetch`` so the analytics
never import ir_search directly:

    fetch(dataset, symbols, start, end, market=..., provider=None, frequency="1d", adjustment="raw")
        -> {"records": [...], "diagnostics": [...], "status": "ok|partial|error"}
"""
from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import basis, chain, surface
from .timegrid import TradingCalendar, VarianceClock, estimate_omega, estimate_omega_pooled

SHANGHAI = ZoneInfo("Asia/Shanghai")
EXCHANGES = ("SSE", "SZSE", "CFFEX", "DCE", "CZCE", "SHFE", "INE", "GFEX")
DEFAULT_OMEGA = 0.1
INDEX_FOR_OPTION = {"HO": "000016.SH", "IO": "000300.SH", "MO": "000852.SH"}


def shanghai_now():
    return datetime.now(SHANGHAI).replace(tzinfo=None)


class Context:
    def __init__(self, fetch, now=None, cache_dir=None):
        self.fetch = fetch
        self.now = now or shanghai_now()
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.notes = []

    def records(self, dataset, symbols, start, end, **kwargs):
        result = self.fetch(dataset, list(symbols), start, end, **kwargs)
        status = result.get("status")
        codes = [c for c in result.get("diagnostics") or [] if c not in {"provider_attempted", "access_not_preverified",
                 "non_tls_explicitly_configured", "database_snapshot_not_pit"}]
        if status != "ok" or codes:
            self.notes.append({"dataset": dataset, "status": status, "codes": sorted(set(codes))[:8],
                               "symbols": list(symbols)[:4] + (["…"] if len(symbols) > 4 else [])})
        return result.get("records") or []

    def cache_read(self, name):
        if not self.cache_dir:
            return None
        path = self.cache_dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def cache_write(self, name, payload):
        if not self.cache_dir:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_dir / f".{name}.tmp"
            tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
            os.replace(tmp, self.cache_dir / name)
        except OSError:
            pass

    def calendar(self, exchange, start, end):
        # 分段拉取再合并：长跨度（如基差全历史 2010 至今）超过 5000 行页上限时避免静默截断
        rows = []
        span = timedelta(days=8 * 365)
        a = start
        while a <= end:
            b = min(a + span, end)
            rows.extend(self.records("trading_calendar", [exchange], a, b, market="CN_FUTURES", frequency="1d",
                                     adjustment="none", provider="wind_mysql"))
            a = b + timedelta(days=1)
        days = sorted({chain.day(r["trade_date"]) for r in rows if r.get("trade_date")})
        if not days and exchange != "CFFEX":
            return self.calendar("CFFEX", start, end)
        return TradingCalendar(days)


def _closes(rows, field="close"):
    out = {}
    for r in rows:
        value = chain.num(r.get(field))
        if value and value > 0:
            out[(str(r["symbol"]), chain.day(r["trade_date"]))] = value
    return out


def _clean(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


# ---------------------------------------------------------------- basis monitor

def _encode_closes(closes):
    return {f"{symbol}|{day.isoformat()}": close for (symbol, day), close in closes.items()}


def _decode_closes(blob):
    out = {}
    for key, close in (blob or {}).items():
        symbol, _, day = key.rpartition("|")
        value = chain.num(close)
        if symbol and day and value:
            out[(symbol, chain.day(day))] = value
    return out


def _prune_basis_cache(ctx, keep):
    if not ctx.cache_dir:
        return
    try:
        for path in ctx.cache_dir.glob("basis-eod-v1*.json"):
            if path.name != keep:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def _basis_eod(ctx, products, index_codes, start, today, cal):
    """Index and futures closes over [start, today]（start 为全历史锚点 HISTORY_START）。

    Historical EOD is immutable once loaded, so the heavy pull is cached under a fixed name and
    only a short tail is re-fetched per call. A pull that comes back partial (>5000-row pages are
    bounded) is NEVER cached, and per-index-symbol coverage is validated on every read: symbols
    missing the window start are refetched individually in full, which self-repairs any cache
    poisoned by an earlier truncated pull. 缓存还记录覆盖的 products/index_symbols；请求集合超出
    缓存集合时整窗重拉，避免子集缓存被误当全量。期货分品种从各自上市日（basis.LISTING）起拉。"""
    cal_days = 10
    tail_start = today - timedelta(days=cal_days)
    key = "basis-eod-v1.json"  # fixed name: the covered start lives inside, so the cache survives daily start drift
    cached = ctx.cache_read(key)
    index_closes, futures_closes = {}, {}
    fetch_start, fetch_end = start, today
    cached_start = None
    if cached and cached.get("start") and chain.day(cached["start"]) <= start \
            and set(products) <= set(cached.get("products") or []) \
            and set(index_codes) <= set(cached.get("index_symbols") or []):
        cached_start = chain.day(cached["start"])
        index_closes = _decode_closes(cached.get("index"))
        futures_closes = _decode_closes(cached.get("futures"))
        fetch_start = tail_start  # refresh only the tail; older closes never change

    complete = [True]  # a partial pull must not poison the cache

    def pull(a, b, only_index_symbols=None, only_products=None):
        jobs = {}
        idx = only_index_symbols if only_index_symbols is not None else index_codes
        # 指数逐标的拉：单标的 16 年约 4000 行 < 5000 行页上限，避免触发续页
        for code in idx:
            jobs[("index", code)] = ("index_daily", [code], a, "CN_INDEX")
        for p in (only_products if only_products is not None else products):
            p_start = max(a, basis.LISTING.get(p, a))  # 上市前的合约不存在，不必拉
            months = basis.candidate_months(p_start, b, cal)
            symbols = [f"{p}{m}.CFE" for m in months]
            # futures_daily 单请求上限 20 个标的（ir_search 适配器约束）；再按 10 只分批，
            # 保证单批行数（10 × 合约最长存续交易日）始终低于 5000 行页上限，不触发续页
            for n in range(0, len(symbols), 10):
                jobs[(p, n)] = ("futures_daily", symbols[n:n + 10], p_start, "CN_FUTURES")

        def run(spec):
            dataset, symbols, job_start, market = spec
            # 显式 wind_mysql：这些数据集在本部署中只有该来源；且续页（>5000 行）必须有显式 provider
            result = ctx.fetch(dataset, list(symbols), job_start, b, market=market, provider="wind_mysql")
            records = result.get("records") or []
            status = result.get("status")
            # 候选合约月含未上市/无成交合约，requested_symbols_without_rows 等属常态信息，不算异常
            benign = {"provider_attempted", "access_not_preverified", "non_tls_explicitly_configured",
                      "database_snapshot_not_pit", "requested_symbols_without_rows",
                      "derivatives_amount_uses_separate_unit_mapping", "source_amount_precision_may_differ",
                      "historical_counting_convention_not_normalized", "index_level_not_tradable_price"}
            codes = [c for c in result.get("diagnostics") or [] if c not in benign]
            if status != "ok" or codes:
                ctx.notes.append({"dataset": dataset, "status": status, "codes": sorted(set(codes))[:8],
                                  "symbols": list(symbols)[:4] + (["…"] if len(symbols) > 4 else [])})
            # 只有行级截断/运营失败才阻止落缓存；partial（如部分标的无行）属内容信息，不阻止
            if result.get("failed") or result.get("truncated") or status in ("error", "unavailable"):
                complete[0] = False
            return records

        out = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            running = {key: pool.submit(run, spec) for key, spec in jobs.items()}
            for key, job in running.items():
                name = key[0]
                try:
                    out.setdefault(name, []).extend(job.result())
                except Exception as exc:  # one failed source must not blank the whole monitor
                    out.setdefault(name, [])
                    complete[0] = False
                    ctx.notes.append({"dataset": name, "status": "error", "codes": [type(exc).__name__],
                                      "message": str(exc)[:200]})
        return out

    pulled = pull(fetch_start, fetch_end)
    for (symbol, day), close in _closes(pulled.get("index", [])).items():
        index_closes[(symbol, day)] = close
    for p in products:
        for (symbol, day), close in _closes(pulled.get(p, [])).items():
            futures_closes[(symbol.split(".")[0], day)] = close
    # 覆盖度校验：按交易日历逐标的核对窗口内应有行数（起点或中段缺口都能发现），缺则单标的全量补拉
    expected = len([d for d in cal.days if start <= d <= today]) - (1 if cal.is_trading(today) else 0)
    missing = []
    for code in index_codes:
        have = sum(1 for (sym, day) in index_closes if sym == code and start <= day <= today)
        if have < expected:
            missing.append(code)
    if missing:
        healed = pull(start, fetch_end, only_index_symbols=missing, only_products=[])
        for (symbol, day), close in _closes(healed.get("index", [])).items():
            index_closes[(symbol, day)] = close
    if complete[0] and index_closes and futures_closes:
        keep_start = min(d for d in (cached_start, start) if d) if cached_start else start
        ctx.cache_write(key, {"start": keep_start.isoformat(), "index": _encode_closes(index_closes),
                              "futures": _encode_closes(futures_closes),
                              "products": sorted(products), "index_symbols": sorted(index_codes)})
        _prune_basis_cache(ctx, key)
    return index_closes, futures_closes


SHIBOR_3M_MA10 = "SHIBOR_3M(10)"  # 用户口径：3 个月 Shibor 过去 10 个数据平均（Wind 移动平均码）


def _latest_obs(rows, field):
    """(date, value) of the most recent record with a value, else (None, None)."""
    best = None
    for r in rows:
        value = chain.num(r.get(field))
        if value is None:
            continue
        day = chain.day(r.get("trade_date"))
        if day and (best is None or day > best[0]):
            best = (day, value)
    return best or (None, None)


def basis_monitor(ctx: Context, products=("IH", "IF", "IC", "IM"), years=3.0, overrides=None):
    """overrides: {product: {"rf": frac, "div": frac, "years": float}} — 缺省项用自动口径：
    rf = SHIBOR_3M(10) 最新值；div = 指数最近可得（不晚于前一交易日）的 Wind 滚动股息率。"""
    years = float(years)
    if not 0.5 <= years <= 10.0:
        raise ValueError("years out of range")
    overrides = overrides or {}
    for name, value in list(overrides.items()):
        if name not in products or not isinstance(value, dict):
            raise ValueError("invalid product override")
        for key, v in value.items():
            if v is None:
                continue
            if key == "years" and not 0.5 <= float(v) <= 10.0:
                raise ValueError("years out of range")
            if key in ("rf", "div") and not -0.05 <= float(v) <= 0.2:
                raise ValueError(f"{key} out of range")
    now = ctx.now
    today = now.date()
    samples_by_product = {p: basis.window_samples((overrides.get(p) or {}).get("years") or years) for p in products}
    max_samples = max(samples_by_product.values())
    # 基差/标的图用全历史（自各品种上市日起，本地 EOD 缓存长期复用）；分位数窗口仍是「过去 N 年」。
    start = basis.HISTORY_START
    cal = ctx.calendar("CFFEX", start - timedelta(days=30), today + timedelta(days=420))
    live_months = basis.listed_months(today, cal)
    index_codes = [basis.PRODUCTS[p]["index"] for p in products]
    status = basis.session_status(now, cal)
    index_closes, futures_closes = _basis_eod(ctx, products, index_codes, start, today, cal)

    prev_trading = max((d for d in cal.days if d < today), default=None)

    def auto_rates():
        out = {"rf": None, "rf_meta": None, "div": {}}
        try:
            day, value = _latest_obs(ctx.records("benchmark_rate", [SHIBOR_3M_MA10], today - timedelta(days=45),
                                                 today, market="CN_RATE"), "rate")
            if value is not None:
                out["rf"] = float(value) / 100.0
                out["rf_meta"] = {"code": SHIBOR_3M_MA10, "date": day.isoformat()}
        except Exception as exc:
            ctx.notes.append({"dataset": "benchmark_rate", "status": "error", "codes": [type(exc).__name__],
                              "message": str(exc)[:200]})
        try:
            rows = ctx.records("index_valuation", index_codes, (prev_trading or today) - timedelta(days=20),
                               prev_trading or today, market="CN_INDEX")
            for code in index_codes:
                day, value = _latest_obs((r for r in rows if str(r.get("symbol")) == code), "dividend_yield")
                if value is not None:
                    out["div"][code] = {"value": float(value) / 100.0, "date": day.isoformat()}
        except Exception as exc:
            ctx.notes.append({"dataset": "index_valuation", "status": "error", "codes": [type(exc).__name__],
                              "message": str(exc)[:200]})
        return out

    rates = auto_rates()

    def futures_live():
        symbols = [f"{p}{m}.CFE" for p in products for m in live_months]
        return ctx.records("futures_snapshot", symbols, today - timedelta(days=14), today, market="CN_FUTURES",
                           provider="fiona", frequency="snapshot", adjustment="raw")

    def index_live():
        if status["code"] in ("holiday", "pre_open"):
            return []
        return ctx.records("index_intraday", index_codes, today, today, market="CN_INDEX", frequency="1m", adjustment="raw")

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {"live": pool.submit(futures_live), "intraday": pool.submit(index_live)}
        results = {}
        for name, job in jobs.items():
            try:
                results[name] = job.result()
            except Exception as exc:  # one failed source must not blank the whole monitor
                results[name] = []
                ctx.notes.append({"dataset": name, "status": "error", "codes": [type(exc).__name__], "message": str(exc)[:200]})
    live = {}
    for r in results["live"]:
        last = chain.num(r.get("last"))
        if not last:
            continue
        quote_time = r.get("quote_time")
        live[str(r["symbol"]).split(".")[0]] = {
            "last": last, "day": chain.day(r.get("trade_date")),
            "time": quote_time.isoformat() if hasattr(quote_time, "isoformat") else quote_time,
            "volume": chain.num(r.get("volume")), "oi": chain.num(r.get("open_interest"))}
    intraday = {}
    for r in results["intraday"]:
        symbol = str(r["symbol"])
        bar = r.get("bar_time")
        key = bar.isoformat() if hasattr(bar, "isoformat") else str(bar)
        if symbol not in intraday or key > intraday[symbol]["time"]:
            intraday[symbol] = {"last": chain.num(r.get("close")), "time": key, "day": chain.day(r.get("trade_date"))}
    out = []
    for p in products:
        code = basis.PRODUCTS[p]["index"]
        ov = overrides.get(p) or {}
        rf = float(ov["rf"]) if ov.get("rf") is not None else rates["rf"]
        div_meta = rates["div"].get(code) or {}
        div = float(ov["div"]) if ov.get("div") is not None else div_meta.get("value")
        carry = (rf or 0.0) - (div or 0.0)
        eod = {day: close for (symbol, day), close in index_closes.items() if symbol == code}
        f_eod = {(c, day): close for (c, day), close in futures_closes.items() if c.startswith(p)}
        product = basis.build_product(p, now=now, calendar=cal, index_eod=eod, index_live=intraday.get(code),
                                      futures_eod=f_eod, futures_live={c: v for c, v in live.items() if c.startswith(p)},
                                      carry=carry, samples=samples_by_product[p])
        product["carry"] = {"rf": rf, "div": div,
                            "rf_source": rates["rf_meta"] if ov.get("rf") is None else "override",
                            "div_source": div_meta.get("date") if ov.get("div") is None else "override",
                            "years": samples_by_product[p] / basis.SAMPLES}
        out.append(product)
        if rf is None or div is None:
            ctx.notes.append({"dataset": "carry", "status": "partial", "codes": ["auto_rate_missing"],
                              "symbols": [p], "message": "rf 或 div 取不到，缺失项按 0 处理"})
    return _clean({"schema": 1, "asOf": now.isoformat(timespec="seconds"), "timezone": "Asia/Shanghai", "status": status,
                   "products": out, "samples": max_samples, "years": years, "notes": ctx.notes,
                   "conventions": {"basis": "指数 − 期货（正值为贴水）；use 勾选后 = 基差 + 指数×(无风险利率−分红率)×剩余天数/365，即合理价 F*−期货",
                                   "annualized": "基差 / 期货价格 × 365 / 剩余天数（历史分位同口径）",
                                   "days": "到期日 − 当日 + 1（与参考截图一致）", "change": "最新价 − 上一交易日收盘价",
                                   "rates": "无风险利率 = Wind SHIBOR_3M(10) 最新值；分红率 = Wind 指数滚动股息率最近可得值；两者均为百分数年化",
                                   "history": "Wind 日终收盘（15:00）；图用全历史（自各品种上市日，本地缓存复用），分位数窗口按各品种「过去 N 年」",
                                   "live": "期货：Fiona 快照；指数：新浪分钟线（延迟未核实）；取不到时回落到 Wind 日终"}})


# ---------------------------------------------------------------- options VIX

# 全部权益类期权标的（2026-09 实测：SSE 5 个 ETF、SZSE 4 个 ETF、CFFEX 3 个指数期权）。
# key = 标的代码（指数期权用指数代码，product 为期权品种码）；spot_dataset 为标的价格序列来源。
# listing = 该品种期权上市日（历史构建起点，与期货基差同一标准：全历史）；group/kind 供前端按标的物分组。
# dict 顺序即界面展示顺序：按标的物分组（上证50/沪深300/中证500/中证1000/科创板50/创业板/深证100），
# 组内 沪ETF → 深ETF → 中金所指数。
VIX_UNDERLYINGS = {
    "510050.SH": {"exchange": "SSE", "product": "510050.SH", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "上证50ETF", "kind": "沪ETF", "group": "上证50",
                  "listing": date(2015, 2, 9)},
    "000016.SH": {"exchange": "CFFEX", "product": "HO", "spot_dataset": "index_daily",
                  "spot_market": "CN_INDEX", "name": "上证50指数", "kind": "中金所指数", "group": "上证50",
                  "listing": date(2022, 12, 19)},
    "510300.SH": {"exchange": "SSE", "product": "510300.SH", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "沪深300ETF(沪)", "kind": "沪ETF", "group": "沪深300",
                  "listing": date(2019, 12, 23)},
    "159919.SZ": {"exchange": "SZSE", "product": "159919.SZ", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "沪深300ETF(深)", "kind": "深ETF", "group": "沪深300",
                  "listing": date(2019, 12, 23)},
    "000300.SH": {"exchange": "CFFEX", "product": "IO", "spot_dataset": "index_daily",
                  "spot_market": "CN_INDEX", "name": "沪深300指数", "kind": "中金所指数", "group": "沪深300",
                  "listing": date(2019, 12, 23)},
    "510500.SH": {"exchange": "SSE", "product": "510500.SH", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "中证500ETF(沪)", "kind": "沪ETF", "group": "中证500",
                  "listing": date(2022, 9, 19)},
    "159922.SZ": {"exchange": "SZSE", "product": "159922.SZ", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "中证500ETF(深)", "kind": "深ETF", "group": "中证500",
                  "listing": date(2022, 9, 19)},
    "000852.SH": {"exchange": "CFFEX", "product": "MO", "spot_dataset": "index_daily",
                  "spot_market": "CN_INDEX", "name": "中证1000指数", "kind": "中金所指数", "group": "中证1000",
                  "listing": date(2022, 7, 22)},
    "588000.SH": {"exchange": "SSE", "product": "588000.SH", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "科创50ETF", "kind": "华夏ETF", "group": "科创板50",
                  "listing": date(2023, 6, 5)},
    "588080.SH": {"exchange": "SSE", "product": "588080.SH", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "科创板50ETF", "kind": "易方达ETF", "group": "科创板50",
                  "listing": date(2023, 6, 5)},
    "159915.SZ": {"exchange": "SZSE", "product": "159915.SZ", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "创业板ETF", "kind": "深ETF", "group": "创业板",
                  "listing": date(2022, 9, 19)},
    "159901.SZ": {"exchange": "SZSE", "product": "159901.SZ", "spot_dataset": "fund_exchange_daily",
                  "spot_market": "CN_FUND", "name": "深证100ETF", "kind": "深ETF", "group": "深证100",
                  "listing": date(2022, 12, 12)},
}
VIX_CHUNKS_PER_CALL = 2  # 每次调用最多补 2 个分块（单块约 25s，串行 ≈55s < 180s 桥接超时）；前端自动续调
VIX_EXCHANGE_ORDER = ("SSE", "SZSE", "CFFEX")  # 分块调度按交易所轮转，各标的进度均衡
# 各交易所权益类期权上市日：早于该日的空分块视为「当时确无数据」落 None 落盘（长窗口不反复重拉），
# 之后的空分块一律视为可疑（可能是取数故障），不写缓存、下轮重试。
EXCHANGE_OPTIONS_SINCE = {"SSE": date(2015, 2, 9), "SZSE": date(2019, 12, 23), "CFFEX": date(2019, 12, 23)}


def _vix_rate_map(ctx, start, end):
    rows = ctx.records("benchmark_rate", [SHIBOR_3M_MA10], start, end, market="CN_RATE")
    series = sorted((chain.day(r["trade_date"]), float(chain.num(r["rate"])) / 100.0)
                    for r in rows if chain.num(r.get("rate")) is not None and r.get("trade_date"))

    def at(day):
        value = None
        for d, v in series:
            if d > day:
                break
            value = v
        return value if value is not None else (series[0][1] if series else 0.015)

    return at


def _missing_spans(missing, limit):
    """Consecutive missing days merged into <=31-day fetch spans (options_chain range cap)."""
    spans, i = [], 0
    while i < len(missing):
        a = missing[i]
        j = i
        while j + 1 < len(missing) and missing[j + 1] <= a + timedelta(days=30):
            j += 1
        spans.append((a, missing[j]))
        i = j + 1
    return spans[:limit], spans[limit:]


_BENIGN_CODES = {"provider_attempted", "access_not_preverified", "non_tls_explicitly_configured",
                 "database_snapshot_not_pit"}


def options_vix(ctx: Context, years=3.0, underlyings=None, since=None):
    """VIX 历史按各品种上市日起全量构建（与期货基差同一标准），years 只决定统计/分位数窗口。
    since（date，测试/诊断用）可把构建起点整体上移。"""
    from . import vix
    years = float(years)
    if not 0.5 <= years <= 10.0:
        raise ValueError("years out of range")
    codes_all = list(underlyings) if underlyings else list(VIX_UNDERLYINGS)
    for code in codes_all:
        if code not in VIX_UNDERLYINGS:
            raise ValueError("unsupported underlying")
    if since is not None and not isinstance(since, date):
        raise ValueError("invalid since")
    now, today = ctx.now, ctx.now.date()
    samples = basis.window_samples(years)
    start_by_code = {c: max(VIX_UNDERLYINGS[c]["listing"], since) if since else VIX_UNDERLYINGS[c]["listing"]
                     for c in codes_all}
    earliest = min(start_by_code.values())
    cal = ctx.calendar("CFFEX", earliest - timedelta(days=30), today + timedelta(days=60))
    # Wind 期权 EOD 傍晚才入库；当天 18:00 前不算今天
    chain_end = max((d for d in cal.days if d <= today and (d < today or now.hour >= 18)), default=None)
    if chain_end is None or not any(d for d in cal.days if d >= earliest):
        # 日历取数瞬时失败时 expected 全空会被误报成「构建完成」；必须显式失败，下轮重试
        raise RuntimeError(f"trading calendar unavailable (CFFEX {earliest}~{today}): cannot determine expected VIX days")
    rate_at = _vix_rate_map(ctx, earliest, chain_end or today)
    expected_by_code = {c: [d for d in cal.days if chain_end and start_by_code[c] <= d <= chain_end] for c in codes_all}
    expected_sets = {c: set(v) for c, v in expected_by_code.items()}
    stale_before = today - timedelta(days=40)  # 早于该日期的块内空交易日接受为 None；近期的留下轮重试（EOD 晚间入库）

    # 按交易所分组：同一交易所的标的共享同一批链分块，一次拉取写多个标的的日缓存
    groups = {}
    for code in codes_all:
        meta = VIX_UNDERLYINGS[code]
        days_cache = dict((ctx.cache_read(f"vix-v1-{code}.json") or {}).get("days") or {})
        missing = [d for d in expected_by_code[code] if d.isoformat() not in days_cache]
        groups.setdefault(meta["exchange"], {"codes": [], "cache": {}, "missing": set()})
        g = groups[meta["exchange"]]
        g["codes"].append(code)
        g["cache"][code] = days_cache
        g["missing"] |= set(missing)

    # 各交易所分块轮转，凑满本次调用预算
    queues = {exch: _missing_spans(sorted(g["missing"]), 10 ** 9)[0]
              for exch, g in groups.items() if g["missing"]}
    work = []
    while len(work) < VIX_CHUNKS_PER_CALL and any(queues.values()):
        for exch in VIX_EXCHANGE_ORDER:
            if len(work) >= VIX_CHUNKS_PER_CALL:
                break
            if queues.get(exch):
                work.append((exch, queues[exch].pop(0)))

    for exch, (a, b) in work:
        g = groups[exch]
        # 串行拉取：ir_search 的 MySQL 连接全局串行，并发只会争抢锁并触发 60s 预算中断。
        # 失败判定：行级截断（truncated）/运营失败（failed）/error/unavailable 才不写缓存重试；
        # partial 与信息性诊断（如页内部分合约字段缺失）照常处理；status ok 且 0 行 = 该时段
        # 确无数据（上市前），由下面的开办日规则处理。
        result = ctx.fetch("options_chain", [exch], a, b, market="CN_OPTIONS", provider="wind_mysql")
        rows = result.get("records") or []
        status = result.get("status")
        info = [c for c in result.get("diagnostics") or [] if c not in _BENIGN_CODES]
        if info:
            ctx.notes.append({"dataset": "options_chain", "status": status,
                              "codes": sorted(set(info))[:8], "message": f"{exch} {a}~{b}"})
        if status in ("error", "unavailable") or result.get("failed") or result.get("truncated"):
            continue  # 失败/截断不写缓存，下一轮重试
        if not rows:
            if b >= EXCHANGE_OPTIONS_SINCE.get(exch, date(2015, 1, 1)):
                ctx.notes.append({"dataset": "options_chain", "status": "empty",
                                  "codes": ["chunk_fetch_empty"], "message": f"{exch} {a}~{b}"})
                continue  # 上市之后的空块 = 可疑（取数故障或 EOD 未入库），不写缓存、下轮重试
            for code in g["codes"]:
                cache = g["cache"][code]
                for d in expected_by_code[code]:
                    if a <= d <= b:
                        cache[d.isoformat()] = None  # 该所尚未上市期权，按空值落盘
                ctx.cache_write(f"vix-v1-{code}.json", {"schema": 1, "underlying": code, "days": cache})
            continue
        by_day = {}
        for r in rows:
            day = chain.day(r.get("trade_date"))
            if day:
                by_day.setdefault(day, []).append(r)
        normalized = {day: chain.normalize(day_rows) for day, day_rows in by_day.items()}
        for code in g["codes"]:
            meta = VIX_UNDERLYINGS[code]
            cache = g["cache"][code]
            for day in sorted(by_day):
                if day not in expected_sets[code]:
                    continue  # 早于该品种上市日的行不写它的缓存（共享分块覆盖组内其他品种）
                blocks = {}
                for s in normalized[day]:
                    if s.product != meta["product"]:
                        continue
                    points = vix.strike_map(s.options)
                    if points:
                        blocks[s.expiry] = points
                cache[day.isoformat()] = vix.daily_vix(day, blocks, rate_at(day))
            for day in (d for d in expected_by_code[code] if a <= d <= b and d not in by_day):
                if day <= stale_before:
                    cache[day.isoformat()] = None  # 老缺口接受为空；近 40 天缺口留下轮重试（EOD 晚间才入库）
            ctx.cache_write(f"vix-v1-{code}.json", {"schema": 1, "underlying": code, "days": cache})

    # 现货序列逐标的拉取（单标的多年也不超 5000 行页上限；批量请求超页会被静默截断）。
    # 显式 wind_mysql：该部署唯一来源，且万一日后超页续页必须有显式 provider。
    spot_rows = {}
    for code in codes_all:
        meta = VIX_UNDERLYINGS[code]
        for r in ctx.records(meta["spot_dataset"], [code], start_by_code[code], today,
                             market=meta["spot_market"], provider="wind_mysql"):
            day, close = r.get("trade_date"), chain.num(r.get("close"))
            if day and close:
                spot_rows.setdefault(code, []).append((chain.day(day).isoformat(), close))

    out = []
    for code in codes_all:
        meta = VIX_UNDERLYINGS[code]
        cache = groups[meta["exchange"]]["cache"][code]
        # 图用全历史（自上市日起）；分位数/dVIX 仍按「过去 N 年」窗口（与左表口径一致）
        points = [(iso, v) for iso, v in sorted(cache.items())
                  if v is not None and meta["listing"].isoformat() <= iso <= (chain_end or today).isoformat()]
        stats = vix.series_stats(points[-samples:], points[-1][0]) if points else None
        spot = sorted(spot_rows.get(code, []))
        out.append({"underlying": code, "name": meta["name"], "kind": meta["kind"], "group": meta["group"],
                    "exchange": meta["exchange"], "since": meta["listing"].isoformat(),
                    "stats": stats, "vix": [[d, v] for d, v in points], "spot": [[d, c] for d, c in spot]})
    total_expected = max(1, sum(len(v) for v in expected_by_code.values()))
    remaining = sum(1 for code in codes_all
                    for d in expected_by_code[code]
                    if d.isoformat() not in groups[VIX_UNDERLYINGS[code]["exchange"]]["cache"][code])
    done = total_expected - remaining
    return _clean({"schema": 1, "asOf": now.isoformat(timespec="seconds"), "timezone": "Asia/Shanghai",
                   "years": years, "samples": samples, "underlyings": out, "notes": ctx.notes,
                   "building": remaining > 0,
                   "progress": {"done": max(0, done), "total": total_expected},
                   "conventions": {
                       "vix": "CBOE 白皮书 model-free 方差公式：两个最近到期（剩余≥8 个自然日）OTM 收盘价的方差互换率，插值到 30 天 ×100",
                       "quotes": "Wind 日终链；无买卖盘，Q(K) 取有成交合约收盘价（替代零买价截断）；有效行权价<6 的日期留空不编造",
                       "forward": "按平价关系取 |C−P| 最小行权价推算；利率 = SHIBOR_3M(10) 当日值（简单年化转连续复利）",
                       "interp": "T₁σ₁²/T₂σ₂² 对 30 天线性插值；换月后两端均 >30 天时为短窗口外推",
                       "history": "图用全历史（自各品种期权上市日，本地逐日缓存复用）；「过去 N 年」只作用于统计口径",
                       "stats": "dVIX = 当日 − 前一有效日；分位数 = 过去 N 年窗口内 ≤ 当前值的比例"}})


# ---------------------------------------------------------------- option chains

def _chain(ctx: Context, exchange, day):
    name = f"chain-{exchange}-{day.isoformat()}.json"
    today = ctx.now.date()
    if day < today:
        cached = ctx.cache_read(name)
        if cached is not None:
            return cached
    rows = ctx.records("options_chain", [exchange], day, day, market="CN_OPTIONS", provider="wind_mysql")
    if rows and day < today:
        ctx.cache_write(name, rows)
    return rows


def _chain_dates(ctx: Context, exchange, requested=None):
    if requested:
        return [chain.day(requested)]
    today = ctx.now.date()
    cal = ctx.calendar("CFFEX" if exchange in ("SSE", "SZSE") else exchange, today - timedelta(days=30), today)
    days = [d for d in cal.days if d <= today]
    # Wind loads option EOD in the evening; before 18:00 today's chain is not worth a query.
    if days and days[-1] == today and ctx.now.hour < 18:
        days = days[:-1]
    return list(reversed(days[-4:]))


def latest_chain(ctx: Context, exchange, requested=None):
    for day in _chain_dates(ctx, exchange, requested):
        rows = _chain(ctx, exchange, day)
        if rows:
            return day, rows
    return None, []


def options_catalog(ctx: Context, exchange, requested=None):
    if exchange not in EXCHANGES:
        raise ValueError("unsupported exchange")
    day, rows = latest_chain(ctx, exchange, requested)
    return _clean({"schema": 1, "exchange": exchange, "family": chain.FAMILY[exchange], "date": day,
                   "products": chain.catalog(rows) if rows else [], "notes": ctx.notes})


def _omega(ctx: Context, key, loader):
    name = f"omega-{key}-{ctx.now.date().isoformat()}.json"
    cached = ctx.cache_read(name)
    if cached:
        return cached
    try:
        series = loader()
        result = estimate_omega_pooled(series)
        result["source"] = "estimated"
    except Exception as exc:
        result = {"omega": DEFAULT_OMEGA, "source": "default", "reason": str(exc)[:120]}
    result["key"] = key
    ctx.cache_write(name, result)
    return result


def _series_from_rows(rows, field="close"):
    grouped = {}
    for r in rows:
        value = chain.num(r.get(field))
        if value and value > 0:
            grouped.setdefault(str(r["symbol"]), []).append((chain.day(r["trade_date"]), value))
    out = []
    for points in grouped.values():
        points.sort()
        out.append(([p[0] for p in points], [p[1] for p in points]))
    return out


def options_surface(ctx: Context, exchange, product, requested=None, rate=0.015):
    if exchange not in EXCHANGES:
        raise ValueError("unsupported exchange")
    rate = float(rate)
    if not -0.05 <= rate <= 0.2:
        raise ValueError("rate out of range")
    day, rows = latest_chain(ctx, exchange, requested)
    if not rows:
        return _clean({"schema": 1, "status": "no_data", "exchange": exchange, "product": product, "notes": ctx.notes})
    slices = [s for s in chain.normalize(rows) if s.product == product]
    if not slices:
        raise ValueError("product not listed on this exchange/date")
    family = slices[0].family
    horizon = max(s.expiry for s in slices) + timedelta(days=400)
    cal = ctx.calendar("CFFEX" if family != "commodity" else exchange, day - timedelta(days=30), horizon)
    history_start = day - timedelta(days=3 * 365 if family != "commodity" else 400)
    spot = None
    futures = {}
    futures_expiry = {}
    if family == "etf":
        omega = _omega(ctx, product, lambda: _series_from_rows(
            ctx.records("fund_exchange_daily", [product], history_start, day, market="CN_FUND")))
        spot_rows = ctx.records("fund_exchange_daily", [product], day, day, market="CN_FUND")
        spot = next((chain.num(r.get("close")) for r in spot_rows if chain.day(r["trade_date"]) == day), None)
    elif family == "index":
        index_code = INDEX_FOR_OPTION[product]
        omega = _omega(ctx, index_code, lambda: _series_from_rows(
            ctx.records("index_daily", [index_code], history_start, day, market="CN_INDEX")))
        codes = sorted({s.underlying for s in slices if s.underlying})
        futures = {symbol: close for (symbol, d), close in _closes(ctx.records(
            "futures_daily", codes, day, day, market="CN_FUTURES")).items() if d == day}
    else:
        codes = sorted({s.underlying for s in slices if s.underlying})
        closes = {}
        for i in range(0, len(codes), 20):
            batch = codes[i:i + 20]
            closes.update(_closes(ctx.records("futures_daily", batch, day, day, market="CN_FUTURES")))
            for r in ctx.records("futures_contracts", batch, day, day, market="CN_FUTURES", frequency="snapshot", adjustment="none"):
                if r.get("last_trading_date"):
                    futures_expiry[str(r["symbol"])] = chain.day(r["last_trading_date"])
        futures = {symbol: close for (symbol, d), close in closes.items() if d == day}

        def pooled():
            series = []
            for i in range(0, len(codes), 20):
                series += _series_from_rows(ctx.records("futures_daily", codes[i:i + 20], history_start, day, market="CN_FUTURES"))
            return series
        omega = _omega(ctx, product, pooled)
    clock = VarianceClock(cal, day, omega["omega"])
    if family == "commodity":
        result = surface.commodity_surface(slices, valuation=day, clock=clock, rate=rate, futures=futures,
                                           futures_expiry=futures_expiry)
    else:
        result = surface.equity_surface(slices, family=family, valuation=day, clock=clock, rate=rate, spot=spot,
                                        futures=futures)
    result.update({"schema": 1, "exchange": exchange, "product": product, "date": day, "rate": rate,
                   "omega": omega, "spot": spot, "calendar_fallback_years": sorted(cal.fallback_used),
                   "notes": ctx.notes, "generatedAt": ctx.now.isoformat(timespec="seconds"),
                   "conventions": {
                       "iv": "自算：欧式 Black-76（远期口径），美式 CRR 树去美式化；不读取数据源 IV/Greeks",
                       "time": "方差时间 τ：交易日权重 1，非交易日权重 ω_n（历史收盘回归估计）",
                       "quotes": "Wind 日终收盘价，仅用有成交合约；无买卖价差，权重用一个最小变动价位折合的波动率宽度，下限 50bp",
                       "greeks": "delta/gamma 为每单位标的（ETF 为现货，股指/商品为期货）；vega/vanna 按 1 个波动率点；theta 为下一交易日；cash 为每张合约",
                       "forward": {"etf": "平价回归（D 取 e^{-rT}），不扣分红", "index": "同月股指期货收盘，远季月平价回归",
                                   "commodity": "所挂期货合约收盘"}[family]}})
    return _clean(result)
