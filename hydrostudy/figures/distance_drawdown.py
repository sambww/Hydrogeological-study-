"""Figure: distance-drawdown curves (semi-log) for the proposed-well scenarios."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.figures.style import save


def render(project, path):
    a = project.artifacts
    scen = [s for s in a["analysis"]["scenarios"] if s["group"] == "proposed_only"]
    if not scen:
        return None
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    r = np.logspace(-0.5, np.log10(6 * 5280), 400)
    for sc in scen:
        for aq, res in sc["results_by_aquifer"].items():
            p = res["pumped_wells"][0]
            rr = np.maximum(r, p["r_w_ft"])
            s = theis_drawdown(p["q_gpm"], res["t_ft2d"], res["s"], rr, sc["duration_days"])
            nm = next((w.label for w in project.intake.all_wells if w.id == p["id"]), p["id"])
            ax.plot(r, s, label=f"{nm}, {p['q_gpm']:,.0f} gpm, {sc['duration_label']} ({aq})")
    nearby = [n for n in a["nearby_wells"] if n["in_search_radius"]]
    for n in nearby:
        ax.axvline(n["distance_ft"], color="#999", lw=0.5, ls=":")
    ax.set_xscale("log")
    ax.set_xlabel("Distance from pumped well (ft)")
    ax.set_ylabel("Drawdown (ft)")
    ax.invert_yaxis()
    ax.grid(True, which="both", lw=0.4, alpha=0.5)
    ax.legend(fontsize=7)
    ax.set_title("Theis distance-drawdown curves (dotted lines: distances to registered wells)", fontsize=9)
    return {"path": save(fig, path), "kind": "distance_drawdown", "caption": "Distance-drawdown curves for the proposed well scenarios"}
