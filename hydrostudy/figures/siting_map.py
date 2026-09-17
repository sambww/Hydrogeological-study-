"""Figure: the siting envelope on the tract, coloured by the maximum rate each location supports."""

from __future__ import annotations

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.patches import Polygon as MplPolygon

from hydrostudy.figures.style import (
    COLORS,
    add_circle,
    add_north_arrow,
    add_scale_bar,
    draw_boundary,
    new_map,
    plot_wells,
    save,
    set_extent,
)

# The envelope edge must not share the property boundary's colour: they are different claims about the
# same picture, and the reader has to be able to tell which line is the tract and which is the rule.
ENVELOPE = "#b3001b"


def _tract_clip(ax, boundary):
    """A patch of the tract's outer ring, for clipping the rate field to the tract."""
    geom = max(boundary.geoms, key=lambda g: g.area) if boundary.geom_type == "MultiPolygon" else boundary
    patch = MplPolygon(list(geom.exterior.coords), closed=True, fc="none", ec="none")
    ax.add_patch(patch)
    return patch


def render(project, siting: dict, path):
    """Rate field, compliant envelope, and the spacing circles that bound it."""
    intake = project.intake
    boundary = project.boundary_geom
    f = siting["field"]
    xs, ys = np.array(f["x_ft"]), np.array(f["y_ft"])
    rate = np.array(f["max_rate_gpm"])
    target = siting["target_rate_gpm"]

    fig, ax = new_map()
    minx, miny, maxx, maxy = boundary.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = max(maxx - minx, maxy - miny) * 0.62
    set_extent(ax, cx, cy, half)

    clip = _tract_clip(ax, boundary)
    if xs.size >= 3 and np.ptp(rate) > 0:
        cs = ax.tricontourf(xs, ys, rate, levels=12, cmap="YlGnBu", alpha=0.85, zorder=2)
        cs.set_clip_path(clip)
        cb = fig.colorbar(cs, ax=ax, fraction=0.035, pad=0.02)
        cb.set_label("Maximum rate the location supports (gpm)", fontsize=7.5)
        cb.ax.tick_params(labelsize=7)
        if rate.min() < target < rate.max():
            line = ax.tricontour(xs, ys, rate, levels=[target], colors=[ENVELOPE], linewidths=2.2, zorder=7)
            line.set_clip_path(clip)
    else:
        ax.scatter(xs, ys, c=rate, cmap="YlGnBu", s=12, marker="s", zorder=2)

    # Every well that limits the envelope, drawn with the radius it claims at the target rate.
    for n in siting["counting_wells"]:
        src = next(w for w in project.artifacts["nearby_wells"] if w["map_id"] == n["map_id"])
        add_circle(ax, src["x_ft"], src["y_ft"], siting["required_spacing_ft"], fill=False, ls=":", lw=1.0,
                   ec=COLORS["spacing"], zorder=6)
    plot_wells(ax, project.artifacts["nearby_wells"])
    draw_boundary(ax, project, lw=1.8)

    xy = intake._local_xy
    for w in intake.all_wells:
        if w.id == siting["well_id"]:
            continue
        x, y = xy[w.id]
        ax.plot(x, y, "s", ms=6.5, color=COLORS["existing"], mec="k", mew=0.6, zorder=14)
    ix, iy = xy[siting["well_id"]]
    ax.plot(ix, iy, "x", ms=9, mew=2.0, color="#444444", zorder=15)

    for cand in siting["best"]:
        ax.plot(cand["x_ft"], cand["y_ft"], "o", ms=9 if cand["rank"] == 1 else 6,
                color=COLORS["proposed"], mec="k", mew=0.9, zorder=16)
        ax.annotate(str(cand["rank"]), (cand["x_ft"], cand["y_ft"]), xytext=(7, 6), textcoords="offset points",
                    fontsize=7.5, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="k", lw=0.5), zorder=17)

    handles = [
        Line2D([], [], marker="o", color=COLORS["proposed"], mec="k", ls="", ms=8, label="Ranked siting candidate"),
        Line2D([], [], marker="x", color="#444444", ls="", ms=8, mew=2, label="Location in the intake"),
        Line2D([], [], marker="s", color=COLORS["existing"], mec="k", ls="", ms=6.5, label="Other system well (fixed)"),
        Line2D([], [], marker="o", color=COLORS["nearby"], ls="", ms=5, label="District well (Map ID)"),
        Line2D([], [], color=COLORS["spacing"], ls=":", label=f"Spacing radius at {target:,.0f} gpm "
                                                              f"({siting['required_spacing_ft']:,.0f} ft)"),
        Patch(fc="none", ec=COLORS["boundary"], label="Property boundary"),
    ]
    if rate.size and rate.min() < target < rate.max():
        handles.append(Line2D([], [], color=ENVELOPE, lw=2.2, label=f"{target:,.0f}-gpm envelope edge"))
    # Below the axes: the ranked candidates cluster wherever interference is least, which is a corner, so
    # any in-axes corner is a corner the legend would hide.
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=3, fontsize=7,
              framealpha=1.0, borderaxespad=0.0)
    add_scale_bar(ax, half)
    add_north_arrow(ax)

    g = siting["grid"]
    qualifier = " (provisional multiplier)" if siting["provisional"] else ""
    setback = (f", inside a {siting['setback_ft']:,.0f}-ft property-line setback"
               if siting["setback_ft"] else "")
    return {"path": save(fig, path), "kind": "siting",
            "caption": f"Siting envelope for {siting['well_label']} in the {siting['aquifer']} at "
                       f"{target:,.0f} gpm{qualifier}: {g['compliant_area_acres']:,.1f} of "
                       f"{g['searched_area_acres']:,.1f} searched acres comply at "
                       f"{siting['ft_per_gpm']:g} ft/gpm, evaluated over {siting['duration_label']}. "
                       f"Shading covers only the points searched ({g['spacing_ft']:,.0f}-ft grid{setback})"}
