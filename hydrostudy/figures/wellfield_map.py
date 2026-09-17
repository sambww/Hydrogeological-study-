"""Figure: the designed well field on the tract, each well labelled with its rate and drawdown."""

from __future__ import annotations

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

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


def render(project, field: dict, path):
    """Designed wells, the spacing radius each one claims, and the wells that bound them."""
    intake = project.intake
    boundary = project.boundary_geom
    rec = field["recommended"]

    fig, ax = new_map()
    minx, miny, maxx, maxy = boundary.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = max(maxx - minx, maxy - miny) * 0.72
    set_extent(ax, cx, cy, half)
    draw_boundary(ax, project, lw=1.8)

    # Each designed well's own spacing radius: multiplier x its rate, which is the distance the District
    # rule asks of it, rather than one radius for the whole field.
    for w in rec["wells"]:
        add_circle(ax, w["x_ft"], w["y_ft"], w["required_spacing_ft"], fill=False, ls=":", lw=1.1,
                   ec=COLORS["spacing"], zorder=6)
    plot_wells(ax, project.artifacts["nearby_wells"])

    xy = intake._local_xy
    for w in intake.existing_wells:
        if not w.include_in_system:
            continue
        x, y = xy[w.id]
        ax.plot(x, y, "s", ms=6.5, color=COLORS["existing"], mec="k", mew=0.6, zorder=14)

    # Marker area scales with rate, so the layout reads at a glance.
    rates = [w["rate_gpm"] for w in rec["wells"]] or [1.0]
    for w in rec["wells"]:
        ms = 7.0 + 7.0 * (w["rate_gpm"] / max(rates))
        ax.plot(w["x_ft"], w["y_ft"], "o", ms=ms, color=COLORS["proposed"], mec="k", mew=1.0, zorder=16)
        ax.annotate(f"#{w['slot']}  {w['rate_gpm']:,.0f} gpm\n{w['drawdown_ft']:,.0f} ft drawdown",
                    (w["x_ft"], w["y_ft"]), xytext=(9, 7), textcoords="offset points", fontsize=7,
                    fontweight="bold", zorder=17,
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="k", lw=0.5, alpha=0.95))

    handles = [
        Line2D([], [], marker="o", color=COLORS["proposed"], mec="k", ls="", ms=9, label="Designed well (area = rate)"),
        Line2D([], [], marker="s", color=COLORS["existing"], mec="k", ls="", ms=6.5, label="Existing system well"),
        Line2D([], [], marker="o", color=COLORS["nearby"], ls="", ms=5, label="District well (Map ID)"),
        Line2D([], [], color=COLORS["spacing"], ls=":", label=f"Spacing radius at each well's rate ({field['ft_per_gpm']:g} ft/gpm)"),
        Patch(fc="none", ec=COLORS["boundary"], label="Property boundary"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, fontsize=7,
              framealpha=1.0, borderaxespad=0.0)
    add_scale_bar(ax, half)
    add_north_arrow(ax)

    qualifier = " (provisional multiplier)" if field["provisional"] else ""
    met = ("meets the" if rec["meets_target"] else
           f"falls {rec['shortfall_gpm']:,.0f} gpm short of the")
    return {"path": save(fig, path), "kind": "wellfield",
            "caption": f"Designed well field in the {field['aquifer']}{qualifier}: "
                       f"{rec['wells_drilled']} well(s) totalling {rec['total_rate_gpm']:,.0f} gpm, which "
                       f"{met} {field['target_rate_gpm']:,.0f}-gpm demand, evaluated over "
                       f"{rec['duration_days']:,.1f} days. Deepest drawdown "
                       f"{rec['max_well_drawdown_ft']:,.0f} ft at a well; layout from a search on a "
                       f"{field['grid']['spacing_ft']:,.0f}-ft grid, not a proof of optimality"}
