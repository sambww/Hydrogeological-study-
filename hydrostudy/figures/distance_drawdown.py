"""Figure: distance-drawdown curves (semi-log) for the proposed-well scenarios."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from hydrostudy.analysis.solution import solution_from
from hydrostudy.figures.style import save


def render(project, path):
    a = project.artifacts
    scen = [s for s in a["analysis"]["scenarios"] if s["group"] == "proposed_only"]
    if not scen:
        return None
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    r = np.logspace(-0.5, np.log10(6 * 5280), 400)
    # A curve drawn with a different solution from the tables beside it is worse than no curve, so the
    # solution comes from the scenario result rather than being assumed here.
    solutions = set()
    for sc in scen:
        for aq, res in sc["results_by_aquifer"].items():
            p = res["pumped_wells"][0]
            rr = np.maximum(r, p["r_w_ft"])
            sol = solution_from(res)
            solutions.add(sol.citation)
            s = sol.drawdown(p["q_gpm"], res["t_ft2d"], res["s"], rr, sc["duration_days"])
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
    named = " / ".join(sorted(solutions)) if solutions else "Theis (1935) nonequilibrium solution"
    ax.set_title(f"Distance-drawdown curves, {named} (dotted lines: distances to registered wells)", fontsize=9)
    # A radial curve cannot represent a boundary: with an image well in the superposition, drawdown at a
    # given distance depends on direction. Say so rather than let the curve imply otherwise.
    bounded = bool(a["geo"].get("hydraulic_boundaries"))
    caveat = (" A hydraulic boundary is in effect, so drawdown at a given distance depends on direction; "
              "these radial curves omit the boundary and the contour maps and tables are the reference."
              if bounded else "")
    return {"path": save(fig, path), "kind": "distance_drawdown", "solution": named,
            "caption": f"Distance-drawdown curves for the proposed well scenarios, {named}. "
                       "The curves are for the pumped well alone and exclude interference from other "
                       f"system wells, which the scenario tables include.{caveat}"}
