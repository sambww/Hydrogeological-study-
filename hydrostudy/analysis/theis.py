"""Theis (1935) nonequilibrium drawdown and superposition.

Units: Q in gpm at the API boundary (converted to ft3/day internally), T in ft2/day, S dimensionless,
r in feet, t in days, drawdown in feet.  s = Q / (4 pi T) * W(u),  u = r^2 S / (4 T t),  W(u) = E1(u).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq
from scipy.special import exp1

from hydrostudy.units import GPM_TO_CFD


def well_function(u):
    """Theis well function W(u) = E1(u), vectorized."""
    return exp1(np.asarray(u, dtype=float))


def theis_drawdown(q_gpm: float, t_ft2d: float, s: float, r_ft, t_days: float):
    """Drawdown (ft) at radius r after t days from one well pumping q_gpm."""
    if t_ft2d <= 0 or s <= 0 or t_days <= 0:
        raise ValueError("T, S and t must be positive")
    r = np.asarray(r_ft, dtype=float)
    if np.any(r <= 0):
        raise ValueError("r must be positive")
    u = r**2 * s / (4.0 * t_ft2d * t_days)
    return (q_gpm * GPM_TO_CFD) / (4.0 * math.pi * t_ft2d) * well_function(u)


@dataclass(frozen=True)
class PumpingWell:
    id: str
    x_ft: float
    y_ft: float
    q_gpm: float
    r_w_ft: float
    aquifer: str = ""

    def distance_to(self, x_ft, y_ft):
        return np.hypot(np.asarray(x_ft, dtype=float) - self.x_ft, np.asarray(y_ft, dtype=float) - self.y_ft)


def superposed_drawdown(wells: Sequence[PumpingWell], t_ft2d: float, s: float, x_ft, y_ft, t_days: float):
    """Total drawdown at (x, y) from all wells. The radius never drops below a well's own r_w, so
    evaluating at a well's coordinates returns that well's pumped-well drawdown plus interference."""
    x = np.asarray(x_ft, dtype=float)
    y = np.asarray(y_ft, dtype=float)
    total = np.zeros(np.broadcast(x, y).shape, dtype=float)
    for w in wells:
        if w.q_gpm == 0:
            continue
        r = np.maximum(w.distance_to(x, y), w.r_w_ft)
        total = total + theis_drawdown(w.q_gpm, t_ft2d, s, r, t_days)
    return total


@dataclass
class DrawdownBreakdown:
    well_id: str
    total_ft: float
    self_ft: float
    contributions_ft: dict = field(default_factory=dict)  # other well id -> ft
    distances_ft: dict = field(default_factory=dict)      # other well id -> center-to-center ft


def drawdown_at_well(target: PumpingWell, wells: Sequence[PumpingWell], t_ft2d: float, s: float,
                     t_days: float) -> DrawdownBreakdown:
    self_ft = float(theis_drawdown(target.q_gpm, t_ft2d, s, target.r_w_ft, t_days)) if target.q_gpm else 0.0
    contrib, dists = {}, {}
    for w in wells:
        if w.id == target.id or w.q_gpm == 0:
            continue
        d = float(w.distance_to(target.x_ft, target.y_ft))
        dists[w.id] = d
        contrib[w.id] = float(theis_drawdown(w.q_gpm, t_ft2d, s, max(d, w.r_w_ft), t_days))
    return DrawdownBreakdown(target.id, self_ft + sum(contrib.values()), self_ft, contrib, dists)


@dataclass
class RadiusResult:
    threshold_ft: float
    max_ft: float
    mean_ft: float
    min_ft: float
    center_xy: tuple
    per_azimuth_ft: list


def _pumping_center(wells: Sequence[PumpingWell]) -> tuple[float, float]:
    qs = np.array([abs(w.q_gpm) for w in wells], dtype=float)
    if qs.sum() == 0:
        return (float(np.mean([w.x_ft for w in wells])), float(np.mean([w.y_ft for w in wells])))
    x = float(np.sum(qs * np.array([w.x_ft for w in wells])) / qs.sum())
    y = float(np.sum(qs * np.array([w.y_ft for w in wells])) / qs.sum())
    return (x, y)


def radius_at_drawdown(wells: Sequence[PumpingWell], t_ft2d: float, s: float, t_days: float,
                       threshold_ft: float, azimuths: int = 36, r_max_ft: float = 5.0e6) -> RadiusResult:
    """Distance from the pumping center at which total drawdown falls to `threshold_ft`, per azimuth
    (root-find in log r). For a single well this is the analytic cone edge."""
    cx, cy = _pumping_center(wells)
    radii = []
    lo = math.log(max(min(w.r_w_ft for w in wells), 1e-3))
    hi = math.log(r_max_ft)
    for k in range(azimuths):
        az = 2 * math.pi * k / azimuths
        ux, uy = math.cos(az), math.sin(az)

        def f(logr, ux=ux, uy=uy):
            r = math.exp(logr)
            return float(superposed_drawdown(wells, t_ft2d, s, cx + ux * r, cy + uy * r, t_days)) - threshold_ft

        if f(hi) > 0:
            radii.append(r_max_ft)
            continue
        if f(lo) < 0:
            radii.append(0.0)
            continue
        radii.append(math.exp(brentq(f, lo, hi, xtol=1e-6)))
    arr = np.array(radii)
    return RadiusResult(threshold_ft, float(arr.max()), float(arr.mean()), float(arr.min()), (cx, cy), radii)


def drawdown_grid(wells: Sequence[PumpingWell], t_ft2d: float, s: float, t_days: float,
                  half_extent_ft: float, n: int = 401, center: tuple | None = None):
    """Regular grid of superposed drawdown for contouring. Returns (X, Y, S) in local feet."""
    cx, cy = center if center is not None else _pumping_center(wells)
    xs = np.linspace(cx - half_extent_ft, cx + half_extent_ft, n)
    ys = np.linspace(cy - half_extent_ft, cy + half_extent_ft, n)
    X, Y = np.meshgrid(xs, ys)
    return X, Y, superposed_drawdown(wells, t_ft2d, s, X, Y, t_days)


def specific_capacity(q_gpm: float, drawdown_ft: float) -> float:
    if drawdown_ft <= 0:
        raise ValueError("drawdown must be positive")
    return q_gpm / drawdown_ft


def transmissivity_from_specific_capacity(sc_gpm_per_ft: float, t_days: float, r_w_ft: float, s: float,
                                          t0: float = 1000.0, tol: float = 1e-6, max_iter: int = 500) -> float:
    """Theis (1963) / Mace (2001) relation, solved by fixed-point iteration:
    T = Sc / (4 pi) * ln(2.25 T t / (r_w^2 S)), with Sc converted to ft2/day per ft of drawdown."""
    sc = sc_gpm_per_ft * GPM_TO_CFD
    t = t0
    for _ in range(max_iter):
        arg = 2.25 * t * t_days / (r_w_ft**2 * s)
        if arg <= 1:
            raise ValueError("specific-capacity relation invalid for these inputs (ln argument <= 1)")
        t_new = sc / (4 * math.pi) * math.log(arg)
        if abs(t_new - t) < tol * max(1.0, t):
            return t_new
        t = t_new
    raise RuntimeError("transmissivity iteration did not converge")


def transmissivity_from_test(q_gpm: float, drawdown_ft: float, t_days: float, r_w_ft: float, s: float) -> float:
    return transmissivity_from_specific_capacity(specific_capacity(q_gpm, drawdown_ft), t_days, r_w_ft, s)


def cooper_jacob_drawdown(q_gpm: float, t_ft2d: float, s: float, r_ft: float, t_days: float) -> float:
    """Cooper-Jacob straight-line approximation (valid for u < 0.01); used only as a cross-check."""
    u = r_ft**2 * s / (4 * t_ft2d * t_days)
    return (q_gpm * GPM_TO_CFD) / (4 * math.pi * t_ft2d) * (-0.5772156649 - math.log(u))
