"""Shared map styling for matplotlib figures (no basemap tiles required)."""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.patches import Polygon as MplPolygon

COLORS = {
    "proposed": "#0aa3d6", "existing": "#1f77b4", "nearby": "#7b2d8e", "system": "#1f4e79",
    "half_mile": "#ffe867", "spacing": "#333333", "contour": "#2c5aa0", "stream": "#5aa9e6",
    "pond": "#a9d4f5", "parcel": "#c9a800", "boundary": "#e6007e", "county": "#555555",
}
DPI = 200


def new_map(figsize=(7.5, 6.5)):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(1.2)
    return fig, ax


def set_extent(ax, cx, cy, half_extent_ft):
    ax.set_xlim(cx - half_extent_ft, cx + half_extent_ft)
    ax.set_ylim(cy - half_extent_ft, cy + half_extent_ft)


def _nice_length(half_extent_ft):
    target = half_extent_ft * 0.5
    for L in (100, 200, 250, 400, 500, 1000, 1200, 2000, 2640, 5280, 10560, 26400, 52800):
        if L >= target:
            return L
    return 52800


def add_scale_bar(ax, half_extent_ft, units="feet"):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    L = _nice_length(half_extent_ft)
    if L >= 5280:
        label = f"{L/5280:g} mi" if L % 5280 == 0 else f"{L/5280:.1f} mi"
    else:
        label = f"{L:,} ft"
    bx = x0 + 0.05 * (x1 - x0)
    by = y0 + 0.05 * (y1 - y0)
    ax.plot([bx, bx + L], [by, by], color="k", lw=3, solid_capstyle="butt", zorder=20)
    ax.plot([bx, bx + L / 2], [by, by], color="w", lw=1.4, solid_capstyle="butt", zorder=21)
    ax.text(bx, by + 0.012 * (y1 - y0), "0", ha="center", va="bottom", fontsize=7, zorder=22)
    ax.text(bx + L, by + 0.012 * (y1 - y0), label, ha="center", va="bottom", fontsize=7, zorder=22)


def add_north_arrow(ax):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x = x1 - 0.06 * (x1 - x0)
    y = y0 + 0.05 * (y1 - y0)
    ax.annotate("N", xy=(x, y + 0.08 * (y1 - y0)), xytext=(x, y), ha="center", va="center", fontsize=9,
                fontweight="bold", arrowprops=dict(arrowstyle="-|>", color="k", lw=1.5), zorder=22)


def add_circle(ax, cx, cy, r_ft, **kw):
    c = Circle((cx, cy), r_ft, **kw)
    ax.add_patch(c)
    return c


def draw_shapely(ax, geom, **kw):
    gt = geom.geom_type
    if gt == "Polygon":
        ax.add_patch(MplPolygon(list(geom.exterior.coords), closed=True, **kw))
    elif gt == "MultiPolygon":
        for g in geom.geoms:
            draw_shapely(ax, g, **kw)
    elif gt in ("LineString", "LinearRing"):
        xs, ys = zip(*geom.coords, strict=True)
        ax.plot(xs, ys, **{k: v for k, v in kw.items() if k not in ("facecolor", "fill")})
    elif gt == "MultiLineString":
        for g in geom.geoms:
            draw_shapely(ax, g, **kw)
    elif gt == "Point":
        ax.plot(geom.x, geom.y, "o", **{k: v for k, v in kw.items() if k in ("color", "ms", "zorder")})


def plot_wells(ax, nearby, label=True, only_in_map=True, fontsize=6.5):
    for n in nearby:
        if only_in_map and not n.get("in_map_radius", True):
            continue
        col = COLORS["system"] if n.get("is_system_well") else COLORS["nearby"]
        ax.plot(n["x_ft"], n["y_ft"], "o", ms=4.5, color=col, mec="white", mew=0.5, zorder=12)
        if label:
            ax.annotate(str(n["map_id"]), (n["x_ft"], n["y_ft"]), xytext=(3, 3), textcoords="offset points",
                        fontsize=fontsize, zorder=13)


def plot_proposed(ax, project, labels=None):
    xy = project.intake._local_xy
    for w in project.intake.proposed_wells:
        x, y = xy[w.id]
        ax.plot(x, y, "o", ms=8, color=COLORS["proposed"], mec="k", mew=0.8, zorder=15)
        txt = labels.get(w.id, f"Prop. {w.label}") if labels else f"Prop. {w.label}"
        ax.annotate(txt, (x, y), xytext=(8, 8), textcoords="offset points", fontsize=7.5, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="k", lw=0.5), zorder=16)
    for w in project.intake.existing_wells:
        x, y = xy[w.id]
        ax.plot(x, y, "s", ms=6.5, color=COLORS["existing"], mec="k", mew=0.6, zorder=14)


def draw_hydrography(ax, project):
    for _name, geom in project.artifacts.get("_hydro_geoms", []):
        col = COLORS["pond"] if geom.geom_type in ("Polygon", "MultiPolygon") else COLORS["stream"]
        draw_shapely(ax, geom, color=col, facecolor=col, lw=1.0, zorder=3, alpha=0.9)


def draw_boundary(ax, project, lw=1.5):
    b = getattr(project, "boundary_geom", None)
    if b is not None:
        draw_shapely(ax, b, facecolor="none", edgecolor=COLORS["boundary"], lw=lw, zorder=8)


def save(fig, path, dpi=DPI):
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def miles_label(ft):
    return f"{ft/5280:.1f} mi" if ft >= 2640 else f"{ft:,.0f} ft"


def deg_to_str(v, kind):
    from hydrostudy.geo.crs import format_dms
    return format_dms(v, kind)


def nice_half_extent(values_ft, minimum):
    return max(minimum, *values_ft) if values_ft else minimum


def log_floor(x):
    return 10 ** math.floor(math.log10(x))
