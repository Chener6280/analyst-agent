"""Option chain normalization: series classification, slices, tick inference, quote filters, forwards.

Input rows are ir_search ``options_chain`` records (Wind EOD). There are no bid/ask quotes, so the
tex spread-based weights are replaced by one-tick implied-vol widths and a non-synchronicity floor.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import numpy as np

ETF_SERIES = re.compile(r"^(\d{6})OP\.(SH|SZ)$")
INDEX_SERIES = re.compile(r"^(HO|IO|MO)\.CFE$")
COMMODITY_SERIES = re.compile(r"^([A-Z]+)O(\d{3,4})(MS)?\.(DCE|CZC|SHF|INE|GFE)$")
INDEX_FUTURE = {"HO": "IH", "IO": "IF", "MO": "IM"}
INDEX_NAME = {"HO": "上证50股指期权", "IO": "沪深300股指期权", "MO": "中证1000股指期权"}
EXCHANGE_SUFFIX = {"DCE": "DCE", "CZCE": "CZC", "SHFE": "SHF", "INE": "INE", "GFEX": "GFE", "SSE": "SH", "SZSE": "SZ", "CFFEX": "CFE"}
FAMILY = {"SSE": "etf", "SZSE": "etf", "CFFEX": "index", "DCE": "commodity", "CZCE": "commodity",
          "SHFE": "commodity", "INE": "commodity", "GFEX": "commodity"}
TICK_CANDIDATES = (10.0, 5.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001, 0.0005, 0.0001)


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def day(value):
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def classify(series_id: str, contract_month: str | None = None):
    """Series -> (family, product, underlying code). Index options map to the same-month future."""
    m = ETF_SERIES.match(series_id)
    if m:
        return {"family": "etf", "product": f"{m.group(1)}.{m.group(2)}", "underlying": f"{m.group(1)}.{m.group(2)}", "serial": False}
    m = INDEX_SERIES.match(series_id)
    if m:
        month = (contract_month or "")[2:6]
        return {"family": "index", "product": m.group(1), "underlying": f"{INDEX_FUTURE[m.group(1)]}{month}.CFE" if month else None,
                "serial": False}
    m = COMMODITY_SERIES.match(series_id)
    if m:
        product, month, serial, suffix = m.groups()
        return {"family": "commodity", "product": f"{product}.{suffix}", "underlying": f"{product}{month}.{suffix}",
                "serial": bool(serial)}
    return None


def infer_tick(prices):
    """Largest candidate tick of which every observed price is an integer multiple (quote granularity)."""
    values = [p for p in prices if p is not None and p > 0]
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    for tick in TICK_CANDIDATES:
        ratio = arr / tick
        if np.all(np.abs(ratio - np.round(ratio)) < 1e-6 * np.maximum(1.0, ratio)):
            return tick
    return TICK_CANDIDATES[-1]


@dataclass
class Option:
    contract: str
    is_call: bool
    strike: float
    close: float | None
    settlement: float | None
    volume: float
    open_interest: float | None
    traded: bool
    contract_size: float | None
    trading_code: str | None
    adjusted: bool


@dataclass
class Slice:
    key: str
    series_id: str
    family: str
    product: str
    underlying: str | None
    serial: bool
    expiry: date
    contract_month: str | None
    options: list = field(default_factory=list)


def normalize(rows):
    """Group chain rows into slices keyed by (series, expiry)."""
    slices = {}
    for row in rows:
        series = str(row.get("series_id") or "")
        info = classify(series, row.get("contract_month"))
        expiry = day(row.get("last_trading_date"))
        strike = num(row.get("strike"))
        if info is None or expiry is None or strike is None or strike <= 0:
            continue
        key = f"{series}|{expiry.isoformat()}"
        if key not in slices:
            slices[key] = Slice(key, series, info["family"], info["product"], info["underlying"], info["serial"], expiry,
                                row.get("contract_month"))
        close = num(row.get("close"))
        volume = num(row.get("volume")) or 0.0
        code = str(row.get("trading_code") or "")
        adjusted = bool(re.search(r"\d[CP]\d{4}A\d", code)) if info["family"] == "etf" else False
        slices[key].options.append(Option(
            contract=str(row.get("contract")), is_call=str(row.get("option_type")) == "call", strike=strike,
            close=close, settlement=num(row.get("settlement")), volume=volume, open_interest=num(row.get("open_interest")),
            traded=str(row.get("price_status")) == "traded" and volume > 0 and close is not None and close > 0,
            contract_size=num(row.get("contract_size")), trading_code=code or None, adjusted=adjusted))
    return sorted(slices.values(), key=lambda s: (s.product, s.underlying or "", s.expiry, s.series_id))


def catalog(rows):
    """Products on one exchange with slice and trade counts (for the renderer's underlying picker)."""
    products = defaultdict(lambda: {"series": set(), "expiries": set(), "contracts": 0, "traded": 0, "underlyings": set()})
    for s in normalize(rows):
        entry = products[s.product]
        entry["series"].add(s.series_id)
        entry["expiries"].add(s.expiry.isoformat())
        entry["contracts"] += len(s.options)
        entry["traded"] += sum(1 for o in s.options if o.traded)
        if s.underlying:
            entry["underlyings"].add(s.underlying)
        entry["family"] = s.family
    out = []
    for product, entry in sorted(products.items()):
        out.append({"product": product, "family": entry["family"], "label": INDEX_NAME.get(product.split(".")[0], product),
                    "series": len(entry["series"]), "expiries": sorted(entry["expiries"]), "contracts": entry["contracts"],
                    "traded": entry["traded"], "underlyings": sorted(entry["underlyings"])})
    return out


def pcp_forward(options, discount, reference=None, max_pairs=8):
    """Forward from put-call parity C - P = D (F - K) on strikes where both legs traded.

    D is fixed at the rate-implied discount (EOD closes are not synchronous enough to identify it);
    the two-parameter regression slope is still reported as the tex check. Returns None if < 2 pairs."""
    calls = {round(o.strike, 6): o for o in options if o.is_call and o.traded and not o.adjusted}
    puts = {round(o.strike, 6): o for o in options if not o.is_call and o.traded and not o.adjusted}
    strikes = sorted(set(calls) & set(puts))
    if len(strikes) < 2:
        return None
    diffs = np.array([calls[k].close - puts[k].close for k in strikes])
    K = np.array(strikes)
    order = np.argsort(np.abs(diffs))[:max_pairs]
    K, diffs = K[order], diffs[order]
    implied = K + diffs / discount
    forward = float(np.median(implied))
    out = {"forward": forward, "pairs": int(len(K)), "dispersion": float(np.std(implied)) if len(K) > 1 else 0.0,
           "strikes": [float(x) for x in sorted(K)]}
    if len(K) >= 3 and np.ptp(K) > 0:
        slope, intercept = np.polyfit(K, diffs, 1)
        out["regression_discount"] = float(-slope)
        out["regression_forward"] = float(intercept / -slope) if slope < 0 else None
    if reference:
        out["reference"] = float(reference)
    return out


def select_quotes(options, forward, tick, both_sides_band=0.01, min_ticks=3, strikes=None):
    """OTM side (puts below F, calls above), both sides within the ATM band, traded closes only,
    at least ``min_ticks`` ticks (tex filter c). ``strikes`` overrides the strike used for the
    moneyness test (dividend-adjusted ETF contracts are passed in standard units)."""
    chosen = []
    for i, o in enumerate(options):
        if not o.traded:
            continue
        strike = float(strikes[i]) if strikes is not None else o.strike
        k = math.log(strike / forward)
        otm = (not o.is_call and strike < forward) or (o.is_call and strike > forward)
        if not otm and abs(k) > both_sides_band:
            continue
        if tick and o.close < min_ticks * tick:
            continue
        chosen.append(o)
    return chosen
