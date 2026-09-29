"""Model-free VIX for Chinese equity options (CBOE white-paper variance-swap formula).

Per underlying and day:
1. take the two nearest expiries with at least ROLL_MIN_DAYS calendar days to expiry;
2. per expiry: forward F from put-call parity at the min |C-P| strike, K0 = highest strike
   <= F, Q(K) = OTM closes (puts below K0, calls above, call/put average at K0) of contracts
   that actually traded, and
       sigma^2 = (2/T) * sum(dK_i / K_i^2 * e^{rT} * Q(K_i)) - (1/T) * (F/K0 - 1)^2;
3. VIX = 100 * sqrt(linear interpolation of T*sigma^2 to 30 days * 365/30).

Data adaptations (kept explicit, never silently fixed): the Wind EOD chain has no bid/ask, so
Q(K) uses closes of contracts with volume > 0 (replaces the zero-bid truncation rule); T is
calendar days/365 instead of minutes; a day with fewer than MIN_STRIKES valid strikes returns
None and stays a gap in the series.
"""
from __future__ import annotations

import math

ROLL_MIN_DAYS = 8       # 近月剩余不足 8 个自然日时整体后移一档（与用户确认的换月规则）
MIN_STRIKES = 6         # 当天有效行权价少于此数 → 该日不可计算
TARGET_DAYS = 30.0


def _valid(price):
    return price is not None and price > 0


def expiry_variance(points, days, rate):
    """points: [(strike, call_close, put_close)] with closes already filtered to traded contracts;
    days: calendar days to expiry; rate: annual simple rate as a fraction.
    Returns {"sigma2", "t_sigma2", "forward", "k0", "used"} or None when not computable."""
    if days <= 0:
        return None
    pts = sorted({(float(k), c, p) for k, c, p in points if k and float(k) > 0}, key=lambda x: x[0])
    both = [(k, c, p) for k, c, p in pts if _valid(c) and _valid(p)]
    if not both:
        return None
    t = days / 365.0
    r = math.log1p(rate)  # 简单年化 → 连续复利
    disc = math.exp(r * t)
    k_star, c_star, p_star = min(both, key=lambda x: abs(x[1] - x[2]))
    forward = k_star + disc * (c_star - p_star)
    if forward <= 0:
        return None
    below = [k for k, _, _ in pts if k <= forward]
    if not below:
        return None
    k0 = max(below)
    terms = []
    usable = [(k, c, p) for k, c, p in pts if (k < k0 and _valid(p)) or (k > k0 and _valid(c))
              or (k == k0 and _valid(c) and _valid(p))]
    if len(usable) < MIN_STRIKES:
        return None
    strikes = [k for k, _, _ in usable]
    for i, (k, c, p) in enumerate(usable):
        if i == 0:
            dk = strikes[1] - strikes[0] if len(strikes) > 1 else 0.0
        elif i == len(usable) - 1:
            dk = strikes[-1] - strikes[-2]
        else:
            dk = (strikes[i + 1] - strikes[i - 1]) / 2.0
        q = p if k < k0 else c if k > k0 else (c + p) / 2.0
        terms.append(dk / (k * k) * disc * q)
    if any(dk <= 0 for dk in (strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1))):
        return None  # 行权价重复或乱序，口径不允许
    sigma2 = 2.0 / t * sum(terms) - (forward / k0 - 1.0) ** 2 / t
    if sigma2 <= 0:
        return None
    return {"sigma2": sigma2, "t_sigma2": t * sigma2, "forward": forward, "k0": k0, "used": len(usable)}


def vix_from_expiries(blocks):
    """blocks: [(days_to_expiry, expiry_variance_result)] sorted by days; interpolate to 30 days."""
    blocks = [(d, b) for d, b in blocks if b]
    if not blocks:
        return None
    if len(blocks) == 1:
        d, b = blocks[0]
        return 100.0 * math.sqrt(b["t_sigma2"] * 365.0 / TARGET_DAYS)
    (d1, b1), (d2, b2) = blocks[0], blocks[1]
    if d2 == d1:
        return None
    blended = (b1["t_sigma2"] * (d2 - TARGET_DAYS) + b2["t_sigma2"] * (TARGET_DAYS - d1)) / (d2 - d1)
    if blended <= 0:
        return None
    return 100.0 * math.sqrt(blended * 365.0 / TARGET_DAYS)


def strike_map(options):
    """Pair calls and puts by strike for one expiry of one day.
    options: iterable with .strike/.is_call/.close/.volume (chain.normalize slice options)."""
    by_strike = {}
    for o in options:
        if not o.volume or o.volume <= 0 or not _valid(o.close):
            continue
        slot = by_strike.setdefault(float(o.strike), {"call": None, "put": None})
        slot["call" if o.is_call else "put"] = o.close
    return [(k, v["call"], v["put"]) for k, v in sorted(by_strike.items())]


def daily_vix(day, expiry_blocks, rate):
    """expiry_blocks: {expiry_date: [(strike, call, put)]}; pick the two nearest expiries with
    >= ROLL_MIN_DAYS calendar days and compute the interpolated VIX, or None."""
    candidates = []
    for expiry, points in sorted(expiry_blocks.items()):
        days = (expiry - day).days
        if days < ROLL_MIN_DAYS:
            continue
        var = expiry_variance(points, days, rate)
        if var:
            candidates.append((days, var))
        if len(candidates) == 2:
            break
    return vix_from_expiries(candidates)


def series_stats(points, current_date):
    """points: [(date_iso, vix)] with nulls already removed; current = last point at current_date.
    Returns dVIX (vs previous point) and the share of window values <= current."""
    if not points:
        return None
    values = [v for _, v in points]
    current = values[-1]
    previous = None
    for d, v in reversed(points):
        if d < current_date:
            previous = v
            break
    return {"current": current, "previous": previous,
            "d_vix": (current - previous) if previous is not None else None,
            "percentile": sum(1 for v in values if v <= current + 1e-12) / len(values),
            "count": len(values), "min": min(values), "max": max(values),
            "first_date": points[0][0]}
