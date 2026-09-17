"""Figure: modeled drawdown contours for one scenario and aquifer."""

from __future__ import annotations

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from hydrostudy.analysis.boundaries import LineBoundary
from hydrostudy.analysis.solution import solution_from
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

# A barrier passes no water and a recharge boundary holds the head: opposite effects, so they must not
# look alike on a map someone reads quickly.
BOUNDARY_COLORS = {"barrier": "#8c2d04", "recharge": "#0b6fa4"}


def render(project, scenario: dict, aquifer: str, path):
    a = project.artifacts
    geo = a["geo"]
    intake = project.intake
    res = scenario["results_by_aquifer"][aquifer]
    wells = [PumpingWell(w["id"], w["x_ft"], w["y_ft"], w["q_gpm"], w["r_w_ft"], aquifer) for w in res["wells_xy"]]
    # The contoured field has to be the one the tables were computed from: the same solution, and the
    # image wells that any hydraulic boundary put into the superposition.
    field = wells + [PumpingWell(i["id"], i["x_ft"], i["y_ft"], i["q_gpm"], i["r_w_ft"], aquifer)
                     for i in res.get("image_wells", [])]
    fn = solution_from(res).drawdown
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
    X, Y, Z = drawdown_grid(field, T, S, t, half, n=n, center=(cx, cy), fn=fn)
    # Everything else refuses to report drawdown beyond a boundary; the contoured field must not imply
    # one either. Masking leaves the far side blank rather than contouring meaningless arithmetic.
    for b in a["geo"].get("hydraulic_boundaries", []):
        if b.get("aquifer") not in (None, "", aquifer):
            continue
        line = LineBoundary(b["kind"], b["x1"], b["y1"], b["x2"], b["y2"], b["name"], b.get("source"))
        here = line.signed_offset_ft(X, Y)
        inside = line.signed_offset_ft(cx, cy)
        Z = np.where((here > 0) == (inside > 0), Z, np.nan)
    fig, ax = new_map()
    set_extent(ax, cx, cy, half)
    for w in intake.proposed_wells:
        x, y = intake._local_xy[w.id]
        add_circle(ax, x, y, geo["half_mile_ft"], fc=COLORS["half_mile"], ec="none", alpha=0.45, zorder=1)
    draw_hydrography(ax, project)
    draw_boundary(ax, project)
    # A hydraulic boundary reshapes these contours; contours collapsing to zero along an invisible
    # line is the kind of figure that gets a report sent back.
    for b in a["geo"].get("hydraulic_boundaries", []):
        if b.get("aquifer") not in (None, "", aquifer):
            continue
        style = dict(color=BOUNDARY_COLORS[b["kind"]], lw=2.0, zorder=9,
                     ls="-" if b["kind"] == "recharge" else (0, (6, 3)))
        # Drawn well past the frame: the line is infinite in the solution, so it must not appear to stop.
        ux, uy = b["x2"] - b["x1"], b["y2"] - b["y1"]
        norm = (ux**2 + uy**2) ** 0.5
        ux, uy = ux / norm, uy / norm
        reach = half * 3
        mx, my = (b["x1"] + b["x2"]) / 2, (b["y1"] + b["y2"]) / 2
        ax.plot([mx - ux * reach, mx + ux * reach], [my - uy * reach, my + uy * reach], **style)
        # Label low on the frame, following the line. The middle holds the well callouts and the
        # deepest contours, and the top-right corner holds the legend.
        along = ((cy - half * 0.62) - my) / uy if abs(uy) > 1e-9 else 0.0
        lx, ly = mx + ux * along, my + uy * along
        if abs(lx - cx) > half:            # a near-horizontal boundary: label it at the frame edge
            along = ((cx - half * 0.45) - mx) / ux if abs(ux) > 1e-9 else 0.0
            lx, ly = mx + ux * along, my + uy * along
        ax.annotate(f"{b['name']} ({b['kind']})", (lx, ly), fontsize=6.5,
                    color=BOUNDARY_COLORS[b["kind"]], ha="center", va="bottom", zorder=10,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))
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
