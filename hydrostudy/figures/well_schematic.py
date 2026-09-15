"""Figure: proposed well construction profile with anticipated lithology (not to scale horizontally)."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from hydrostudy.figures.style import save


def render(project, well, path):
    td = well.total_depth_ft
    fig = plt.figure(figsize=(7.0, 8.5))
    ax = fig.add_axes([0.30, 0.06, 0.40, 0.88])
    axl = fig.add_axes([0.04, 0.06, 0.20, 0.88], sharey=ax)
    top_pad = min(-0.03 * td, -20)
    ax.set_ylim(td * 1.04, top_pad)
    ax.set_xlim(-1.0, 1.0)
    for a in (ax, axl):
        a.set_xticks([])
        for s in a.spines.values():
            s.set_visible(False)
    axl.set_yticks([])
    ax.set_yticks([])
    # ground surface
    ax.plot([-1, 1], [0, 0], color="k", lw=1.5)
    ax.text(1.02, 0, f"0' datum: ~{well.elevation_ft_msl:,.0f} ft MSL" if well.elevation_ft_msl is not None else "0' ground surface",
            va="center", fontsize=7.5)
    max_dia = max([b.diameter_in for b in well.borehole] + [c.diameter_in for c in well.casing] + [s.diameter_in for s in well.screen] + [1.0])

    def hw(d_in):  # half width in axis units (exaggerated)
        return 0.45 * d_in / max_dia

    right_labels = []  # (y, text)

    # borehole with cement (annulus hatched)
    for b in well.borehole:
        w = hw(b.diameter_in)
        ax.add_patch(Rectangle((-w, b.top_ft), 2 * w, b.bottom_ft - b.top_ft, fc="#e8e8e8", ec="k", lw=0.8, hatch="////", zorder=1))
        right_labels.append(((b.top_ft + b.bottom_ft) / 2, f"{_frac(b.diameter_in)}\" dia. borehole ({b.top_ft:,.0f}' - {b.bottom_ft:,.0f}')"))
    for c in well.cement:
        # cement fills annulus between casing and borehole
        cas = well.casing[0] if well.casing else None
        bore = next((b for b in well.borehole if b.top_ft <= c.top_ft < b.bottom_ft), None)
        if cas and bore:
            wi, wo = hw(cas.diameter_in), hw(bore.diameter_in)
            for sgn in (-1, 1):
                ax.add_patch(Rectangle((min(sgn * wi, sgn * wo), c.top_ft), abs(wo - wi), c.bottom_ft - c.top_ft,
                                       fc="#b9b9b9", ec="none", hatch="...", zorder=2))
        right_labels.append((c.top_ft + 0.55 * (c.bottom_ft - c.top_ft), f"{c.method.capitalize()} ({c.top_ft:,.0f}' - {c.bottom_ft:,.0f}')"))
    for c in well.casing:
        w = hw(c.diameter_in)
        ax.add_patch(Rectangle((-w, c.top_ft), 2 * w, c.bottom_ft - c.top_ft, fc="white", ec="k", lw=1.6, zorder=3))
        wall = f" x {c.wall_in}\"" if c.wall_in else ""
        right_labels.append((c.top_ft + 0.3 * (c.bottom_ft - c.top_ft), f"{_frac(c.diameter_in)}\"{wall} {c.material} casing ({c.top_ft:+,.0f}' - {c.bottom_ft:,.0f}')"))
    for bl in getattr(well, "blank_liner", []) or []:
        w = hw(bl.diameter_in)
        ax.add_patch(Rectangle((-w, bl.top_ft), 2 * w, bl.bottom_ft - bl.top_ft, fc="#dddddd", ec="k", lw=1.2, zorder=4))
        right_labels.append(((bl.top_ft + bl.bottom_ft) / 2, f"{_frac(bl.diameter_in)}\" {bl.material} blank liner ({bl.top_ft:,.0f}' - {bl.bottom_ft:,.0f}')"))
    for s in well.screen:
        w = hw(s.diameter_in)
        ax.add_patch(Rectangle((-w, s.top_ft), 2 * w, s.bottom_ft - s.top_ft, fc="white", ec="k", lw=1.2, hatch="---", zorder=4))
        slot = f", {s.slot_in}\" slot" if s.slot_in else ""
        right_labels.append(((s.top_ft + s.bottom_ft) / 2, f"{_frac(s.diameter_in)}\" {s.material} screen{slot} ({s.top_ft:,.0f}' - {s.bottom_ft:,.0f}')"))
    for fp in well.filter_pack:
        bore = next((b for b in well.borehole if b.top_ft <= fp.top_ft < b.bottom_ft), None)
        scr = well.screen[0] if well.screen else None
        if bore and scr:
            wi, wo = hw(scr.diameter_in), hw(bore.diameter_in)
            for sgn in (-1, 1):
                ax.add_patch(Rectangle((min(sgn * wi, sgn * wo), fp.top_ft), abs(wo - wi), fp.bottom_ft - fp.top_ft, fc="#f2d38b", ec="none", hatch="oo", zorder=2))
        right_labels.append((fp.bottom_ft, f"Filter pack ({fp.top_ft:,.0f}' - {fp.bottom_ft:,.0f}')"))
    if well.packer_depth_ft is not None:
        ax.plot([-0.5, 0.5], [well.packer_depth_ft, well.packer_depth_ft], color="k", lw=3, zorder=5)
        ax.text(-0.55, well.packer_depth_ft, "Packer", ha="right", va="center", fontsize=7)
    if well.static_water_level_ft is not None:
        ax.plot([-0.3, 0.3], [well.static_water_level_ft] * 2, color="#1f77b4", lw=1.2, zorder=6)
        ax.annotate("", (0.32, well.static_water_level_ft), (0.32, well.static_water_level_ft - 0.02 * td),
                    arrowprops=dict(arrowstyle="-|>", color="#1f77b4"))
        ax.text(-0.98, well.static_water_level_ft, f"Est. W.L. ~{well.static_water_level_ft:,.0f}'", va="center", fontsize=7, color="#1f77b4")
    if getattr(well, "pump_setting_ft", None) is not None:
        pw = getattr(well, "pump_diameter_in", None)
        wpump = hw(pw) * 0.9 if pw else 0.12
        ax.add_patch(Rectangle((-wpump, well.pump_setting_ft - 0.03 * td), 2 * wpump, 0.03 * td, fc="#444", ec="k", zorder=6))
        ax.text(-0.98, well.pump_setting_ft, f"Pump setting {well.pump_setting_ft:,.0f}'" + (f" ({_frac(pw)}\")" if pw else ""), va="center", fontsize=7)
    ax.text(0, td * 1.02, f"T.D. {td:,.0f}'", ha="center", va="top", fontsize=8, fontweight="bold")
    # de-overlap right-hand annotations (min gap 4% of TD) and draw leader lines
    right_labels.sort(key=lambda t: t[0])
    gap = 0.045 * td
    placed = []
    for y, txt in right_labels:
        yy = y if not placed or y - placed[-1] >= gap else placed[-1] + gap
        placed.append(yy)
        ax.annotate(txt, xy=(0.5, y), xytext=(1.05, yy), textcoords="data", va="center", fontsize=7,
                    arrowprops=dict(arrowstyle="-", lw=0.5, color="#555"), annotation_clip=False)
    # lithology column
    palette = {"sand": "#f6e27a", "sandy clay": "#c9b27c", "clay": "#9aa89e", "gravel": "#e0c6a0", "shale": "#8f8f8f"}
    for li in well.anticipated_lithology:
        key = next((k for k in palette if k in li.description.lower()), None)
        col = palette.get(key, "#dddddd")
        axl.add_patch(Rectangle((0.1, li.top_ft), 0.8, li.bottom_ft - li.top_ft, fc=col, ec="k", lw=0.6))
        axl.text(0.5, (li.top_ft + li.bottom_ft) / 2, f"{li.description}\n{li.top_ft:,.0f}' - {li.bottom_ft:,.0f}'", ha="center", va="center", fontsize=6.5)
    axl.set_title("Anticipated lithology", fontsize=8)
    ax.set_title(f"{getattr(well, 'title_prefix', 'Proposed')} {well.label} - {well.aquifer} Aquifer", fontsize=9)
    fig.text(0.5, 0.015, "Not to scale horizontally", ha="center", fontsize=7, style="italic")
    return {"path": save(fig, path), "kind": "schematic",
            "caption": getattr(well, "caption", None) or f"Well profile and anticipated lithology for proposed {well.label}"}


def _frac(d):
    whole = int(d)
    frac = d - whole
    table = {0.125: "1/8", 0.25: "1/4", 0.375: "3/8", 0.5: "1/2", 0.625: "5/8", 0.75: "3/4", 0.875: "7/8"}
    for k, v in table.items():
        if abs(frac - k) < 0.02:
            return f"{whole} {v}"
    return f"{d:g}"
