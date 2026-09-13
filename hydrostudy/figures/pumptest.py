"""Figures for aquifer-test analysis."""

from __future__ import annotations

import numpy as np

from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.figures.style import plt, save
from hydrostudy.units import MIN_PER_DAY


def _pumping_points(test: dict):
    t = np.array(test["series"]["elapsed_min"], dtype=float)
    s = np.array(test["series"]["drawdown_ft"], dtype=float)
    ph = test["series"].get("phase")
    if ph:
        m = np.array([str(x).lower() != "recovery" for x in ph])
        t, s = t[m], s[m]
    return t, s


def render_cooper_jacob(test: dict, path):
    fig, ax = plt.subplots(figsize=(7.0, 4.3))
    t, s = _pumping_points(test)
    ax.semilogx(t, s, "o", ms=3.5, color="#555", label="Measured drawdown")
    cj = test["cooper_jacob"]
    if cj and cj["t_ft2d"]:
        tu = np.array(cj["t_used_min"])
        ax.semilogx(tu, cj["s_used_ft"], "o", ms=4.5, mfc="none", mec="#d62728", label=f"Points used (u < 0.01, n = {cj['n_used']})")
        x = np.logspace(np.log10(max(tu.min() / 3, 0.5)), np.log10(t.max() * 1.5), 50)
        ax.semilogx(x, cj["slope_ft_per_cycle"] * np.log10(x / MIN_PER_DAY) + cj["intercept_ft"], "-", color="#d62728",
                    label=f"Cooper-Jacob line: {cj['slope_ft_per_cycle']:.2f} ft/log cycle, T = {cj['t_ft2d']:,.0f} ft2/day")
    ax.invert_yaxis()
    ax.set_xlabel("Elapsed time (min)")
    ax.set_ylabel("Drawdown (ft)")
    ax.grid(True, which="both", lw=0.4, alpha=0.5)
    ax.legend(fontsize=7.5, loc="lower left")
    ax.set_title(f"Test {test['id']}: {test['rate_gpm']:,.0f} gpm, semi-log time-drawdown", fontsize=9)
    return {"path": save(fig, path), "kind": "cj", "caption": f"Time-drawdown data and Cooper-Jacob straight-line fit, test {test['id']}"}


def render_theis_match(test: dict, path):
    tf = test["theis"]
    if not tf or not tf["t_ft2d"]:
        return None
    fig, ax = plt.subplots(figsize=(7.0, 4.3))
    t, s = _pumping_points(test)
    ax.loglog(t, s, "o", ms=3.5, color="#555", label="Measured drawdown")
    x = np.logspace(np.log10(t.min()), np.log10(t.max()), 100)
    ax.loglog(x, theis_drawdown(test["rate_gpm"], tf["t_ft2d"], tf["s"], test["r_w_ft"], x / MIN_PER_DAY), "-", color="#1f77b4",
              label=f"Theis fit: T = {tf['t_ft2d']:,.0f} ft2/day, S = {tf['s']:.2e}{' (fixed)' if tf['s_fixed'] else ''}")
    ax.set_xlabel("Elapsed time (min)")
    ax.set_ylabel("Drawdown (ft)")
    ax.grid(True, which="both", lw=0.4, alpha=0.5)
    ax.legend(fontsize=7.5)
    ax.set_title(f"Test {test['id']}: log-log Theis match", fontsize=9)
    return {"path": save(fig, path), "kind": "theis", "caption": f"Log-log time-drawdown data with fitted Theis curve, test {test['id']}"}


def render_recovery(test: dict, path):
    rf = test.get("recovery")
    if not rf or not rf.get("t_ft2d"):
        return None
    fig, ax = plt.subplots(figsize=(7.0, 4.3))
    x = np.array(rf["ratio_used"])
    y = np.array(rf["residual_used_ft"])
    ax.plot(x, y, "o", ms=3.5, color="#555", label="Residual drawdown")
    xs = np.linspace(x.min(), x.max(), 20)
    inter = float(np.mean(y - rf["slope_ft_per_cycle"] * x))
    ax.plot(xs, rf["slope_ft_per_cycle"] * xs + inter, "-", color="#d62728", label=f"Recovery line: T = {rf['t_ft2d']:,.0f} ft2/day")
    ax.invert_yaxis()
    ax.set_xlabel("log10(t / t')  [t = time since pumping began, t' = time since pumping stopped]")
    ax.set_ylabel("Residual drawdown (ft)")
    ax.grid(True, lw=0.4, alpha=0.5)
    ax.legend(fontsize=7.5)
    ax.set_title(f"Test {test['id']}: Theis recovery analysis", fontsize=9)
    return {"path": save(fig, path), "kind": "recovery", "caption": f"Residual-drawdown recovery analysis, test {test['id']}"}


def render_step_test(test: dict, path):
    sf = test.get("step")
    if not sf or sf["b_ft_per_gpm"] is None:
        return None
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.5, 3.8))
    t = np.array(test["series"]["elapsed_min"])
    s = np.array(test["series"]["drawdown_ft"])
    ax1.plot(t, s, "-", color="#555", lw=1)
    ax1.invert_yaxis()
    ax1.set_xlabel("Elapsed time (min)")
    ax1.set_ylabel("Drawdown (ft)")
    ax1.set_title("Step-drawdown record", fontsize=9)
    ax1.grid(True, lw=0.4, alpha=0.5)
    q = np.array([x["q_gpm"] for x in sf["steps"]])
    y = np.array([x["s_over_q"] for x in sf["steps"]])
    ax2.plot(q, y, "o", color="#555", label="s/Q at end of step")
    qs = np.linspace(0, q.max() * 1.1, 20)
    ax2.plot(qs, sf["b_ft_per_gpm"] + sf["c_ft_per_gpm2"] * qs, "-", color="#d62728",
             label=f"s/Q = B + CQ; B = {sf['b_ft_per_gpm']:.4f}, C = {sf['c_ft_per_gpm2']:.2e}")
    ax2.set_xlabel("Pumping rate Q (gpm)")
    ax2.set_ylabel("s/Q (ft per gpm)")
    ax2.set_title("Jacob step-drawdown analysis", fontsize=9)
    ax2.grid(True, lw=0.4, alpha=0.5)
    ax2.legend(fontsize=7)
    fig.tight_layout()
    return {"path": save(fig, path), "kind": "step", "caption": f"Step-drawdown test record and s/Q analysis, test {test['id']}"}
