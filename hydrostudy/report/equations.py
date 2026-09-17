"""Render the Theis equations as images (mathtext) so they display identically in Word and LibreOffice."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

EQUATIONS = {
    "theis": r"$s = \dfrac{Q}{4\pi T}\,W(u)$",
    "well_function": r"$W(u) = \int_{u}^{\infty} \dfrac{e^{-y}}{y}\,dy = -0.5772 - \ln u + u - \dfrac{u^{2}}{2\cdot 2!} + \dfrac{u^{3}}{3\cdot 3!} - \cdots$",
    "u": r"$u = \dfrac{r^{2} S}{4 T t}$",
    "specific_capacity": r"$T = \dfrac{S_c}{4\pi}\,\ln\!\left(\dfrac{2.25\,T\,t}{r_w^{2} S}\right)$",
    # Hantush-Jacob, shown in place of the Theis pair when a leaky solution was used.
    "hantush": r"$s = \dfrac{Q}{4\pi T}\,W\!\left(u,\, \dfrac{r}{B}\right)$",
    "hantush_well_function": r"$W\!\left(u, \dfrac{r}{B}\right) = \int_{u}^{\infty} \dfrac{1}{y}\,\exp\!\left(-y - \dfrac{r^{2}}{4 B^{2} y}\right) dy$",
    "leakage_factor": r"$B = \sqrt{\dfrac{T}{K' / b'}}$",
}


def render_equations(out_dir) -> dict:
    out = {}
    for key, tex in EQUATIONS.items():
        fig = plt.figure(figsize=(6, 0.9))
        fig.text(0.5, 0.5, tex, ha="center", va="center", fontsize=14)
        p = out_dir / f"eq_{key}.png"
        fig.savefig(p, dpi=250, bbox_inches="tight", transparent=True)
        plt.close(fig)
        out[key] = str(p)
    return out
