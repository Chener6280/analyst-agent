"""Variance time (vol_surface_cn.tex eq. vartime) and the non-trading-day weight estimate.

tau(t, T) = [sum over d in (t, T] of omega(d)] / A, omega = 1 on trading days and omega_n otherwise,
A = total weight of the year after t. Valuation is at the day-session close, so the current day
contributes nothing (lambda_t = 0); a night session belongs to the next trading day.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np


@dataclass
class TradingCalendar:
    """Published open dates; dates past the published horizon fall back to weekdays."""
    days: list
    horizon: date | None = None
    fallback_used: set = field(default_factory=set)

    def __post_init__(self):
        self.days = sorted(set(self.days))
        self._set = set(self.days)
        if self.horizon is None and self.days:
            self.horizon = self.days[-1]

    def is_trading(self, day: date) -> bool:
        if self.horizon is not None and day <= self.horizon and self.days and day >= self.days[0]:
            return day in self._set
        self.fallback_used.add(day.year)
        return day.weekday() < 5

    def count(self, start: date, end: date):
        """(trading days, non-trading days) in (start, end]."""
        trading = other = 0
        day = start + timedelta(days=1)
        while day <= end:
            if self.is_trading(day):
                trading += 1
            else:
                other += 1
            day += timedelta(days=1)
        return trading, other

    def next_trading_day(self, day: date) -> date:
        probe = day + timedelta(days=1)
        for _ in range(40):
            if self.is_trading(probe):
                return probe
            probe += timedelta(days=1)
        raise ValueError("no trading day within 40 days")

    def previous_trading_days(self, day: date, count: int):
        index = bisect.bisect_right(self.days, day)
        return self.days[max(0, index - count):index]


class VarianceClock:
    def __init__(self, calendar: TradingCalendar, valuation: date, omega_n: float):
        self.calendar = calendar
        self.valuation = valuation
        self.omega_n = float(omega_n)
        trading, other = calendar.count(valuation, valuation + timedelta(days=365))
        self.annual_weight = trading + self.omega_n * other

    def tau(self, expiry: date) -> float:
        trading, other = self.calendar.count(self.valuation, expiry)
        return (trading + self.omega_n * other) / self.annual_weight

    def trading_days(self, expiry: date) -> int:
        return self.calendar.count(self.valuation, expiry)[0]

    def calendar_years(self, expiry: date) -> float:
        return (expiry - self.valuation).days / 365.0

    def one_day_step(self):
        """(delta tau, delta calendar years) from the valuation close to the next trading-day close."""
        nxt = self.calendar.next_trading_day(self.valuation)
        trading, other = self.calendar.count(self.valuation, nxt)
        return (trading + self.omega_n * other) / self.annual_weight, (nxt - self.valuation).days / 365.0


def estimate_omega(dates, closes, winsor=0.995):
    """E[r^2 | n] = sigma_d^2 (1 + omega_n n) by OLS of squared close-to-close returns on the number of
    intervening non-trading days n; squared returns are winsorized to limit crash-day leverage."""
    return estimate_omega_pooled([(dates, closes)], winsor)


def estimate_omega_pooled(series, winsor=0.995):
    """Same regression on several (dates, closes) series, e.g. the listed contracts of one commodity."""
    returns, gaps = [], []
    for dates, closes in series:
        dates = list(dates)
        closes = np.asarray(closes, dtype=float)
        if len(dates) < 3:
            continue
        returns.append(np.diff(np.log(closes)))
        gaps.append(np.array([(b - a).days - 1 for a, b in zip(dates[:-1], dates[1:])], dtype=float))
    if not returns or sum(len(r) for r in returns) < 120:
        raise ValueError("too few closes to estimate omega_n")
    returns = np.concatenate(returns)
    gaps = np.concatenate(gaps)
    keep = np.isfinite(returns) & (gaps >= 0) & (gaps <= 14)
    y = returns[keep] ** 2
    n = gaps[keep]
    y = np.minimum(y, np.quantile(y, winsor))
    X = np.column_stack([np.ones_like(n), n])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    cov = np.linalg.inv(X.T @ X) * (resid @ resid) / max(len(y) - 2, 1)
    a, b = coef
    raw = b / a if a > 0 else float("nan")
    grad = np.array([-b / a ** 2, 1 / a]) if a > 0 else np.array([np.nan, np.nan])
    se = float(np.sqrt(grad @ cov @ grad)) if a > 0 else float("nan")
    return {
        "omega": float(np.clip(raw, 0.0, 1.0)) if np.isfinite(raw) else 0.0,
        "raw": float(raw), "standard_error": se, "observations": int(len(y)),
        "multi_day_intervals": int(np.sum(n > 0)), "daily_variance": float(a),
    }
