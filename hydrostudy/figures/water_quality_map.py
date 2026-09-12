"""Figure: reported concentrations of one constituent at sampled wells near the site."""

from __future__ import annotations

from matplotlib.lines import Line2D

from hydrostudy.figures.style import (
    COLORS,
    add_circle,
    add_north_arrow,
    add_scale_bar,
    new_map,
    plot_proposed,
    save,
    set_extent,
)


def render(project, constituent: str, path):
    a = project.artifacts
    wq = a["water_quality"]
    recs = [w for w in wq["wells"] if constituent in w["values"] and w["lat"] is not None and w["lon"] is not None]
    if not recs:
        return None
    spec = wq["limits"].get(constituent, {})
    label = spec.get("label", constituent)
    units = spec.get("units", "")
    geo = a["geo"]
    intake = project.intake
    fig, ax = new_map()
    cx, cy = intake._local_xy[intake.proposed_wells[0].id]
    pts = [project.crs.to_local(w["lon"], w["lat"]) for w in recs]
    half = max(geo["map_radius_ft"] * 1.05, *[max(abs(x - cx), abs(y - cy)) * 1.15 for x, y in pts])
    set_extent(ax, cx, cy, half)
    add_circle(ax, cx, cy, geo["half_mile_ft"], fill=False, ls="--", lw=1.2, ec="k", zorder=6)
    limit = spec.get("mcl") or spec.get("scl")
    for w, (x, y) in zip(recs, pts, strict=True):
        v = w["values"][constituent]
        val = v["value"]
        if v["nd"] or val is None:
            col, txt = "#2ca02c", "ND"
        elif limit is not None and val > limit:
            col, txt = "#d62728", f"{val:g}"
        elif limit is not None and val > 0.5 * limit:
            col, txt = "#e6b800", f"{val:g}"
        else:
            col, txt = "#2ca02c", f"{val:g}"
        ax.plot(x, y, "o", ms=7, color=col, mec="k", mew=0.5, zorder=12)
        depth = f"{w['depth_ft']:,.0f}" if w.get("depth_ft") else "?"
        ax.annotate(f"{txt} {units}\n({depth} ft)", (x, y), xytext=(8, -22), textcoords="offset points", fontsize=6.5, zorder=13,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))
    plot_proposed(ax, project)
    handles = [Line2D([], [], marker="o", color=COLORS["proposed"], mec="k", ls="", ms=8, label="Proposed well")]
    if limit is not None:
        handles += [Line2D([], [], marker="o", color="#2ca02c", ls="", ms=7, label=f"< half of limit ({limit:g} {units})"),
                    Line2D([], [], marker="o", color="#e6b800", ls="", ms=7, label="between half of limit and limit"),
                    Line2D([], [], marker="o", color="#d62728", ls="", ms=7, label="exceeds limit")]
    handles.append(Line2D([], [], color="k", ls="--", label="1/2-mile radius"))
    ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.95, title=f"{label} (well depth)", title_fontsize=7)
    add_scale_bar(ax, half)
    add_north_arrow(ax)
    return {"path": save(fig, path), "kind": "wq", "constituent": constituent,
            "caption": f"Reported {label if label.isupper() else label[0].lower() + label[1:]} concentrations at sampled wells in the vicinity of the proposed well"}
