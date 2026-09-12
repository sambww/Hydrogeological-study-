"""Figure: original stratigraphic/hydrogeologic column of the Gulf Coast Aquifer System."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from hydrostudy.figures.style import save
from hydrostudy.reference import load_reference


def render(project, path):
    ref = load_reference("aquifers_gulf_coast")
    units = sorted(ref["units"], key=lambda u: u["order"])
    targets = {w.aquifer for w in project.intake.proposed_wells}
    fig, ax = plt.subplots(figsize=(7.5, 0.9 * len(units) + 1.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(len(units), 0)
    ax.axis("off")
    cols = {"aquifer": "#cfe3f5", "confining": "#d9cfc1"}
    ax.text(0.1, -0.25, "Hydrogeologic unit", fontsize=8, fontweight="bold")
    ax.text(3.4, -0.25, "Principal formations", fontsize=8, fontweight="bold")
    ax.text(6.8, -0.25, "Typical lithology", fontsize=8, fontweight="bold")
    for i, u in enumerate(units):
        name = u["hydrogeologic_unit"]
        is_target = any(t in name for t in targets)
        fc = cols.get(u["role"], "#eeeeee")
        ax.add_patch(Rectangle((0, i), 10, 1, fc=fc, ec="k", lw=0.8))
        if is_target:
            ax.add_patch(Rectangle((0, i), 10, 1, fc="none", ec="#d62728", lw=2.2))
        ax.text(0.1, i + 0.5, name + ("\n(target aquifer)" if is_target else ""), va="center", fontsize=8, fontweight="bold" if is_target else "normal")
        ax.text(3.4, i + 0.5, "\n".join(u["formations"]), va="center", fontsize=6.5)
        ax.text(6.8, i + 0.5, _wrap(u["lithology"], 40), va="center", fontsize=6.5)
    ax.set_title(f"{ref['system']}: hydrogeologic units (youngest at top)", fontsize=9, pad=22)
    fig.text(0.5, 0.01, "Summarized from Baker (1979), Kasmarek (2013) and Young and others (2016).", ha="center", fontsize=6.5, style="italic")
    return {"path": save(fig, path), "kind": "strat", "caption": "Hydrogeologic units of the northern Gulf Coast Aquifer System"}


def _wrap(text, n):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    return "\n".join(lines)
