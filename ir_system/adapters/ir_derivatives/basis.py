"""Stock-index futures basis monitor (IH/IF/IC/IM against 000016/000300/000905/000852).

Conventions reproduce the reference calculator screenshots (verified on the 2026-09-24 close):
basis = index - futures (positive = discount), annualized = basis / futures * 365 / days,
days = expiry - sample calendar date + 1, daily = basis / days, per_point = futures * days / 365 / 100
(index points of basis per 1% annualized), change = last - previous close.

Carry adjustment (carry = risk-free rate − dividend yield, simple interest): the fair futures
price is F* = S * (1 + carry * days/365) and the displayed basis becomes F* - F
= raw basis + S * carry * days/365, i.e. the discount in excess of fair carry. carry = 0
leaves the raw convention untouched.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np

PRODUCTS = {
    "IH": {"index": "000016.SH", "name": "上证50", "short": "SSE50", "multiplier": 300},
    "IF": {"index": "000300.SH", "name": "沪深300", "short": "CSI300", "multiplier": 300},
    "IC": {"index": "000905.SH", "name": "中证500", "short": "CSI500", "multiplier": 200},
    "IM": {"index": "000852.SH", "name": "中证1000", "short": "CSI1000", "multiplier": 200},
}
SLOTS = ("当月", "下月", "当季", "下季")
SAMPLES = 250  # trading days per history year
# 基差全历史锚点：IF 上市日 2010-04-16 是最早可算基差的日期；指数数据都回填到 2010 之前，
# 因此指数不做单独起点处理（分品种期货起点见 LISTING，避免拉取上市前不存在的合约）。
HISTORY_START = date(2010, 4, 1)
LISTING = {"IF": date(2010, 4, 16), "IH": date(2015, 4, 16), "IC": date(2015, 4, 16), "IM": date(2022, 7, 22)}


def window_samples(years) -> int:
    """History window in trading days; years clamped to [0.5, 10]."""
    return int(round(min(max(float(years), 0.5), 10.0) * SAMPLES))


def third_friday(year, month):
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def expiry(yymm: str, calendar):
    """CFFEX index futures: third Friday of the delivery month, rolled to the next trading day."""
    year, month = 2000 + int(yymm[:2]), int(yymm[2:])
    day = third_friday(year, month)
    for _ in range(15):
        if calendar.is_trading(day):
            return day
        day += timedelta(days=1)
    return third_friday(year, month)


def _add_months(year, month, n):
    total = year * 12 + (month - 1) + n
    return total // 12, total % 12 + 1


def listed_months(day: date, calendar):
    """Current month, next month and the next two quarterly months listed on ``day``."""
    year, month = day.year, day.month
    if day > expiry(f"{year % 100:02d}{month:02d}", calendar):
        year, month = _add_months(year, month, 1)
    first = (year, month)
    second = _add_months(year, month, 1)
    quarters = []
    y, m = second
    while len(quarters) < 2:
        y, m = _add_months(y, m, 1)
        if m in (3, 6, 9, 12):
            quarters.append((y, m))
    return [f"{y % 100:02d}{m:02d}" for y, m in (first, second, *quarters)]


def days_left(expiry_day: date, sample_day: date) -> int:
    return (expiry_day - sample_day).days + 1


def metrics(index_level, futures_price, days, carry=0.0):
    basis_raw = index_level - futures_price
    adjusted = basis_raw + index_level * carry * days / 365.0
    return {"basis": adjusted, "basis_raw": basis_raw,
            "annualized": adjusted / futures_price * 365.0 / days,
            "annualized_raw": basis_raw / futures_price * 365.0 / days,
            "daily": adjusted / days, "per_point": futures_price * days / 365.0 / 100.0}


def candidate_months(start: date, end: date, calendar):
    months = set()
    day = start
    while day <= end + timedelta(days=1):
        months.update(listed_months(day, calendar))
        day += timedelta(days=7)
    months.update(listed_months(end, calendar))
    return sorted(months)


def slot_history(product, futures_closes, index_closes, calendar, carry=0.0):
    """Per trading day the four listed contracts ordered by expiry and their closing annualized basis.

    futures_closes: {(code, day): close} with codes like IM2703; index_closes: {day: close}.
    ``carry`` switches both basis and annualized to the fair-carry-adjusted convention."""
    by_day = {}
    for (code, day), close in futures_closes.items():
        if close and close > 0:
            by_day.setdefault(day, {})[code] = close
    series = {slot: [] for slot in SLOTS}
    for day in sorted(index_closes):
        quotes = by_day.get(day)
        level = index_closes[day]
        if not quotes or not level:
            continue
        months = listed_months(day, calendar)
        for slot, yymm in zip(SLOTS, months):
            code = f"{product}{yymm}"
            price = quotes.get(code)
            if not price:
                continue
            days = days_left(expiry(yymm, calendar), day)
            if days <= 0:
                continue
            m = metrics(level, price, days, carry)
            series[slot].append({"date": day.isoformat(), "code": code, "annualized": m["annualized"],
                                 "annualized_raw": m["annualized_raw"], "basis": m["basis"], "days": days})
    return series


def percentile_block(samples, current, current_date, window=SAMPLES):
    """Share of the last ``window`` closing samples at or below the current value (reference definition)."""
    values = [s["annualized"] for s in samples][-window:]
    kept = samples[-window:]
    if not values or current is None:
        return None
    arr = np.asarray(values, dtype=float)
    pct = float(np.mean(arr <= current + 1e-12))
    lo, hi = int(np.argmin(arr)), int(np.argmax(arr))
    previous = None
    for s in reversed(kept):
        if s["date"] < current_date:
            previous = s
            break
    label = ("处于历史低位" if pct < 0.10 else "略低于中枢" if pct < 0.35 else "接近中枢" if pct <= 0.65
             else "略高于中枢" if pct <= 0.90 else "处于历史高位")
    return {"current": current, "percentile": pct, "mean": float(arr.mean()), "median": float(np.median(arr)),
            "p25": float(np.percentile(arr, 25)), "p75": float(np.percentile(arr, 75)),
            "min": float(arr[lo]), "min_date": kept[lo]["date"], "max": float(arr[hi]), "max_date": kept[hi]["date"],
            "count": len(values), "target": window, "label": label,
            "previous": previous["annualized"] if previous else None, "previous_date": previous["date"] if previous else None,
            "first_date": kept[0]["date"]}


def session_status(now: datetime, calendar):
    """CFFEX index futures day session 09:30-11:30, 13:00-15:00 (Asia/Shanghai wall clock)."""
    today = now.date()
    if not calendar.is_trading(today):
        return {"code": "holiday", "label": "休市"}
    t = now.time()
    if t < time(9, 30):
        return {"code": "pre_open", "label": "未开盘"}
    if t < time(11, 30):
        return {"code": "trading", "label": "交易中"}
    if t < time(13, 0):
        return {"code": "lunch", "label": "午间休市"}
    if t < time(15, 0):
        return {"code": "trading", "label": "交易中"}
    return {"code": "closed", "label": "已收盘"}


def previous_close(closes_by_day: dict, before: date):
    days = sorted(d for d in closes_by_day if d < before)
    if not days:
        return None, None
    return days[-1], closes_by_day[days[-1]]


def latest_close(closes_by_day: dict, on_or_before: date):
    days = sorted(d for d in closes_by_day if d <= on_or_before)
    if not days:
        return None, None
    return days[-1], closes_by_day[days[-1]]


def build_product(product, *, now, calendar, index_eod, index_live, futures_eod, futures_live,
                  carry=0.0, samples=SAMPLES):
    """index_eod: {day: close}; index_live: {"last", "time", "day"} or None;
    futures_eod: {(code, day): close}; futures_live: {code: {"last", "time", "day", "volume", "oi", "expiry"}}.
    carry: r − q as a fraction; 0 keeps the raw index−futures convention. samples: history window in days."""
    meta = PRODUCTS[product]
    today = now.date()
    sample_day = today
    # Index level: live bar of today when present, else the latest EOD close.
    if index_live and index_live.get("last") and index_live.get("day") == today:
        level, level_day, level_time, level_source = index_live["last"], today, index_live.get("time"), "sina_intraday"
    else:
        level_day, level = latest_close(index_eod, today)
        level_time, level_source = None, "wind_eod"
    prev_day, prev_level = previous_close(index_eod, level_day) if level_day else (None, None)
    index_block = {"code": meta["index"], "name": meta["name"], "short": meta["short"], "last": level, "date": level_day.isoformat() if level_day else None,
                   "time": level_time, "source": level_source, "previous_close": prev_level,
                   "change": (level - prev_level) if level is not None and prev_level is not None else None}
    months = listed_months(today, calendar)
    contracts = []
    for slot, yymm in zip(SLOTS, months):
        code = f"{product}{yymm}"
        exp = expiry(yymm, calendar)
        closes = {day: close for (c, day), close in futures_eod.items() if c == code}
        live = futures_live.get(code) or {}
        if live.get("last") and live.get("day"):
            price, price_day, quote_time, source = live["last"], live["day"], live.get("time"), "fiona_snapshot"
        else:
            price_day, price = latest_close(closes, today)
            quote_time, source = None, "wind_eod"
        prev_day_f, prev_price = previous_close(closes, price_day) if price_day else (None, None)
        days = days_left(exp, sample_day)
        row = {"slot": slot, "code": code, "expiry": exp.isoformat(), "days": days, "price": price,
               "date": price_day.isoformat() if price_day else None, "quote_time": quote_time, "source": source,
               "previous_close": prev_price, "change": (price - prev_price) if price is not None and prev_price is not None else None,
               "volume": live.get("volume"), "open_interest": live.get("oi")}
        if price and level:
            row.update(metrics(level, price, days, carry))
            if prev_price and prev_level:
                # Previous day's display basis: that day had more calendar days to expiry.
                prev_days = days_left(exp, prev_day_f) if prev_day_f else days + 1
                prev_basis = metrics(prev_level, prev_price, prev_days, carry)["basis"]
                row["basis_change"] = row["basis"] - prev_basis
        contracts.append(row)
    history = slot_history(product, futures_eod, index_eod, calendar, carry=carry)
    percentiles = {}
    percentiles_raw = {}
    for slot, row in zip(SLOTS, contracts):
        # The current value is sampled today (days counted from today), so "previous" is the last close before today.
        block = percentile_block(history[slot], row.get("annualized"), today.isoformat(), window=samples)
        if block:
            block["code"] = row["code"]
            percentiles[slot] = block
        raw_series = [dict(s, annualized=s["annualized_raw"]) for s in history[slot]]
        block_raw = percentile_block(raw_series, row.get("annualized_raw"), today.isoformat(), window=samples)
        if block_raw:
            block_raw["code"] = row["code"]
            percentiles_raw[slot] = block_raw
    sync = None
    if level_time and any(c.get("quote_time") for c in contracts):
        sync = {"index_time": level_time, "futures_time": max(c["quote_time"] for c in contracts if c.get("quote_time"))}
    index_history = [[day.isoformat(), close] for day, close in sorted(index_eod.items())]
    # 历史序列返回全历史（前端用双滑块选窗口，默认窗口 = 分位数窗口 samples）；分位数仍按 samples 窗口。
    return {"product": product, "index": index_block, "contracts": contracts,
            "history": {slot: [[s["date"], s["annualized"], s["code"], s["annualized_raw"]]
                               for s in history[slot]] for slot in SLOTS},
            "index_history": index_history, "percentiles": percentiles, "percentiles_raw": percentiles_raw, "sync": sync}
