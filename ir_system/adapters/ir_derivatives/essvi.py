"""eSSVI equity surfaces (vol_surface_cn.tex sec. 6): SSVI skeleton, eSSVI bootstrap under the full
Proposition 3 calendar conditions, joint refinement, and price-space interpolation (eq. interp).

A slice is (theta, rho, psi) with psi = theta * phi; k is forward log-moneyness, theta the ATM total
variance in variance time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr

from . import black76

MARGIN = 1e-4  # relative inward margin on every constraint (SLSQP lands ~1e-5 outside active bounds)


def essvi_w(k, th, rho, psi):
    u = psi * np.asarray(k, dtype=float) + rho * th
    return 0.5 * (th + rho * psi * np.asarray(k, dtype=float) + np.sqrt(u * u + th * th * (1 - rho * rho)))


def essvi_derivs(k, th, rho, psi):
    k = np.asarray(k, dtype=float)
    u = psi * k + rho * th
    q = th * th * (1 - rho * rho)
    D = u * u + q
    sD = np.sqrt(D)
    return 0.5 * (th + rho * psi * k + sD), 0.5 * (rho * psi + psi * u / sD), 0.5 * psi * psi * q / (D * sD)


def g_function(k, th, rho, psi):
    w, wp, wpp = essvi_derivs(k, th, rho, psi)
    k = np.asarray(k, dtype=float)
    return (1 - k * wp / (2 * w)) ** 2 - 0.25 * wp * wp * (1 / w + 0.25) + 0.5 * wpp


def butterfly_params_ok(th, rho, psi):
    """Gatheral-Jacquier 2014 Thm 4.2 (sufficient, not necessary)."""
    return psi * (1 + abs(rho)) < 4 and psi * psi * (1 + abs(rho)) <= 4 * th


def calendar_ok(th1, r1, p1, th2, r2, p2, rtol=1e-12):
    """Necessary and sufficient no-crossing condition (Hendriks-Martini 2019 as corrected by Pasquazzi 2023),
    slice 1 expiring first. Slacks are scale-free; identical to the tex appendix C listing."""
    s1 = (th2 - th1) / th2
    dp = r2 * p2 - r1 * p1
    s2 = ((p2 - p1) - abs(dp)) / p2
    if th2 > th1 * (1 + rtol):
        phi1, phi2 = p1 / th1, p2 / th2
        s3 = max((phi1 - phi2) / phi2, ((th2 - th1) * (p2 ** 2 / th2 - p1 ** 2 / th1) - dp ** 2) / p2 ** 2)
    else:
        s3 = -abs(dp) / p2
    return (s1 >= -rtol and s2 >= -rtol and s3 >= -rtol), (float(s1), float(s2), float(s3))


def min_calendar_gap(s1, s2, kmax=6.0, n=1201):
    """min_k (w2 - w1) on a linear grid plus a log-spaced far grid; -inf when a wing slope decreases."""
    (t1, r1, p1), (t2, r2, p2) = s1, s2
    if p2 * (1 + r2) < p1 * (1 + r1) or p2 * (1 - r2) < p1 * (1 - r1):
        return float("-inf")
    far = np.logspace(np.log10(kmax), 6, 200)
    kk = np.concatenate([-far[::-1], np.linspace(-kmax, kmax, n), far])
    return float(np.min(essvi_w(kk, t2, r2, p2) - essvi_w(kk, t1, r1, p1)))


def power_law_phi(theta, eta, gamma):
    return eta / (theta ** gamma * (1 + theta) ** (1 - gamma))


def _fly_constraints(th, rho, psi):
    cap = 4 * (1 - MARGIN)
    return np.array([cap - psi * (1 + rho), cap - psi * (1 - rho),
                     cap - psi * psi * (1 + rho) / th, cap - psi * psi * (1 - rho) / th])


def _calendar_constraints(prev, cur):
    t1, r1, p1 = prev
    t2, r2, p2 = cur
    dp = r2 * p2 - r1 * p1
    branch1 = (p1 / t1 - p2 / t2) / (p2 / t2)
    branch2 = ((t2 - t1) * (p2 ** 2 / t2 - p1 ** 2 / t1) - dp ** 2) / p2 ** 2
    return np.array([(t2 - t1) / t2 - MARGIN, ((p2 - p1) - dp) / p2 - MARGIN, ((p2 - p1) + dp) / p2 - MARGIN,
                     max(branch1, branch2) - MARGIN])


@dataclass
class SliceData:
    tau: float
    k: np.ndarray
    sigma: np.ndarray
    lam: np.ndarray
    label: str = ""

    def objective(self, th, rho, psi):
        model = np.sqrt(np.maximum(essvi_w(self.k, th, rho, psi), 1e-14) / self.tau)
        return float(np.sum(self.lam * (model - self.sigma) ** 2))


def atm_guess(data: SliceData):
    """Market ATM total variance by linear interpolation of implied vol in k."""
    order = np.argsort(data.k)
    k, s = data.k[order], data.sigma[order]
    sigma0 = float(np.interp(0.0, k, s))
    return max(sigma0 * sigma0 * data.tau, 1e-8)


def fit_ssvi(slices, starts=((-0.5, 0.8, 0.4), (0.0, 0.8, 0.4), (0.3, 0.8, 0.4))):
    """Step 1: global (rho, eta, gamma) and monotone theta_i. eta(1+|rho|) <= 2, gamma in (0, 1/2]
    give a surface free of static arbitrage (GJ 2014), so the skeleton is always a valid fallback."""
    n = len(slices)
    theta0 = np.maximum.accumulate(np.array([atm_guess(s) for s in slices]))
    for i in range(1, n):
        theta0[i] = max(theta0[i], theta0[i - 1] * (1 + 1e-3))
    increments = np.diff(np.concatenate([[0.0], theta0]))
    scale = max(sum(len(s.k) for s in slices), 1)

    def unpack(z):
        rho = 0.998 * np.tanh(z[0])
        eta = (2 / (1 + abs(rho))) * (1 - MARGIN) / (1 + np.exp(-z[1]))
        gamma = 0.01 + 0.49 / (1 + np.exp(-z[2]))
        theta = np.cumsum(np.exp(z[3:]))
        return rho, eta, gamma, theta

    def objective(z):
        rho, eta, gamma, theta = unpack(z)
        total = 0.0
        for s, th in zip(slices, theta):
            total += s.objective(th, rho, th * power_law_phi(th, eta, gamma))
        return total / scale

    best = None
    for rho0, eta_frac, gamma0 in starts:
        z0 = np.concatenate([[np.arctanh(rho0 / 0.998), np.log(eta_frac / (1 - eta_frac)),
                              np.log((gamma0 - 0.01) / (0.5 - gamma0))], np.log(np.maximum(increments, 1e-10))])
        res = minimize(objective, z0, method="L-BFGS-B", options={"maxiter": 2000})
        if best is None or res.fun < best.fun:
            best = res
    rho, eta, gamma, theta = unpack(best.x)
    params = np.array([[th, rho, th * power_law_phi(th, eta, gamma)] for th in theta])
    return {"rho": float(rho), "eta": float(eta), "gamma": float(gamma), "params": params,
            "objective": float(best.fun * scale), "success": bool(best.success)}


def _slice_prior(prior, rho, psi):
    if prior is None:
        return 0.0
    rho0, psi0, d_rho, d_log_psi = prior
    return ((rho - rho0) / d_rho) ** 2 + ((np.log(max(psi, 1e-12)) - np.log(psi0)) / d_log_psi) ** 2


def _grid_floor(prev, kk):
    return essvi_w(kk, *prev)


def bootstrap(slices, skeleton, k_domain, prior_width=(0.25, 0.5), redundant_grid=True):
    """Step 2: slice-by-slice (theta_i, rho_i, psi_i) under GJ Thm 4.2 and Prop. 3 vs the previous slice."""
    kk = np.linspace(k_domain[0], k_domain[1], 41)
    out = []
    reports = []
    for i, s in enumerate(slices):
        th0, rho0, psi0 = skeleton[i]
        prior = (rho0, psi0, prior_width[0], prior_width[1])
        scale = max(len(s.k), 1)

        def objective(x, s=s, prior=prior, scale=scale):
            return (s.objective(*x) + _slice_prior(prior, x[1], x[2])) / scale

        cons = [{"type": "ineq", "fun": lambda x: _fly_constraints(*x)}]
        if out:
            prev = tuple(out[-1])
            cons.append({"type": "ineq", "fun": lambda x, prev=prev: _calendar_constraints(prev, x)})
            if redundant_grid:
                floor = _grid_floor(prev, kk)
                cons.append({"type": "ineq", "fun": lambda x, floor=floor: (essvi_w(kk, *x) - floor) / np.maximum(floor, 1e-12)})
        x0 = np.array([th0, rho0, psi0])
        if out:
            x0[0] = max(x0[0], out[-1][0] * (1 + 2 * MARGIN))
            x0[2] = max(x0[2], out[-1][2] * (1 + 2 * MARGIN))
        res = minimize(objective, x0, method="SLSQP", constraints=cons,
                       bounds=[(1e-7, 5.0), (-0.999, 0.999), (1e-7, 4.0)], options={"maxiter": 500, "ftol": 1e-12})
        x = np.asarray(res.x, dtype=float)
        feasible = bool(np.all(_fly_constraints(*x) >= -1e-9)) and (not out or bool(np.all(_calendar_constraints(tuple(out[-1]), x) >= -1e-9)))
        reports.append({"slice": s.label, "success": bool(res.success), "feasible": feasible, "message": str(res.message)})
        out.append(x)
    return np.array(out), reports


def joint_refine(slices, start, skeleton, prior_width=(0.25, 0.5)):
    """Step 3: all 3n parameters at once under the same constraints (spreads short-end noise back)."""
    n = len(slices)
    scale = max(sum(len(s.k) for s in slices), 1)
    priors = [(skeleton[i][1], skeleton[i][2], prior_width[0], prior_width[1]) for i in range(n)]

    def objective(z):
        x = z.reshape(n, 3)
        return sum(s.objective(*x[i]) + _slice_prior(priors[i], x[i][1], x[i][2]) for i, s in enumerate(slices)) / scale

    def constraints(z):
        x = z.reshape(n, 3)
        parts = [_fly_constraints(*x[i]) for i in range(n)]
        parts += [_calendar_constraints(tuple(x[i - 1]), x[i]) for i in range(1, n)]
        return np.concatenate(parts)

    res = minimize(objective, np.asarray(start, dtype=float).reshape(-1), method="SLSQP",
                   constraints=[{"type": "ineq", "fun": constraints}],
                   bounds=[(1e-7, 5.0), (-0.999, 0.999), (1e-7, 4.0)] * n, options={"maxiter": 800, "ftol": 1e-12})
    x = np.asarray(res.x, dtype=float).reshape(n, 3)
    feasible = bool(np.all(constraints(x.reshape(-1)) >= -1e-9))
    return x, bool(res.success), feasible, str(res.message)


def normalized_call(k, w):
    """Undiscounted call on a unit forward: N(d1) - e^k N(d2)."""
    k = np.asarray(k, dtype=float)
    sw = np.sqrt(np.maximum(w, 1e-16))
    d1 = -k / sw + 0.5 * sw
    return ndtr(d1) - np.exp(k) * ndtr(d1 - sw)


def total_variance_from_call(c, k):
    """Invert a unit-forward call to total variance using the out-of-the-money side for precision."""
    k = np.asarray(k, dtype=float)
    c = np.asarray(c, dtype=float)
    call_side = k >= 0
    otm = np.where(call_side, c, c - (1 - np.exp(k)))
    sigma = black76.implied_vol(otm, np.ones_like(k), np.exp(k), np.ones_like(k), np.ones_like(k), call_side)
    return sigma ** 2


@dataclass
class EquitySurface:
    taus: np.ndarray
    params: np.ndarray
    labels: list = field(default_factory=list)

    def theta_at(self, tau):
        t, th = self.taus, self.params[:, 0]
        if tau <= t[0]:
            return th[0] * tau / t[0]
        if tau >= t[-1]:
            return th[-1] * tau / t[-1]
        return float(np.interp(tau, t, th))

    def w(self, k, tau):
        """Total variance at variance time tau; price-space interpolation between slices (GJ 2014 sec. 5.3)."""
        k = np.asarray(k, dtype=float)
        t = self.taus
        for i, ti in enumerate(t):
            if abs(tau - ti) <= 1e-12:
                return essvi_w(k, *self.params[i])
        theta_t = self.theta_at(tau)
        if tau > t[-1]:
            return essvi_w(k, *self.params[-1]) + theta_t - self.params[-1][0]
        if tau < t[0]:
            th2 = self.params[0][0]
            alpha = (np.sqrt(th2) - np.sqrt(theta_t)) / np.sqrt(th2)
            c = alpha * np.maximum(1 - np.exp(k), 0.0) + (1 - alpha) * normalized_call(k, essvi_w(k, *self.params[0]))
            return total_variance_from_call(c, k)
        j = int(np.searchsorted(t, tau))
        p1, p2 = self.params[j - 1], self.params[j]
        alpha = (np.sqrt(p2[0]) - np.sqrt(theta_t)) / (np.sqrt(p2[0]) - np.sqrt(p1[0]))
        c = alpha * normalized_call(k, essvi_w(k, *p1)) + (1 - alpha) * normalized_call(k, essvi_w(k, *p2))
        return total_variance_from_call(c, k)

    def iv(self, k, tau):
        return np.sqrt(np.maximum(self.w(k, tau), 0.0) / tau)


def slice_stats(th, rho, psi, tau):
    """ATM level, ATM skew (Prop. skew: rho psi / (2 sqrt(theta tau))), wing slopes and 25-delta points."""
    atm = np.sqrt(th / tau)
    out = {"atm_vol": float(atm), "atm_skew": float(rho * psi / (2 * np.sqrt(th * tau))),
           "left_slope": float(psi * (1 - rho) / 2), "right_slope": float(psi * (1 + rho) / 2)}
    points = delta_points(lambda k: essvi_w(k, th, rho, psi), tau)
    out.update(points)
    return out


def delta_points(w_fn, tau, levels=(0.25, 0.10)):
    """Strikes at undiscounted forward deltas (put -d, call +d) on a smile; returns vols and RR/BF."""
    out = {}
    atm = float(np.sqrt(w_fn(np.array([0.0]))[0] / tau))
    grid = np.linspace(-2.5, 2.5, 501)
    w_grid = np.asarray(w_fn(grid), dtype=float)

    def find_crossing(lo, hi, target):
        mask = (grid >= lo) & (grid <= hi) & np.isfinite(w_grid) & (w_grid > 1e-12)
        kk, ww = grid[mask], w_grid[mask]
        if len(kk) < 5:
            return None
        sw = np.sqrt(ww)
        d1 = -kk / sw + 0.5 * sw
        err = (ndtr(d1) - target) if hi > 0 or lo >= 0 else (ndtr(-d1) - target)
        sign = np.sign(err)
        flips = np.where(np.diff(sign) != 0)[0]
        flips = [j for j in flips if np.isfinite(err[j]) and np.isfinite(err[j + 1])]
        if not flips:
            return None
        j = flips[0]
        a, b, fa = kk[j], kk[j + 1], err[j]
        for _ in range(60):
            mid = 0.5 * (a + b)
            w_mid = float(np.asarray(w_fn(np.array([mid])))[0])
            sw_mid = np.sqrt(max(w_mid, 1e-14))
            d1_mid = -mid / sw_mid + 0.5 * sw_mid
            fm = (ndtr(d1_mid) - target) if hi > 0 or lo >= 0 else (ndtr(-d1_mid) - target)
            if fa * fm <= 0:
                b = mid
            else:
                a, fa = mid, fm
        return 0.5 * (a + b)

    for d in levels:
        tag = int(round(d * 100))
        vols = {}
        for side, lo, hi in (("put", -2.5, 0.0), ("call", 0.0, 2.5)):
            k_star = find_crossing(lo, hi, d)
            if k_star is None:
                vols[side] = None
                continue
            w_star = float(np.asarray(w_fn(np.array([k_star])))[0])
            vols[side] = (float(k_star), float(np.sqrt(max(w_star, 0.0) / tau)))
        if vols.get("put") and vols.get("call"):
            out[f"k_put_{tag}d"], out[f"vol_put_{tag}d"] = vols["put"]
            out[f"k_call_{tag}d"], out[f"vol_call_{tag}d"] = vols["call"]
            out[f"rr_{tag}d"] = vols["call"][1] - vols["put"][1]
            out[f"bf_{tag}d"] = 0.5 * (vols["call"][1] + vols["put"][1]) - atm
    return out


def calibrate(slices, k_domain):
    """Run the three tex steps. Falls back to the SSVI skeleton when eSSVI is infeasible (rule r:equity)."""
    skeleton = fit_ssvi(slices)
    boot, boot_reports = bootstrap(slices, skeleton["params"], k_domain)
    boot_ok = all(r["feasible"] for r in boot_reports)
    method = "essvi_joint"
    params = boot
    joint_info = {"success": False, "feasible": False, "message": "skipped"}
    if boot_ok and len(slices) > 1:
        joint, success, feasible, message = joint_refine(slices, boot, skeleton["params"])
        joint_info = {"success": success, "feasible": feasible, "message": message}
        if feasible:
            params = joint
        else:
            method = "essvi_bootstrap"
    elif boot_ok:
        method = "essvi_bootstrap"
    else:
        params = skeleton["params"]
        method = "ssvi_fallback"
    return {"method": method, "params": params, "skeleton": skeleton, "bootstrap": boot_reports, "joint": joint_info}


def diagnostics(params, taus, k_domain, labels):
    """Validation check (2): min g on the declared domain, g(+-inf), exact and numerical calendar checks."""
    kk = np.linspace(k_domain[0], k_domain[1], 801)
    per_slice = []
    for i, (th, rho, psi) in enumerate(params):
        g = g_function(kk, th, rho, psi)
        c_left, c_right = psi * (1 - rho) / 2, psi * (1 + rho) / 2
        per_slice.append({"slice": labels[i], "min_g": float(g.min()), "argmin_k": float(kk[int(np.argmin(g))]),
                          "g_left_inf": float(0.25 - c_left ** 2 / 16), "g_right_inf": float(0.25 - c_right ** 2 / 16),
                          "gj_params_ok": bool(butterfly_params_ok(th, rho, psi))})
    pairs = []
    for i in range(1, len(params)):
        ok, slacks = calendar_ok(*params[i - 1], *params[i], rtol=1e-9)
        pairs.append({"pair": [labels[i - 1], labels[i]], "calendar_ok": bool(ok), "slacks": list(slacks),
                      "min_gap": min_calendar_gap(tuple(params[i - 1]), tuple(params[i]))})
    return {"slices": per_slice, "calendar": pairs,
            "butterfly_ok": all(s["min_g"] >= -1e-9 and min(s["g_left_inf"], s["g_right_inf"]) >= 0 for s in per_slice),
            "calendar_ok": all(p["calendar_ok"] for p in pairs)}
