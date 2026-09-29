"""Cross-group ATM structure for commodity options (vol_surface_cn.tex sec. 7.2, eq. thetass/cmreg).

theta_j = int_0^{T_o} s(u) v(u; T_F) du with the Schwartz-Smith futures variance
v(u; T_F) = sx^2 + 2 rho sc sx e^{-kappa (T_F - u)} + sc^2 e^{-2 kappa (T_F - u)} and an optional
calendar seasonal multiplier s(u) = 1 + a cos(2 pi (u - u_peak)). Total variance is clock-free, so the
model integrates over calendar years while slice vols stay in variance time.
Groups are different underlyings: nothing here is an arbitrage constraint, only a prior.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

_NODES, _WEIGHTS = np.polynomial.legendre.leggauss(64)


def theta_closed(T_o, T_F, sx, sc, kappa, rho):
    T_o, T_F = np.asarray(T_o, dtype=float), np.asarray(T_F, dtype=float)
    L = T_F - T_o
    return (sx ** 2 * T_o + 2 * rho * sc * sx / kappa * (np.exp(-kappa * L) - np.exp(-kappa * T_F))
            + sc ** 2 / (2 * kappa) * (np.exp(-2 * kappa * L) - np.exp(-2 * kappa * T_F)))


def theta_seasonal(T_o, T_F, sx, sc, kappa, rho, a, u_peak, t0_year_fraction):
    """Gauss-Legendre quadrature; u is calendar years from valuation, t0_year_fraction positions the
    valuation date inside the calendar year so the seasonal phase is a calendar property."""
    T_o, T_F = np.atleast_1d(np.asarray(T_o, dtype=float)), np.atleast_1d(np.asarray(T_F, dtype=float))
    out = np.empty_like(T_o)
    for i, (to, tf) in enumerate(zip(T_o, T_F)):
        u = 0.5 * to * (_NODES + 1)
        s = tf - u
        v = sx ** 2 + 2 * rho * sc * sx * np.exp(-kappa * s) + sc ** 2 * np.exp(-2 * kappa * s)
        season = 1 + a * np.cos(2 * np.pi * (u + t0_year_fraction - u_peak))
        out[i] = 0.5 * to * np.sum(_WEIGHTS * season * v)
    return out


def fit_theta_model(T_o, T_F, theta, weights, t0_year_fraction):
    """Fit log theta; model size follows the number of groups (4 params from 6 groups, seasonality
    from 8 groups and only when AICc improves). Returns None below 3 groups."""
    T_o, T_F, theta, weights = (np.asarray(x, dtype=float) for x in (T_o, T_F, theta, weights))
    n = len(theta)
    if n < 3:
        return None
    sw = np.sqrt(np.maximum(weights, 1e-9) / np.max(weights))
    target = np.log(theta)
    candidates = []

    def run(name, model, x0, lo, hi):
        def resid(x):
            value = model(x)
            return sw * (np.log(np.maximum(value, 1e-12)) - target)
        try:
            res = least_squares(resid, x0, bounds=(lo, hi), max_nfev=4000)
        except Exception:
            return
        k = len(x0)
        rss = float(np.sum(res.fun ** 2))
        aicc = n * np.log(max(rss / n, 1e-18)) + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else np.inf)
        candidates.append({"name": name, "x": res.x, "rss": rss, "aicc": float(aicc), "model": model})

    base_sigma = float(np.sqrt(np.median(theta / T_o)))
    if n >= 6:
        run("two_factor", lambda x: theta_closed(T_o, T_F, *x),
            [base_sigma * 0.7, base_sigma * 0.7, 1.5, 0.0], [0.005, 0.0, 0.05, -0.99], [3.0, 5.0, 20.0, 0.99])
    run("two_factor_fixed", lambda x: theta_closed(T_o, T_F, x[0], x[1], 2.0, 0.0),
        [base_sigma * 0.7, base_sigma * 0.7], [0.005, 0.0], [3.0, 5.0])
    if n >= 8:
        run("two_factor_seasonal", lambda x: theta_seasonal(T_o, T_F, *x, t0_year_fraction),
            [base_sigma * 0.7, base_sigma * 0.7, 1.5, 0.0, 0.2, 0.3], [0.005, 0.0, 0.05, -0.99, 0.0, 0.0],
            [3.0, 5.0, 20.0, 0.99, 0.95, 1.0])
    if not candidates:
        return None
    best = min(candidates, key=lambda c: c["aicc"] if np.isfinite(c["aicc"]) else c["rss"] * 1e6)
    x = best["x"]
    names = {"two_factor": ("sigma_xi", "sigma_chi", "kappa", "rho"),
             "two_factor_fixed": ("sigma_xi", "sigma_chi"),
             "two_factor_seasonal": ("sigma_xi", "sigma_chi", "kappa", "rho", "season_a", "season_peak")}[best["name"]]
    params = {name: float(value) for name, value in zip(names, x)}
    if best["name"] == "two_factor_fixed":
        params.update({"kappa": 2.0, "rho": 0.0, "fixed": ["kappa", "rho"]})
    fitted = best["model"](x)
    return {"model": best["name"], "params": params, "fitted_theta": [float(v) for v in fitted],
            "log_rmse": float(np.sqrt(best["rss"] / n)), "aicc": best["aicc"],
            "compared": [{"model": c["name"], "aicc": c["aicc"], "rss": c["rss"]} for c in candidates]}
