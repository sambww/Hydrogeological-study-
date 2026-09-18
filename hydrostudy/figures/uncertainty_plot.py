"""Figure: drawdown as an interval per receptor, and the exceedance curve at the worst-affected well.

Two panels, because they answer two different questions.

The left panel is the whole picture at once: one row per receptor, the p10-to-p90 interval as a bar, the
median as a line and the value the report currently states as a separate marker. A reader sees both how
uncertain each number is and whether the reported figure sits in the middle of that range or at one end.

The right panel is the one that settles arguments. It reads straight off the axis as "the probability
that drawdown at this well exceeds X feet", which is the form a District hearing or a neighbour's
complaint actually takes.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullFormatter, NullLocator, ScalarFormatter

from hydrostudy.analysis.uncertainty import quantile_keys
from hydrostudy.figures.style import save

#: The reported value, the interval, and the exceedance curves are three different claims; they get
#: three visually distinct treatments rather than three similar blues.
INTERVAL = "#2c5aa0"
REPORTED = "#b3001b"
MEDIAN = "#0b2d52"


def render(project, unc: dict, samples, path):
    """`samples` is the per-receptor array of draws, which is too large to keep in the JSON."""
    receptors = unc["receptors"]
    # Whatever quantiles were asked for, not the defaults: hard-coding them crashed the run *after* the
    # analysis had succeeded, which is the worst place to lose it.
    lo_k, mid_k, hi_k = quantile_keys(unc["quantiles"])
    lo_pct, mid_pct, hi_pct = (f"p{float(k) * 100:g}" for k in (lo_k, mid_k, hi_k))
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.0, max(3.2, 0.42 * len(receptors) + 1.6)),
                                 gridspec_kw={"width_ratios": [1.15, 1.0]})

    # ---- left: an interval per receptor ----------------------------------------------------------
    order = list(range(len(receptors)))[::-1]          # first receptor at the top
    for row, i in enumerate(order):
        r = receptors[i]
        q = r["quantiles"]
        lo, mid, hi = q[lo_k]["ft"], q[mid_k]["ft"], q[hi_k]["ft"]
        ax.plot([lo, hi], [row, row], color=INTERVAL, lw=6, solid_capstyle="butt", alpha=0.35,
                zorder=2)
        ax.plot([mid, mid], [row - 0.28, row + 0.28], color=MEDIAN, lw=2.2, zorder=4)
        if r.get("deterministic_ft") is not None:
            ax.plot([r["deterministic_ft"]], [row], marker="D", ms=5.5, color=REPORTED, mec="white",
                    mew=0.7, zorder=5)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([receptors[i]["label"] for i in order], fontsize=7.5)
    # Log scale: a pumped well draws several times what a registered well does, and on a linear axis the
    # pumped wells push every other row into an unreadable cluster. It also makes the bars comparable -
    # equal visual width is equal *proportional* uncertainty, which is what a lognormal spread produces.
    ax.set_xscale("log")
    ax.set_xlabel("Drawdown (ft), log scale", fontsize=8)
    # A decade-tick log axis can leave a single label on a range like 30-180 ft, which makes the panel
    # unreadable as numbers. Label a 1-2-3-5 ladder across whatever range the data actually spans.
    lo = min(r["quantiles"][lo_k]["ft"] for r in receptors)
    hi = max(max(r["quantiles"][hi_k]["ft"], r.get("deterministic_ft") or 0.0) for r in receptors)
    ladder = [v * 10**e for e in range(-2, 5) for v in (1, 1.5, 2, 3, 5, 7)]
    ticks = [v for v in ladder if lo * 0.92 <= v <= hi * 1.08]
    if len(ticks) >= 3:
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.tick_params(axis="x", labelsize=7.5)
    ax.grid(axis="x", lw=0.4, alpha=0.5)
    ax.set_axisbelow(True)
    ax.set_title(f"{lo_pct} to {hi_pct} across {unc['draws']:,} parameter draws", fontsize=8.5)

    # ---- right: exceedance at the most exposed registered well -----------------------------------
    pick = max(range(len(receptors)),
               key=lambda i: (receptors[i]["kind"] == "registered",
                              receptors[i]["quantiles"][hi_k]["ft"]))
    draws = np.sort(np.asarray(samples[pick], dtype=float))
    exceed = 1.0 - np.arange(1, draws.size + 1) / draws.size
    bx.plot(draws, exceed * 100.0, color=INTERVAL, lw=2.0, zorder=3)
    focus = receptors[pick]
    if focus.get("deterministic_ft") is not None:
        d = focus["deterministic_ft"]
        pct = 100.0 * (1.0 - (focus["deterministic_percentile"] or 0.0))
        bx.plot([d], [pct], marker="D", ms=6, color=REPORTED, mec="white", mew=0.8, zorder=5)
        bx.annotate(f"reported {d:,.0f} ft\n({pct:.0f}% chance of more)", (d, pct),
                    xytext=(8, 10), textcoords="offset points", fontsize=7, color=REPORTED,
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=REPORTED, lw=0.6, alpha=0.95))
    for th, prob in (focus.get("exceedance") or {}).items():
        bx.plot([float(th)], [prob * 100.0], marker="o", ms=5, color=MEDIAN, zorder=4)
        bx.annotate(f"{prob:.0%} above {float(th):,.0f} ft", (float(th), prob * 100.0),
                    xytext=(6, -12), textcoords="offset points", fontsize=7, color=MEDIAN)
    bx.set_xlabel("Drawdown (ft)", fontsize=8)
    bx.set_ylabel("Probability of exceeding (%)", fontsize=8)
    bx.set_ylim(0, 100)
    bx.tick_params(labelsize=7.5)
    bx.grid(lw=0.4, alpha=0.5)
    bx.set_axisbelow(True)
    bx.set_title(f"Exceedance at {focus['label']}", fontsize=8.5)

    fig.legend(handles=[
        Line2D([], [], color=INTERVAL, lw=6, alpha=0.35, label=f"{lo_pct} to {hi_pct}"),
        Line2D([], [], color=MEDIAN, lw=2.2, label=f"{mid_pct} of the draws"),
        Line2D([], [], color=REPORTED, marker="D", ls="", ms=6, label="value the report states"),
    ], loc="lower center", ncol=3, fontsize=7.5, frameon=True, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.06, 1, 1))

    p = unc["parameters"]
    spreads = []
    # The DECLARED spread, not this sample's quantiles: the caption is quoting the input.
    if p["t_ft2d"]["declared"]:
        spreads.append(f"T from {p['t_ft2d']['declared_p10']:,.0f} to "
                       f"{p['t_ft2d']['declared_p90']:,.0f} ft2/day")
    if p["s"]["declared"]:
        spreads.append(f"S from {p['s']['declared_p10']:.2e} to {p['s']['declared_p90']:.2e}")
    return {"path": save(fig, path), "kind": "uncertainty",
            "caption": f"Drawdown for {unc['scenario_title']} with the declared parameter spreads "
                       f"({'; '.join(spreads) or 'none declared'}, declared p10 to p90) propagated through "
                       f"{unc['draws']:,} draws, seed {unc['seed']}. The diamond is the value the report "
                       f"states; where it sits away from the median, the intake's parameter is one end of "
                       f"the declared spread rather than its centre. This propagates the declared "
                       f"parameter spreads only, and says nothing about whether the "
                       f"{unc['solution']['citation'].split('(')[0].strip()} assumptions hold."}
