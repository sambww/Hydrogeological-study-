"""Figure: registered/permitted wells and surface water within the map radius."""

from __future__ import annotations

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from hydrostudy.figures.style import (
    COLORS,
    add_circle,
    add_north_arrow,
    add_scale_bar,
    draw_boundary,
    draw_hydrography,
    new_map,
    plot_proposed,
    plot_wells,
    save,
    set_extent,
)


def render(project, path):
    a = project.artifacts
    geo = a["geo"]
    intake = project.intake
    fig, ax = new_map()
    cx, cy = intake._local_xy[intake.proposed_wells[0].id]
    half = geo["map_radius_ft"] * 1.05
    set_extent(ax, cx, cy, half)
    draw_hydrography(ax, project)
    draw_boundary(ax, project)
    for w in intake.proposed_wells:
        x, y = intake._local_xy[w.id]
        add_circle(ax, x, y, geo["half_mile_ft"], fill=False, ls="--", lw=1.4, ec="k", zorder=6)
        if geo["spacing_radius_ft"] > 0:
            add_circle(ax, x, y, geo["spacing_radius_ft"], fill=False, ls=":", lw=1.2, ec=COLORS["spacing"], zorder=6)
    plot_wells(ax, a["nearby_wells"])
    plot_proposed(ax, project)
    handles = [
        Line2D([], [], marker="o", color=COLORS["proposed"], mec="k", ls="", ms=8, label="Proposed well"),
        Line2D([], [], marker="s", color=COLORS["existing"], mec="k", ls="", ms=6.5, label="Existing system well"),
        Line2D([], [], marker="o", color=COLORS["nearby"], ls="", ms=5, label="District registered/permitted well (Map ID)"),
        Line2D([], [], color="k", ls="--", label="1/2-mile radius"),
    ]
    if geo["spacing_radius_ft"] > 0:
        handles.append(Line2D([], [], color=COLORS["spacing"], ls=":", label=f"Required spacing radius ({geo['spacing_radius_ft']:,.0f} ft)"))
    if a.get("_hydro_geoms"):
        handles.append(Line2D([], [], color=COLORS["stream"], label="Stream / pond"))
    if getattr(project, "boundary_geom", None) is not None:
        handles.append(Patch(fc="none", ec=COLORS["boundary"], label="Property boundary"))
    ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.95)
    add_scale_bar(ax, half)
    add_north_arrow(ax)
    n_in = sum(1 for n in a["nearby_wells"] if n["in_search_radius"])
    return {"path": save(fig, path), "kind": "wells",
            "caption": f"Registered and permitted wells and surface water within {geo['map_radius_ft']/5280:g} mile of the proposed well "
                       f"({n_in} wells within the {geo['search_radius_ft']:,.0f}-ft search radius)"}
