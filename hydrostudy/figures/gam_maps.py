"""Figures: GAM transmissivity / hydraulic conductivity / storativity around the site (from data/gam_lookup.json)."""

from __future__ import annotations

import numpy as np
from matplotlib.colors import LogNorm

from hydrostudy.figures.style import COLORS, add_north_arrow, add_scale_bar, new_map, plot_proposed, plt, save

PARAMS = {"t": ("Transmissivity (ft2/day)", "t_ft2d", True), "k": ("Hydraulic conductivity (ft/day)", "k_ftd", True),
          "s": ("Storativity (-)", "s", True)}


def render(project, aquifer: str, param: str, path):
    gam = project.artifacts.get("gam")
    if not gam or not gam.get("neighborhood"):
        return None
    nb = gam["neighborhood"]
    vals = nb.get("values", {}).get(aquifer, {}).get(param)
    if not vals:
        return None
    arr = np.array(vals, dtype=float)
    label, key, log = PARAMS[param]
    intake = project.intake
    cx, cy = intake._local_xy[intake.proposed_wells[0].id]
    x0, y0, dx, dy = nb["x0_ft"] + cx, nb["y0_ft"] + cy, nb["dx_ft"], nb["dy_ft"]
    fig, ax = new_map()
    extent = [x0, x0 + dx * arr.shape[1], y0, y0 + dy * arr.shape[0]]
    pos = arr[np.isfinite(arr) & (arr > 0)]
    norm = LogNorm(vmin=pos.min(), vmax=pos.max()) if log and pos.size and pos.max() / pos.min() > 20 else None
    im = ax.imshow(arr, extent=extent, origin="lower", cmap="RdYlGn", norm=norm, alpha=0.9, zorder=1)
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            v = arr[i, j]
            if np.isfinite(v):
                ax.text(x0 + (j + 0.5) * dx, y0 + (i + 0.5) * dy, f"{v:.2g}" if param == "s" else f"{v:,.0f}", ha="center", va="center", fontsize=5.5, color="#222")
    plot_proposed(ax, project)
    cb = fig.colorbar(im, ax=ax, shrink=0.7)
    cb.set_label(label, fontsize=8)
    site_val = gam["_layers"].get(aquifer, {}).get(key)
    if site_val is not None:
        ax.text(0.02, 0.98, f"{aquifer} Aquifer, site cell: {site_val:.3g}", transform=ax.transAxes, va="top", fontsize=8,
                bbox=dict(fc="white", ec="k", lw=0.5))
    add_scale_bar(ax, (extent[1] - extent[0]) / 2)
    add_north_arrow(ax)
    src = gam.get("_source", "GAM")
    return {"path": save(fig, path), "kind": "gam", "aquifer": aquifer, "param": param,
            "caption": f"{aquifer} Aquifer {label.split(' (')[0].lower()} near the proposed well (from {src})"}


_ = (COLORS, plt)
