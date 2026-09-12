"""Figure: modeled drawdown contours for one scenario and aquifer."""

from __future__ import annotations

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from hydrostudy.analysis.theis import PumpingWell, drawdown_grid
from hydrostudy.figures.style import (
    COLORS,
    add_circle,
    add_north_arrow,
    add_scale_bar,
    draw_boundary,
    draw_hydrography,
    new_map,
    plot_wells,
    save,
    set_extent,
)


def render(project, scenario: dict, aquifer: str, path):
    a = project.artifacts
    geo = a["geo"]
    intake = project.intake
    res = scenario["results_by_aquifer"][aquifer]
    wells = [PumpingWell(w["id"], w["x_ft"], w["y_ft"], w["q_gpm"], w["r_w_ft"], aquifer) for w in res["wells_xy"]]
    T, S, t = res["t_ft2d"], res["s"], scenario["duration_days"]
    interval = intake.analysis.contour_interval_ft
    # extent: cover the half-mile circles, all system wells and the largest reported cone edge (capped)
    xs = [w.x_ft for w in wells] + [intake._local_xy[w.id][0] for w in intake.all_wells]
    ys = [w.y_ft for w in wells] + [intake._local_xy[w.id][1] for w in intake.all_wells]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    spread = max(max(xs) - min(xs), max(ys) - min(ys)) / 2
    edge_5 = next((e["max_ft"] for e in res["cone_edges"] if abs(e["threshold_ft"] - 5.0) < 1e-6), None)
    half = max(spread + geo["half_mile_ft"] * 1.25, 3200.0)
    if edge_5:
        half = max(half, min(edge_5 * 1.15, 4 * 5280))
    n = int(intake.analysis.grid_points)
    X, Y, Z = drawdown_grid(wells, T, S, t, half, n=n, center=(cx, cy))
    fig, ax = new_map()
    set_extent(ax, cx, cy, half)
    for w in intake.proposed_wells:
        x, y = intake._local_xy[w.id]
        add_circle(ax, x, y, geo["half_mile_ft"], fc=COLORS["half_mile"], ec="none", alpha=0.45, zorder=1)
    draw_hydrography(ax, project)
    draw_boundary(ax, project)
    zmax = float(np.nanmax(Z))
    levels = np.arange(interval, min(zmax, 400) + interval, interval)
    if len(levels) == 0:
        levels = np.array([interval])
    cs = ax.contour(X, Y, Z, levels=levels, colors=COLORS["contour"], linewidths=0.8, zorder=5)
    # label a subset so the map stays legible
    step = max(1, len(levels) // 8)
    ax.clabel(cs, levels=levels[::step], fmt=lambda v: f"{v:g}'", fontsize=6.5, inline=True)
    plot_wells(ax, a["nearby_wells"])
    names = {w.id: w.label for w in intake.all_wells}
    labels = {}
    for p in res["pumped_wells"]:
        labels[p["id"]] = f"{names.get(p['id'], p['id'])} ({p['total_ft']:.1f}')"
    for p in res["idle_wells"]:
        labels[p["id"]] = f"{names.get(p['id'], p['id'])} idle ({p['total_ft']:.1f}')"
    xy = intake._local_xy
    k = 0
    for w in intake.all_wells:
        x, y = xy[w.id]
        pumping = any(pw.id == w.id for pw in wells)
        if w in intake.proposed_wells:
            ax.plot(x, y, "o", ms=8, color=COLORS["proposed"], mec="k", mew=0.8, zorder=15)
        else:
            ax.plot(x, y, "s", ms=6.5, color=COLORS["existing"] if pumping else "#bbbbbb", mec="k", mew=0.6, zorder=14)
        if w.id in labels:
            ax.annotate(labels[w.id], (x, y), xytext=(14, 14 + 16 * k), textcoords="offset points", fontsize=7.5, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="k", lw=0.5),
                        arrowprops=dict(arrowstyle="-", lw=0.6), zorder=16)
            k += 1
    handles = [Line2D([], [], marker="o", color=COLORS["proposed"], mec="k", ls="", ms=8, label="Proposed well"),
               Line2D([], [], marker="s", color=COLORS["existing"], mec="k", ls="", ms=6.5, label="Existing system well"),
               Line2D([], [], marker="o", color=COLORS["nearby"], ls="", ms=5, label="Registered/permitted well (Map ID)"),
               Patch(fc=COLORS["half_mile"], alpha=0.45, label="1/2-mile radius"),
               Line2D([], [], color=COLORS["contour"], label=f"Drawdown contour ({interval:g}-ft interval)")]
    ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.95)
    add_scale_bar(ax, half)
    add_north_arrow(ax)
    who = "proposed " + names.get(scenario["focus_well"], scenario["focus_well"]) if scenario["focus_well"] else "all system wells"
    return {"path": save(fig, path), "kind": "drawdown", "scenario_key": scenario["key"], "aquifer": aquifer,
            "caption": f"Modeled drawdown in the {aquifer} Aquifer after {scenario['duration_label']} of pumping from {who}"}
