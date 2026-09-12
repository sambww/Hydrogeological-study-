"""Figure: regional location of the site (county outline when supplied)."""

from __future__ import annotations

from hydrostudy.figures.style import (
    COLORS,
    add_north_arrow,
    add_scale_bar,
    draw_shapely,
    new_map,
    plot_proposed,
    save,
    set_extent,
)
from hydrostudy.geo.geometry import geojson_to_local
from hydrostudy.geo.io import read_geojson
from hydrostudy.units import FT_PER_MILE


def render(project, path):
    fig, ax = new_map((7.0, 6.0))
    intake = project.intake
    cx, cy = intake._local_xy[intake.proposed_wells[0].id]
    half = 3 * FT_PER_MILE
    county = project.manifest.get("county")
    has_county = False
    if county is not None:
        for _props, geom in geojson_to_local(read_geojson(county.path), project.crs):
            draw_shapely(ax, geom, facecolor="#f3f3f3", edgecolor=COLORS["county"], lw=1.2, zorder=1)
            has_county = True
            b = geom.bounds
            half = max(abs(b[0] - cx), abs(b[2] - cx), abs(b[1] - cy), abs(b[3] - cy)) * 1.1
    set_extent(ax, cx, cy, half)
    _graticule(ax, project, cx, cy, half)
    if not has_county:
        from hydrostudy.figures.style import plot_wells
        plot_wells(ax, project.artifacts["nearby_wells"], label=False, only_in_map=False, fontsize=6)
    plot_proposed(ax, project, labels={w.id: f"{intake.applicant.system_name or 'Site'} - {w.label}" for w in intake.proposed_wells})
    ax.text(0.02, 0.98, f"{intake.district.county} County, Texas", transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(fc="white", ec="k", lw=0.5))
    if not has_county:
        fig.text(0.5, 0.005, "County boundary layer not supplied; graticule shown for reference (see location description in text).",
                 ha="center", fontsize=6.5, color="#666")
    add_scale_bar(ax, half)
    add_north_arrow(ax)
    ax.set_title(f"Location of the {intake.applicant.system_name or 'project'}", fontsize=10)
    return {"path": save(fig, path), "caption": f"Location map of the {intake.applicant.system_name or 'project site'}",
            "kind": "location", "has_county": has_county}


def _graticule(ax, project, cx, cy, half, step_deg=0.02):
    """Latitude/longitude grid lines with edge labels (local AEQD feet)."""
    import numpy as np
    crs = project.crs
    lon_min, lat_min = crs.to_wgs84(cx - half, cy - half)
    lon_max, lat_max = crs.to_wgs84(cx + half, cy + half)
    lons = np.arange(np.floor(lon_min / step_deg) * step_deg, lon_max + step_deg, step_deg)
    lats = np.arange(np.floor(lat_min / step_deg) * step_deg, lat_max + step_deg, step_deg)
    for lo in lons:
        ys = np.linspace(lat_min, lat_max, 50)
        x, y = crs.to_local(np.full_like(ys, lo), ys)
        ax.plot(x, y, color="#bbbbbb", lw=0.5, zorder=0)
        if cx - half < x[0] < cx + half:
            ax.text(x[0], cy - half + 0.02 * half, f"{abs(lo):.2f}°W", ha="center", va="bottom", fontsize=6, color="#666")
    for la in lats:
        xs = np.linspace(lon_min, lon_max, 50)
        x, y = crs.to_local(xs, np.full_like(xs, la))
        ax.plot(x, y, color="#bbbbbb", lw=0.5, zorder=0)
        if cy - half < y[0] < cy + half:
            ax.text(cx - half + 0.02 * half, y[0], f"{la:.2f}°N", ha="left", va="bottom", fontsize=6, color="#666")
