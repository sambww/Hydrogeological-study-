"""Figure: property map (parcels when supplied) with the spacing radius."""

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
    draw_shapely,
    new_map,
    plot_proposed,
    plot_wells,
    save,
    set_extent,
)
from hydrostudy.geo.geometry import geojson_to_local
from hydrostudy.geo.io import read_geojson


def render(project, path):
    a = project.artifacts
    geo = a["geo"]
    intake = project.intake
    fig, ax = new_map()
    cx, cy = intake._local_xy[intake.proposed_wells[0].id]
    half = max(geo["spacing_radius_ft"] * 1.6, 800)
    set_extent(ax, cx, cy, half)
    parcels = project.manifest.get("parcels")
    has_parcels = False
    if parcels is not None:
        for _props, geom in geojson_to_local(read_geojson(parcels.path), project.crs):
            draw_shapely(ax, geom, facecolor="none", edgecolor=COLORS["parcel"], lw=0.7, zorder=4)
            has_parcels = True
    draw_hydrography(ax, project)
    draw_boundary(ax, project, lw=2.0)
    for w in intake.proposed_wells:
        x, y = intake._local_xy[w.id]
        if geo["spacing_radius_ft"] > 0:
            add_circle(ax, x, y, geo["spacing_radius_ft"], fill=False, ls="--", lw=1.5, ec="k", zorder=6)
            ax.annotate(f"{geo['spacing_radius_ft']:,.0f}-ft spacing radius", (x, y + geo["spacing_radius_ft"]),
                        xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7.5,
                        bbox=dict(fc="white", ec="k", lw=0.4), zorder=16)
    plot_wells(ax, a["nearby_wells"], only_in_map=False)
    labels = {w.id: f"Prop. {w.label} ({w.aquifer} Aquifer)" for w in intake.proposed_wells}
    plot_proposed(ax, project, labels=labels)
    handles = [Line2D([], [], marker="o", color=COLORS["proposed"], mec="k", ls="", ms=8, label="Proposed well"),
               Line2D([], [], marker="s", color=COLORS["existing"], mec="k", ls="", ms=6.5, label="Existing system well"),
               Line2D([], [], marker="o", color=COLORS["nearby"], ls="", ms=5, label="Registered/permitted well (Map ID)"),
               Line2D([], [], color="k", ls="--", label="Well spacing radius")]
    if has_parcels:
        handles.append(Patch(fc="none", ec=COLORS["parcel"], label="Parcel boundary"))
    if getattr(project, "boundary_geom", None) is not None:
        handles.append(Patch(fc="none", ec=COLORS["boundary"], label="Property boundary"))
    ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.95)
    if not has_parcels and getattr(project, "boundary_geom", None) is None:
        ax.text(0.5, 0.03, "Parcel/property boundary layer not supplied; nearest boundary distance taken from the intake.",
                transform=ax.transAxes, ha="center", fontsize=7, color="#666")
    add_scale_bar(ax, half)
    add_north_arrow(ax)
    return {"path": save(fig, path), "kind": "property", "has_parcels": has_parcels,
            "caption": "Property map of the proposed well(s) showing the required well spacing radius"}
