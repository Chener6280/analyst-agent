"""Surface pipeline on EOD chains: forwards, self-computed implied vols, weights, calibration,
diagnostics and Greeks for every listed option (vendor IV/Greek fields are never read).

Equity (ETF, index options, European): eSSVI surface with price-space interpolation.
Commodity (American on futures): de-Americanized IV, SVI per slice, calendar only inside an
underlying group, Schwartz-Smith ATM prior across groups.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

import numpy as np

from . import black76, chain, commodity, essvi, svi

S_MIN = 0.005          # 50 bp floor: EOD closes are not synchronous with the underlying close
DELTA_MAX = 0.005      # rule r:filter, one tick worth more than 50 bp of vol is dropped
MIN_TICKS = 3
MIN_TRADING_DAYS = 3   # tex sec. 6.4: near-expiry slices leave the calibration
MIN_POINTS = 5
TREE_STEPS = 200
PRIOR_ATM_WIDTH = 0.005  # commodity cross-group ATM prior counts as one pseudo-quote of 50 bp
DELTA_LEVELS = (0.10, 0.25)
TENORS_DAYS = (30, 60, 90, 180)


def _f(value, digits=6):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if value == 0:
        return 0.0
    return float(f"{value:.{digits}g}")


def _vol_weight(volume):
    volume = np.asarray(volume, dtype=float)
    return volume / (volume + 5.0)


def _prepare(slice_, F, D, tau, american, rate, t_cal, tick):
    """Market IV for every traded option plus the calibration subset and its weights.

    ETF dividend-adjusted (A) contracts are converted to standard-share units for pricing:
    factor f = size/10000, K_std = K f, P_std = close f (strike cut by f at the dividend, size up by f)."""
    opts = slice_.options
    factor = np.ones(len(opts))
    if slice_.family == "etf":
        for i, o in enumerate(opts):
            if o.adjusted and o.contract_size:
                factor[i] = o.contract_size / 10000.0
    K = np.array([o.strike for o in opts]) * factor
    call = np.array([o.is_call for o in opts])
    P = np.array([o.close if o.traded else np.nan for o in opts], dtype=float) * factor
    premium = np.zeros(len(opts))
    if american:
        iv, premium = black76.american_implied_vol(P, np.full(len(opts), F), K, np.full(len(opts), tau),
                                                   np.full(len(opts), t_cal), rate, call, TREE_STEPS)
    else:
        iv = black76.implied_vol(P, np.full(len(opts), F), K, np.full(len(opts), tau), np.full(len(opts), D), call)
    vega = black76.greeks(np.full(len(opts), F), K, np.full(len(opts), tau), np.where(np.isfinite(iv), iv, 0.2),
                          np.full(len(opts), D), call, np.full(len(opts), t_cal))["vega"]
    width = np.where(vega > 0, (tick or 0.0) / vega, np.inf)
    chosen = {id(o) for o in chain.select_quotes(opts, F, tick, min_ticks=MIN_TICKS, strikes=K)}
    use = np.array([id(o) in chosen for o in opts]) & np.isfinite(iv) & (width <= DELTA_MAX)
    lam = _vol_weight([o.volume for o in opts]) / np.maximum(width, S_MIN) ** 2
    k = np.log(K / F)
    return {"K": K, "call": call, "P": P, "factor": factor, "iv": iv, "premium": premium, "width": width,
            "use": use, "lam": lam, "k": k}


def _greeks(american, F, K, tau, sigma, t_cal, rate, call, step):
    n = len(K)
    F_arr, tau_arr, t_arr = np.full(n, F), np.full(n, tau), np.full(n, t_cal)
    D = math.exp(-rate * t_cal)
    if american:
        g = black76.american_greeks(F_arr, K, tau_arr, sigma, t_arr, rate, call, TREE_STEPS)
    else:
        g = black76.greeks(F_arr, K, tau_arr, sigma, np.full(n, D), call, t_arr)
        g["premium"] = np.zeros(n)
    dtau, dcal = step
    tau2, t2 = max(tau - dtau, 0.0), max(t_cal - dcal, 0.0)
    intrinsic = np.where(call, np.maximum(F - K, 0.0), np.maximum(K - F, 0.0))
    if tau2 <= 1e-10:
        later = intrinsic
    elif american:
        later = black76.crr_tree(F_arr, K, np.full(n, tau2), sigma, np.full(n, t2), rate, call, TREE_STEPS).american
    else:
        later = black76.price(F_arr, K, np.full(n, tau2), sigma, np.full(n, math.exp(-rate * t2)), call)
    g["theta"] = later - g["price"]
    return g


def _option_rows(slice_, prep, model_iv, F, tau, t_cal, rate, american, step, spot, atm_skew):
    opts = slice_.options
    K, call = prep["K"], prep["call"]
    rows = []
    model_ok = np.isfinite(model_iv) & (model_iv > 0)
    g_model = _greeks(american, F, K, tau, np.where(model_ok, model_iv, 0.2), t_cal, rate, call, step) if np.any(model_ok) else None
    mkt_ok = np.isfinite(prep["iv"])
    g_mkt = _greeks(american, F, K, tau, np.where(mkt_ok, prep["iv"], 0.2), t_cal, rate, call, step) if np.any(mkt_ok) else None
    ratio = F / spot if spot else 1.0
    level = spot if spot else F
    for i, o in enumerate(opts):
        size = o.contract_size or 1.0
        row = {"contract": o.contract, "type": "C" if o.is_call else "P", "strike": _f(o.strike, 8), "k": _f(prep["k"][i]),
               "close": _f(o.close, 8), "settlement": _f(o.settlement, 8), "volume": _f(o.volume), "oi": _f(o.open_interest),
               "traded": o.traded, "used": bool(prep["use"][i]), "adjusted": o.adjusted, "size": _f(size),
               "iv_mkt": _f(prep["iv"][i]) if mkt_ok[i] else None, "iv_model": _f(model_iv[i]) if model_ok[i] else None,
               "tick_width_bp": _f(prep["width"][i] * 1e4, 4) if np.isfinite(prep["width"][i]) else None}
        if o.adjusted:
            # Pricing ran in standard-share units; quoted close is per A unit and exact per-unit Greeks
            # need the full adjustment history, so only the rescaled strike and IV are shown.
            row["strike_std"] = _f(prep["K"][i], 8)
            rows.append(row)
            continue
        if mkt_ok[i] and model_ok[i]:
            row["resid_bp"] = _f((prep["iv"][i] - model_iv[i]) * 1e4, 4)
        for tag, g, ok in (("model", g_model, model_ok), ("mkt", g_mkt, mkt_ok)):
            if g is None or not ok[i]:
                continue
            delta = g["delta"][i] * ratio
            gamma = g["gamma"][i] * ratio * ratio
            out = {"price": _f(g["price"][i]), "delta": _f(delta), "gamma": _f(gamma), "vega": _f(g["vega"][i] / 100),
                   "theta": _f(g["theta"][i]), "vanna": _f(g["vanna"][i] / 100), "volga": _f(g["volga"][i] / 1e4),
                   "rho": _f((g["rho_spot"][i] if spot else g["rho_forward"][i]) / 100),
                   "delta_cash": _f(delta * level * size), "gamma_1pct_cash": _f(gamma * level * level * 0.01 * size),
                   "vega_cash": _f(g["vega"][i] / 100 * size), "theta_cash": _f(g["theta"][i] * size)}
            if american:
                out["eep"] = _f(g.get("premium", np.zeros(len(opts)))[i])
            if atm_skew is not None and tag == "model":
                # tex eq. smiledelta with R = 0 (sticky moneyness); R itself is not estimated here.
                out["delta_sticky_moneyness"] = _f(delta - g["vega"][i] * atm_skew / F * ratio)
            row[tag] = out
        if american and mkt_ok[i]:
            row["eep_mkt"] = _f(prep["premium"][i])
        rows.append(row)
    return rows


def _slice_header(s, valuation, tau, t_cal, trading_days, F, F_source, D, tick, pcp):
    return {"key": s.key, "series": s.series_id, "underlying": s.underlying, "serial": s.serial,
            "expiry": s.expiry.isoformat(), "contract_month": s.contract_month, "tau": _f(tau), "t_cal": _f(t_cal),
            "trading_days": trading_days, "calendar_days": (s.expiry - valuation).days,
            "forward": _f(F, 8), "forward_source": F_source, "discount": _f(D, 8), "tick": tick, "pcp": pcp}


def _fit_stats(prep, model_iv):
    use = prep["use"]
    if not np.any(use):
        return {"points": 0}
    err = (prep["iv"][use] - model_iv[use]) * 1e4
    lam = prep["lam"][use]
    k = prep["k"][use]
    buckets = {}
    for name, lo, hi in (("put_wing", -9, -0.1), ("near_atm", -0.1, 0.1), ("call_wing", 0.1, 9)):
        mask = (k > lo) & (k <= hi)
        if np.any(mask):
            buckets[name] = {"points": int(mask.sum()), "rmse_bp": _f(np.sqrt(np.mean(err[mask] ** 2)), 4),
                             "bias_bp": _f(np.mean(err[mask]), 4)}
    within = np.abs(err) <= np.maximum(prep["width"][use], S_MIN) * 1e4
    return {"points": int(use.sum()), "rmse_bp": _f(np.sqrt(np.mean(err ** 2)), 4),
            "wrmse_bp": _f(np.sqrt(np.sum(lam * err ** 2) / np.sum(lam)), 4), "max_abs_bp": _f(np.max(np.abs(err)), 4),
            "within_width": _f(np.mean(within), 4), "buckets": buckets}


def _curve(w_fn, tau, k_lo, k_hi, n=61):
    kk = np.linspace(k_lo, k_hi, n)
    w = np.asarray(w_fn(kk), dtype=float)
    return {"k": [_f(x, 5) for x in kk], "iv": [_f(math.sqrt(max(x, 0.0) / tau), 5) for x in w]}


def equity_surface(slices, *, family, valuation, clock, rate, spot=None, futures=None):
    """ETF options (forward from parity, no dividend deduction, Prop. etf) and index options
    (forward = same-month future, parity for the far quarterlies)."""
    futures = futures or {}
    tick = chain.infer_tick([o.close for s in slices for o in s.options] + [o.settlement for s in slices for o in s.options])
    step = clock.one_day_step()
    prepared, excluded = [], []
    for s in slices:
        tau, t_cal, td = clock.tau(s.expiry), clock.calendar_years(s.expiry), clock.trading_days(s.expiry)
        if tau <= 0 or t_cal <= 0:
            continue
        D = math.exp(-rate * t_cal)
        reference = spot * math.exp(rate * t_cal) if spot else None
        pcp = chain.pcp_forward(s.options, D, reference=reference)
        future = futures.get(s.underlying) if family == "index" else None
        if future:
            F, source = future, "futures_close"
        elif pcp:
            F, source = pcp["forward"], "put_call_parity"
        elif reference:
            F, source = reference, "carry_reference"
        else:
            excluded.append({"key": s.key, "reason": "no_forward"})
            continue
        prep = _prepare(s, F, D, tau, False, rate, t_cal, tick)
        header = _slice_header(s, valuation, tau, t_cal, td, F, source, D, tick, pcp)
        reason = None
        if td < MIN_TRADING_DAYS:
            reason = "near_expiry"
        elif int(prep["use"].sum()) < MIN_POINTS:
            reason = "too_few_quotes"
        prepared.append({"slice": s, "prep": prep, "F": F, "D": D, "tau": tau, "t_cal": t_cal, "header": header, "reason": reason})
    calib = [p for p in prepared if p["reason"] is None]
    if not calib:
        return {"status": "insufficient", "family": family, "tick": tick, "excluded": excluded,
                "slices": [dict(p["header"], excluded=p["reason"]) for p in prepared]}
    calib.sort(key=lambda p: p["tau"])
    data = [essvi.SliceData(p["tau"], p["prep"]["k"][p["prep"]["use"]], p["prep"]["iv"][p["prep"]["use"]],
                            p["prep"]["lam"][p["prep"]["use"]], p["header"]["expiry"]) for p in calib]
    k_all = np.concatenate([d.k for d in data])
    k_domain = (float(k_all.min()) - 0.05, float(k_all.max()) + 0.05)
    fit = essvi.calibrate(data, k_domain)
    surf = essvi.EquitySurface(np.array([d.tau for d in data]), fit["params"], [d.label for d in data])
    diag = essvi.diagnostics(fit["params"], surf.taus, k_domain, surf.labels)
    out_slices = []
    param_by_key = {p["slice"].key: fit["params"][i] for i, p in enumerate(calib)}
    for p in sorted(prepared, key=lambda item: item["tau"]):
        prep, tau = p["prep"], p["tau"]
        model_iv = surf.iv(prep["k"], tau)
        header = dict(p["header"])
        params = param_by_key.get(p["slice"].key)
        if params is not None:
            th, rho, psi = params
            header["params"] = {"theta": _f(th), "rho": _f(rho), "psi": _f(psi)}
            header["stats"] = {key: _f(value) for key, value in essvi.slice_stats(th, rho, psi, tau).items()}
            atm_skew = header["stats"]["atm_skew"]
        else:
            header["excluded"] = p["reason"]
            w_fn = lambda kk, tau=tau: surf.w(kk, tau)
            stats = essvi.delta_points(w_fn, tau)
            atm = float(np.sqrt(surf.w(np.array([0.0]), tau)[0] / tau))
            header["stats"] = {"atm_vol": _f(atm), **{key: _f(value) for key, value in stats.items()}}
            atm_skew = None
        header["fit"] = _fit_stats(prep, model_iv)
        header["curve"] = _curve(lambda kk, tau=tau: surf.w(kk, tau), tau, k_domain[0], k_domain[1])
        header["options"] = _option_rows(p["slice"], prep, model_iv, p["F"], tau, p["t_cal"], rate, False, step, spot, atm_skew)
        out_slices.append(header)
    grid = []
    for days in TENORS_DAYS:
        tau = clock.tau(valuation + timedelta(days=days))
        stats = essvi.delta_points(lambda kk, tau=tau: surf.w(kk, tau), tau, DELTA_LEVELS)
        atm = float(np.sqrt(surf.w(np.array([0.0]), tau)[0] / tau))
        grid.append({"days": days, "tau": _f(tau), "atm_vol": _f(atm), "extrapolated": bool(tau > surf.taus[-1] or tau < surf.taus[0]),
                     **{key: _f(value) for key, value in stats.items()}})
    skeleton = fit["skeleton"]
    return {"status": "ok", "family": family, "model": fit["method"], "tick": tick, "k_domain": [_f(k_domain[0]), _f(k_domain[1])],
            "ssvi": {"rho": _f(skeleton["rho"]), "eta": _f(skeleton["eta"]), "gamma": _f(skeleton["gamma"])},
            "calibration": {"bootstrap": fit["bootstrap"], "joint": fit["joint"]}, "diagnostics": diag,
            "slices": out_slices, "grid": grid, "excluded": excluded, "theta_step": [_f(step[0]), _f(step[1])]}


def _fit_svi_slice(prep, tau, k_domain, prior=None, floor=None):
    use = prep["use"]
    k, sig, lam = prep["k"][use], prep["iv"][use], prep["lam"][use]
    params, _ = svi.fit_zeliade(k, sig, lam, tau, prior=prior)
    check = svi.check_slice(params, k_domain)
    note = "zeliade"
    floor_ok = True
    if floor is not None:
        kk = np.linspace(k_domain[0], k_domain[1], 201)
        floor_ok = bool(np.all(svi.raw_w(kk, params) >= floor(kk)))
    if not check["butterfly_ok"] or not floor_ok:
        refit, success, message = svi.refit_constrained(params, k, sig, lam, tau, k_domain, floor=floor, prior=prior)
        recheck = svi.check_slice(refit, k_domain)
        if recheck["butterfly_ok"]:
            params, check, note = refit, recheck, "slsqp_constrained"
        else:
            note = f"constrained_refit_failed: {message}"
    return params, check, note


def commodity_surface(slices, *, valuation, clock, rate, futures, futures_expiry):
    """futures: underlying code -> close; futures_expiry: code -> last trading date."""
    tick = chain.infer_tick([o.close for s in slices for o in s.options] + [o.settlement for s in slices for o in s.options])
    step = clock.one_day_step()
    prepared, excluded = [], []
    for s in slices:
        tau, t_cal, td = clock.tau(s.expiry), clock.calendar_years(s.expiry), clock.trading_days(s.expiry)
        F = futures.get(s.underlying)
        if tau <= 0 or t_cal <= 0:
            continue
        if not F:
            excluded.append({"key": s.key, "reason": "no_underlying_close", "underlying": s.underlying})
            continue
        D = math.exp(-rate * t_cal)
        prep = _prepare(s, F, D, tau, True, rate, t_cal, tick)
        header = _slice_header(s, valuation, tau, t_cal, td, F, "underlying_future_close", D, tick, None)
        expiry_f = futures_expiry.get(s.underlying)
        header["future_expiry"] = expiry_f.isoformat() if expiry_f else None
        reason = "near_expiry" if td < MIN_TRADING_DAYS else "too_few_quotes" if int(prep["use"].sum()) < MIN_POINTS else None
        prepared.append({"slice": s, "prep": prep, "F": F, "tau": tau, "t_cal": t_cal, "header": header, "reason": reason,
                         "future_expiry": expiry_f})
    calib = [p for p in prepared if p["reason"] is None]
    if not calib:
        return {"status": "insufficient", "family": "commodity", "tick": tick, "excluded": excluded,
                "slices": [dict(p["header"], excluded=p["reason"]) for p in prepared]}
    k_all = np.concatenate([p["prep"]["k"][p["prep"]["use"]] for p in calib])
    k_domain = (float(k_all.min()) - 0.05, float(k_all.max()) + 0.05)
    groups = defaultdict(list)
    for p in calib:
        groups[p["slice"].underlying].append(p)

    def fit_group(members, priors):
        members.sort(key=lambda item: item["tau"])
        previous = None
        for p in members:
            prior = priors.get(p["slice"].key)
            floor = (lambda kk, prev=previous: svi.raw_w(kk, prev)) if previous is not None else None
            params, check, note = _fit_svi_slice(p["prep"], p["tau"], k_domain, prior=prior, floor=floor)
            p["params"], p["check"], p["note"] = params, check, note
            previous = params

    for members in groups.values():
        fit_group(members, {})
    theta_rows = [p for p in calib if p.get("future_expiry")]
    model = None
    if len(theta_rows) >= 3:
        t0_frac = (valuation - valuation.replace(month=1, day=1)).days / 365.0
        T_o = [max(p["t_cal"], 1e-6) for p in theta_rows]
        T_F = [max((p["future_expiry"] - valuation).days / 365.0, t + 1e-6) for p, t in zip(theta_rows, T_o)]
        theta = [max(float(svi.raw_w(0.0, p["params"])), 1e-10) for p in theta_rows]
        weights = [float(p["prep"]["use"].sum()) for p in theta_rows]
        model = commodity.fit_theta_model(T_o, T_F, theta, weights, t0_frac)
        if model:
            priors = {}
            for p, fitted in zip(theta_rows, model["fitted_theta"]):
                priors[p["slice"].key] = (fitted, 1.0 / PRIOR_ATM_WIDTH ** 2)
                p["theta_model"] = fitted
                p["theta_first_pass"] = float(svi.raw_w(0.0, p["params"]))
            for members in groups.values():
                fit_group(members, priors)
    group_checks = []
    kk = np.linspace(k_domain[0], k_domain[1], 401)
    for underlying, members in sorted(groups.items()):
        members.sort(key=lambda item: item["tau"])
        for a, b in zip(members[:-1], members[1:]):
            gap = svi.raw_w(kk, b["params"]) - svi.raw_w(kk, a["params"])
            group_checks.append({"underlying": underlying, "pair": [a["slice"].key, b["slice"].key],
                                 "min_gap": _f(float(gap.min())), "calendar_ok": bool(gap.min() >= -1e-10)})
    out_slices = []
    for p in sorted(prepared, key=lambda item: (item["slice"].underlying or "", item["tau"])):
        prep, tau = p["prep"], p["tau"]
        header = dict(p["header"])
        atm_skew = None
        if "params" in p:
            params = p["params"]
            model_iv = np.sqrt(np.maximum(svi.raw_w(prep["k"], params), 0.0) / tau)
            a, b, rho, m, sig = params
            w0, wp0, _ = svi.raw_derivs(np.array([0.0]), params)
            atm = math.sqrt(max(w0[0], 0.0) / tau)
            atm_skew = float(wp0[0] / (2 * math.sqrt(max(w0[0], 1e-14) * tau)))
            stats = essvi.delta_points(lambda x, params=params: svi.raw_w(x, params), tau, DELTA_LEVELS)
            header["params"] = {"a": _f(a), "b": _f(b), "rho": _f(rho), "m": _f(m), "sigma": _f(sig)}
            jw = svi.jump_wings(params, tau)
            header["jw"] = {key: _f(value) for key, value in jw.items()} if jw else None
            header["stats"] = {"atm_vol": _f(atm), "atm_skew": _f(atm_skew), **{key: _f(value) for key, value in stats.items()}}
            header["check"] = {key: (_f(v) if isinstance(v, float) else v) for key, v in p["check"].items()}
            header["fit_note"] = p["note"]
            if "theta_model" in p:
                header["theta_model"] = _f(p["theta_model"])
                header["theta_first_pass"] = _f(p["theta_first_pass"])
            header["fit"] = _fit_stats(prep, model_iv)
            header["curve"] = _curve(lambda x, params=params: svi.raw_w(x, params), tau, k_domain[0], k_domain[1])
        else:
            model_iv = np.full(len(prep["k"]), np.nan)
            header["excluded"] = p["reason"]
        header["options"] = _option_rows(p["slice"], prep, model_iv, p["F"], tau, p["t_cal"], rate, True, step, None, atm_skew)
        out_slices.append(header)
    model_out = None
    if model:
        model_out = {key: value for key, value in model.items() if key != "fitted_theta"}
        model_out["points"] = [{"key": p["slice"].key, "t_option": _f(p["t_cal"]), "t_future": _f((p["future_expiry"] - valuation).days / 365.0),
                                "theta": _f(p.get("theta_first_pass")), "theta_model": _f(p.get("theta_model"))} for p in theta_rows]
    return {"status": "ok", "family": "commodity", "model": "svi_per_slice", "tick": tick,
            "k_domain": [_f(k_domain[0]), _f(k_domain[1])], "theta_model": model_out, "group_calendar": group_checks,
            "slices": out_slices, "excluded": excluded, "theta_step": [_f(step[0]), _f(step[1])]}
