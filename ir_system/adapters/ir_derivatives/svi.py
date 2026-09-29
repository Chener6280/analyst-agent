"""Raw SVI slices: Zeliade quasi-explicit fit, butterfly function g(k), constrained refits.

Coordinates are forward log-moneyness k and total variance w = sigma^2 * tau (variance time).
Objective is the tex eq. (obj) in implied-volatility space; the inner Zeliade step works in
total-variance space with weights linearized by d sigma = d w / (2 sqrt(w tau)).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import lsq_linear, minimize

LEE_SLOPE = 2.0  # wing slope bound b(1+|rho|) <= 2 (Lee moment formula; tex sec. 4.1 uses 2 sigma instead of 4 sigma)


def raw_w(k, p):
    a, b, rho, m, s = p
    x = np.asarray(k, dtype=float) - m
    return a + b * (rho * x + np.sqrt(x * x + s * s))


def raw_derivs(k, p):
    a, b, rho, m, s = p
    x = np.asarray(k, dtype=float) - m
    r = np.sqrt(x * x + s * s)
    return a + b * (rho * x + r), b * (rho + x / r), b * s * s / r ** 3


def g_function(k, w, wp, wpp):
    k = np.asarray(k, dtype=float)
    return (1 - k * wp / (2 * w)) ** 2 - 0.25 * wp * wp * (1 / w + 0.25) + 0.5 * wpp


def wing_slopes(p):
    _, b, rho, _, _ = p
    return b * (1 - rho), b * (1 + rho)


def g_limits(slopes):
    """g(+-inf) = 1/4 - c^2/16 for wings linear in |k| (tex sec. 5.2)."""
    return [0.25 - c * c / 16 for c in slopes]


def jump_wings(p, tau):
    """SVI-JW (v, psi, p, c, v_tilde) of Gatheral-Jacquier 2014, per variance-time year."""
    a, b, rho, m, s = p
    root = np.sqrt(m * m + s * s)
    w_atm = a + b * (-rho * m + root)
    if w_atm <= 0 or tau <= 0:
        return None
    sw = np.sqrt(w_atm)
    return {"v": w_atm / tau, "psi": b / (2 * sw) * (-m / root + rho), "p": b * (1 - rho) / sw,
            "c": b * (1 + rho) / sw, "v_tilde": (a + b * s * np.sqrt(1 - rho * rho)) / tau}


def _vol_objective(w_model, sigma_mkt, lam, tau):
    sigma_model = np.sqrt(np.maximum(w_model, 1e-12) / tau)
    return float(np.sum(lam * (sigma_model - sigma_mkt) ** 2))


def _inner(k, w_mkt, lin_weights, m, s, w_cap, lee):
    """Box-constrained linear least squares in (a, u, v), u = c + d, v = c - d (c = b s, d = rho b s).

    0 <= u, v <= lee*s encodes |d| <= c and c + |d| <= lee*s, i.e. b(1+|rho|) <= lee."""
    y = (k - m) / s
    root = np.sqrt(y * y + 1)
    A = np.column_stack([np.ones_like(y), 0.5 * (y + root), 0.5 * (root - y)])
    sw = np.sqrt(lin_weights)
    res = lsq_linear(A * sw[:, None], w_mkt * sw, bounds=([0.0, 0.0, 0.0], [w_cap, lee * s, lee * s]), method="bvls")
    a, u, v = res.x
    c, d = 0.5 * (u + v), 0.5 * (u - v)
    b = c / s
    rho = d / c if c > 1e-14 else 0.0
    return np.array([a, b, float(np.clip(rho, -0.999999, 0.999999)), m, s])


def fit_zeliade(k, sigma_mkt, lam, tau, lee=LEE_SLOPE, prior=None):
    """Two-dimensional search over (m, sigma) with the Zeliade inner problem.

    prior: optional (theta_target, weight) pulling w(0) toward theta_target (commodity regularization).
    Returns (params, objective)."""
    k = np.asarray(k, dtype=float)
    sigma_mkt = np.asarray(sigma_mkt, dtype=float)
    lam = np.asarray(lam, dtype=float)
    w_mkt = sigma_mkt ** 2 * tau
    lin = lam / np.maximum(4.0 * w_mkt * tau, 1e-16)
    w_cap = float(np.max(w_mkt))
    span = max(float(k.max() - k.min()), 0.05)
    m_lo, m_hi = float(k.min()) - span, float(k.max()) + span
    s_lo, s_hi = 1e-3, max(1.5 * span, 0.05)

    def total(p):
        value = _vol_objective(raw_w(k, p), sigma_mkt, lam, tau)
        if prior is not None:
            target, weight = prior
            atm = np.sqrt(max(raw_w(0.0, p), 1e-12) / tau)
            value += weight * (atm - np.sqrt(target / tau)) ** 2
        return value

    def outer(x):
        m, s = float(np.clip(x[0], m_lo, m_hi)), float(np.clip(x[1], s_lo, s_hi))
        return total(_inner(k, w_mkt, lin, m, s, w_cap, lee))

    best = None
    for m0 in np.linspace(float(k.min()), float(k.max()), 5):
        for s0 in (0.03, 0.08, 0.2, 0.5):
            if s0 > s_hi:
                continue
            value = outer((m0, s0))
            if best is None or value < best[0]:
                best = (value, (m0, s0))
    res = minimize(outer, np.array(best[1]), method="Nelder-Mead", bounds=[(m_lo, m_hi), (s_lo, s_hi)],
                   options={"xatol": 1e-6, "fatol": 1e-12, "maxiter": 600})
    x = res.x if res.fun <= best[0] else np.array(best[1])
    params = _inner(k, w_mkt, lin, float(np.clip(x[0], m_lo, m_hi)), float(np.clip(x[1], s_lo, s_hi)), w_cap, lee)
    return params, total(params)


def check_slice(p, k_domain, n=401):
    """Numerical butterfly diagnostics on the declared domain plus the wing limits."""
    kk = np.linspace(k_domain[0], k_domain[1], n)
    w, wp, wpp = raw_derivs(kk, p)
    g = g_function(kk, w, wp, wpp)
    slopes = wing_slopes(p)
    limits = g_limits(slopes)
    return {"min_g": float(np.min(g)), "argmin_k": float(kk[int(np.argmin(g))]), "g_left_inf": float(limits[0]),
            "g_right_inf": float(limits[1]), "min_w": float(np.min(w)), "wing_slopes": [float(slopes[0]), float(slopes[1])],
            "butterfly_ok": bool(np.min(g) >= -1e-9 and min(limits) >= -1e-12 and np.min(w) > 0)}


def refit_constrained(p0, k, sigma_mkt, lam, tau, k_domain, floor=None, prior=None, lee=LEE_SLOPE, n_grid=81):
    """SLSQP on raw parameters with g(k) >= 0 on a domain grid, Lee wing bounds and, optionally,
    w(k) >= floor(k) (same-underlying earlier slice). Used only when the Zeliade result fails a check."""
    k = np.asarray(k, dtype=float)
    kk = np.linspace(k_domain[0], k_domain[1], n_grid)
    floor_values = None if floor is None else np.asarray(floor(kk), dtype=float)
    scale = max(float(np.sum(lam)) * 1e-4, 1e-12)

    def objective(p):
        value = _vol_objective(raw_w(k, p), sigma_mkt, lam, tau)
        if prior is not None:
            target, weight = prior
            atm = np.sqrt(max(raw_w(0.0, p), 1e-12) / tau)
            value += weight * (atm - np.sqrt(target / tau)) ** 2
        return value / scale

    cons = [
        {"type": "ineq", "fun": lambda p: g_function(kk, *raw_derivs(kk, p))},
        {"type": "ineq", "fun": lambda p: np.array([lee - p[1] * (1 + p[2]), lee - p[1] * (1 - p[2])])},
        {"type": "ineq", "fun": lambda p: np.array([p[0] + p[1] * p[4] * np.sqrt(max(1 - p[2] ** 2, 0.0)) - 1e-10])},
    ]
    if floor_values is not None:
        cons.append({"type": "ineq", "fun": lambda p: raw_w(kk, p) - floor_values * (1 + 1e-4)})
    bounds = [(-1.0, 5.0), (0.0, 10.0), (-0.999, 0.999), (k_domain[0] - 1.0, k_domain[1] + 1.0), (1e-3, 3.0)]
    res = minimize(objective, np.asarray(p0, dtype=float), method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 400, "ftol": 1e-12})
    return np.asarray(res.x, dtype=float), bool(res.success), str(res.message)
