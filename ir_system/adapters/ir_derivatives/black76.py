"""Black-76 on a forward plus a CRR tree for American futures options.

Diffusion runs on variance time ``tau`` and discounting on calendar time ``t_cal``
(vol_surface_cn.tex sec. 3.5), so every volatility here is per square-root variance-year.
Implied volatilities and Greeks are computed locally; vendor IV/Greek fields are never read.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr

_SQRT_2PI = float(np.sqrt(2.0 * np.pi))
IV_LOW, IV_HIGH = 1e-4, 6.0


def pdf(x):
    return np.exp(-0.5 * x * x) / _SQRT_2PI


def _arrays(*values):
    return [np.atleast_1d(np.array(v, dtype=float)) for v in np.broadcast_arrays(*(np.atleast_1d(np.asarray(v, dtype=float)) for v in values))]


def _flags(is_call, shape):
    return np.broadcast_to(np.asarray(is_call, dtype=bool), shape).copy()


def price(F, K, tau, sigma, D, is_call):
    F, K, tau, sigma, D = _arrays(F, K, tau, sigma, D)
    call = _flags(is_call, F.shape)
    out = D * np.where(call, np.maximum(F - K, 0.0), np.maximum(K - F, 0.0))
    s = sigma * np.sqrt(np.maximum(tau, 0.0))
    live = s > 0
    if np.any(live):
        f, k, sv, d = F[live], K[live], s[live], D[live]
        d1 = (np.log(f / k) + 0.5 * sv * sv) / sv
        d2 = d1 - sv
        value = np.where(call[live], f * ndtr(d1) - k * ndtr(d2), k * ndtr(-d2) - f * ndtr(-d1))
        out[live] = d * value
    return out


def implied_vol(P, F, K, tau, D, is_call, iterations=80):
    """Bisection on the monotone Black price; NaN when the price has no time value or breaks bounds."""
    P, F, K, tau, D = _arrays(P, F, K, tau, D)
    call = _flags(is_call, F.shape)
    intrinsic = D * np.where(call, np.maximum(F - K, 0.0), np.maximum(K - F, 0.0))
    upper = D * np.where(call, F, K)
    valid = np.isfinite(P) & np.isfinite(F) & (F > 0) & (K > 0) & (tau > 0) & (P > intrinsic) & (P < upper)
    lo = np.full(F.shape, IV_LOW)
    hi = np.full(F.shape, IV_HIGH)
    if np.any(valid):
        f, k, t, d, p, c = F[valid], K[valid], tau[valid], D[valid], P[valid], call[valid]
        a, b = lo[valid], hi[valid]
        for _ in range(iterations):
            mid = 0.5 * (a + b)
            higher = price(f, k, t, mid, d, c) > p
            b = np.where(higher, mid, b)
            a = np.where(higher, a, mid)
        lo[valid], hi[valid] = a, b
    sigma = 0.5 * (lo + hi)
    sigma[~valid] = np.nan
    # A root pinned to the bracket edge is not a solution.
    sigma[(sigma <= IV_LOW * 1.001) | (sigma >= IV_HIGH * 0.999)] = np.nan
    return sigma


def greeks(F, K, tau, sigma, D, is_call, t_cal):
    """European Greeks on the forward: delta/gamma per unit forward, vega/vanna/volga per 1.00 vol.

    rho_forward holds the forward fixed (futures underlyings); rho_spot holds spot fixed (ETF).
    Both are per 1.00 of the continuously compounded calendar-time rate.
    """
    F, K, tau, sigma, D, t_cal = _arrays(F, K, tau, sigma, D, t_cal)
    call = _flags(is_call, F.shape)
    sq = np.sqrt(np.maximum(tau, 0.0))
    s = np.maximum(sigma * sq, 1e-12)
    d1 = (np.log(F / K) + 0.5 * s * s) / s
    d2 = d1 - s
    n1 = pdf(d1)
    value = price(F, K, tau, sigma, D, call)
    delta = np.where(call, D * ndtr(d1), -D * ndtr(-d1))
    gamma = D * n1 / (F * s)
    vega = D * F * n1 * sq
    vanna = -D * n1 * d2 / np.maximum(sigma, 1e-12)
    volga = vega * d1 * d2 / np.maximum(sigma, 1e-12)
    rho_forward = -t_cal * value
    rho_spot = np.where(call, t_cal * K * D * ndtr(d2), -t_cal * K * D * ndtr(-d2))
    return {"price": value, "delta": delta, "gamma": gamma, "vega": vega, "vanna": vanna,
            "volga": volga, "rho_forward": rho_forward, "rho_spot": rho_spot, "d1": d1, "d2": d2}


@dataclass
class TreeResult:
    american: np.ndarray
    european: np.ndarray
    delta_american: np.ndarray
    delta_european: np.ndarray
    gamma_american: np.ndarray
    gamma_european: np.ndarray

    @property
    def premium(self):
        return np.maximum(self.american - self.european, 0.0)


def crr_tree(F, K, tau, sigma, t_cal, r, is_call, steps=200):
    """One CRR tree per option (futures: no drift). American and European share the tree, so their
    difference (the early-exercise premium) cancels most discretization error."""
    F, K, tau, sigma, t_cal = _arrays(F, K, tau, sigma, t_cal)
    call = _flags(is_call, F.shape)
    shape = F.shape
    F, K, tau, sigma, t_cal, call = (x.reshape(-1) for x in (F, K, tau, sigma, t_cal, call))
    n = max(int(steps), 3)
    u = np.exp(sigma * np.sqrt(np.maximum(tau, 1e-12) / n))
    d = 1.0 / u
    p = ((1.0 - d) / (u - d))[:, None]
    q = 1.0 - p
    disc = np.exp(-r * t_cal / n)[:, None]
    sign = np.where(call, 1.0, -1.0)[:, None]
    strike = K[:, None]
    nodes = F[:, None] * np.exp(np.outer(np.log(u), n - 2.0 * np.arange(n + 1)))
    va = np.maximum(sign * (nodes - strike), 0.0)
    ve = va.copy()
    keep = {}
    for step in range(n - 1, -1, -1):
        nodes = nodes[:, :-1] / u[:, None]
        ve = disc * (p * ve[:, :-1] + q * ve[:, 1:])
        va = np.maximum(disc * (p * va[:, :-1] + q * va[:, 1:]), sign * (nodes - strike))
        if step in (1, 2):
            keep[step] = (va.copy(), ve.copy(), nodes.copy())

    def first(values, level):
        return (values[:, 0] - values[:, 1]) / (level[:, 0] - level[:, 1])

    def second(values, level):
        up = (values[:, 0] - values[:, 1]) / (level[:, 0] - level[:, 1])
        down = (values[:, 1] - values[:, 2]) / (level[:, 1] - level[:, 2])
        return (up - down) / (0.5 * (level[:, 0] - level[:, 2]))

    a1, e1, f1 = keep[1]
    a2, e2, f2 = keep[2]
    out = TreeResult(va[:, 0], ve[:, 0], first(a1, f1), first(e1, f1), second(a2, f2), second(e2, f2))
    for name in ("american", "european", "delta_american", "delta_european", "gamma_american", "gamma_european"):
        setattr(out, name, getattr(out, name).reshape(shape))
    return out


def american_implied_vol(P, F, K, tau, t_cal, r, is_call, steps=200, rounds=3):
    """De-Americanize (tex sec. 3.4): solve sigma with Black(sigma) + EEP_tree(sigma) = P.

    Returns (sigma, early_exercise_premium). NaN where the premium leaves no European time value."""
    P, F, K, tau, t_cal = _arrays(P, F, K, tau, t_cal)
    call = _flags(is_call, F.shape)
    D = np.exp(-r * t_cal)
    sigma = implied_vol(P, F, K, tau, D, call)
    premium = np.zeros(F.shape)
    for _ in range(rounds):
        ok = np.isfinite(sigma)
        if not np.any(ok):
            break
        premium = np.zeros(F.shape)
        premium[ok] = crr_tree(F[ok], K[ok], tau[ok], sigma[ok], t_cal[ok], r, call[ok], steps).premium
        sigma = implied_vol(P - premium, F, K, tau, D, call)
    return sigma, premium


def american_greeks(F, K, tau, sigma, t_cal, r, is_call, steps=200):
    """Black Greeks plus tree corrections for the early-exercise premium (control variate)."""
    F, K, tau, sigma, t_cal = _arrays(F, K, tau, sigma, t_cal)
    call = _flags(is_call, F.shape)
    D = np.exp(-r * t_cal)
    base = greeks(F, K, tau, sigma, D, call, t_cal)
    tree = crr_tree(F, K, tau, sigma, t_cal, r, call, steps)
    h = np.maximum(0.01 * sigma, 1e-4)
    up = crr_tree(F, K, tau, sigma + h, t_cal, r, call, steps).premium
    down = crr_tree(F, K, tau, np.maximum(sigma - h, 1e-4), t_cal, r, call, steps).premium
    bump = 1e-4
    rate_up = crr_tree(F, K, tau, sigma, t_cal, r + bump, call, steps).premium
    out = dict(base)
    out["price"] = base["price"] + tree.premium
    out["delta"] = base["delta"] + (tree.delta_american - tree.delta_european)
    out["gamma"] = base["gamma"] + (tree.gamma_american - tree.gamma_european)
    out["vega"] = base["vega"] + (up - down) / (sigma + h - np.maximum(sigma - h, 1e-4))
    out["rho_forward"] = base["rho_forward"] + (rate_up - tree.premium) / bump
    out["premium"] = tree.premium
    return out
