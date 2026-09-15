"""Aquifer-test analysis: specific capacity, Cooper-Jacob straight line, Theis curve fit, Theis recovery,
Jacob step-drawdown. Units: Q gpm (converted to ft3/day internally), T ft2/day, t days, s ft."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.units import GPM_TO_CFD, MIN_PER_DAY

U_LIMIT = 0.01


def specific_capacity(q_gpm: float, drawdown_ft: float) -> float:
    if drawdown_ft <= 0:
        raise ValueError("drawdown must be positive")
    return q_gpm / drawdown_ft


@dataclass
class CooperJacobFit:
    t_ft2d: float | None
    s: float | None                 # storativity, only for observation-well data
    s_reason: str
    slope_ft_per_cycle: float | None
    intercept_ft: float | None
    t0_days: float | None
    n_used: int
    n_total: int
    u_max: float | None
    r2: float | None
    valid: bool
    notes: list = field(default_factory=list)
    t_used_min: list = field(default_factory=list)
    s_used_ft: list = field(default_factory=list)


def cooper_jacob_fit(t_min, s_ft, q_gpm: float, r_ft: float, s_guess: float, observation_well: bool = False,
                     min_points: int = 5, max_iter: int = 12) -> CooperJacobFit:
    """Straight-line fit of drawdown vs log10(t) on the late-time points where u = r^2 S/(4 T t) < 0.01.
    T = 2.303 Q / (4 pi ds), ds = drawdown change per log cycle. S from t0 is reported only for observation wells."""
    t = np.asarray(t_min, dtype=float) / MIN_PER_DAY
    s = np.asarray(s_ft, dtype=float)
    ok = (t > 0) & np.isfinite(s) & (s > 0)
    t, s = t[ok], s[ok]
    n_total = len(t)
    notes = []
    if n_total < min_points:
        return CooperJacobFit(None, None, "insufficient data", None, None, None, 0, n_total, None, None, False,
                              [f"fewer than {min_points} usable points"])
    q_cfd = q_gpm * GPM_TO_CFD
    mask = np.ones_like(t, dtype=bool)
    T = None
    for _ in range(max_iter):
        lt = np.log10(t[mask])
        if len(lt) < min_points or np.ptp(lt) < 0.3:
            break
        slope, intercept = np.polyfit(lt, s[mask], 1)
        if slope <= 0:
            notes.append("non-positive slope; data not consistent with a pumping response")
            return CooperJacobFit(None, None, "invalid fit", float(slope), float(intercept), None, int(mask.sum()), n_total, None, None, False, notes)
        T_new = 2.303 * q_cfd / (4 * math.pi * slope)
        u = r_ft**2 * s_guess / (4 * T_new * t)
        new_mask = u < U_LIMIT
        if new_mask.sum() < min_points:
            # keep the latest min_points points
            idx = np.argsort(t)[-min_points:]
            new_mask = np.zeros_like(mask)
            new_mask[idx] = True
            notes.append(f"fewer than {min_points} points satisfy u < 0.01; latest points used")
        if T is not None and abs(T_new - T) / T < 1e-4 and np.array_equal(new_mask, mask):
            T = T_new
            break
        T, mask = T_new, new_mask
    if T is None:
        return CooperJacobFit(None, None, "invalid fit", None, None, None, 0, n_total, None, None, False, notes + ["fit did not converge"])
    lt = np.log10(t[mask])
    slope, intercept = np.polyfit(lt, s[mask], 1)
    if not np.isfinite(slope) or slope <= 0:
        notes.append("non-positive slope on the selected points; data not consistent with a pumping response")
        return CooperJacobFit(None, None, "invalid fit", None if not np.isfinite(slope) else float(slope),
                              None, None, int(mask.sum()), n_total, None, None, False, notes)
    # The loop ends with `T` derived from the mask of the previous pass while `mask` has already moved on, so the
    # reported transmissivity has to be recomputed from the slope of the points actually reported. Otherwise T,
    # slope, n_used and u_max describe different sets of points, and it is T that gets adopted as the well's value.
    T = 2.303 * q_cfd / (4 * math.pi * slope)
    pred = slope * lt + intercept
    ss_res = float(np.sum((s[mask] - pred) ** 2))
    ss_tot = float(np.sum((s[mask] - s[mask].mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    t0 = 10 ** (-intercept / slope)
    u_max = float(np.max(r_ft**2 * s_guess / (4 * T * t[mask])))
    if observation_well:
        S = 2.25 * T * t0 / r_ft**2
        s_reason = "from the zero-drawdown intercept of the observation-well data"
        if not (1e-6 < S < 0.5):
            notes.append("storativity from intercept is outside the plausible range; check r and t0")
    else:
        S = None
        s_reason = "not determinable from a single-well test (intercept is dominated by well losses and the effective radius)"
    valid = u_max < U_LIMIT and (r2 is None or r2 > 0.9)
    if r2 is not None and r2 <= 0.9:
        notes.append("late-time data are not well fit by a straight line (r2 <= 0.9)")
    return CooperJacobFit(float(T), None if S is None else float(S), s_reason, float(slope), float(intercept), float(t0),
                          int(mask.sum()), n_total, u_max, r2, valid, notes,
                          (t[mask] * MIN_PER_DAY).tolist(), s[mask].tolist())


@dataclass
class TheisFit:
    t_ft2d: float | None
    s: float | None
    s_fixed: bool
    rmse_ft: float | None
    n: int
    valid: bool
    notes: list = field(default_factory=list)


def theis_fit(t_min, s_ft, q_gpm: float, r_ft: float, fix_s: float | None = None, t_guess: float = 1000.0,
              s_guess: float = 1e-4) -> TheisFit:
    """Least-squares match of the Theis curve to the observed drawdown (log-parameter space)."""
    t = np.asarray(t_min, dtype=float) / MIN_PER_DAY
    s = np.asarray(s_ft, dtype=float)
    ok = (t > 0) & np.isfinite(s)
    t, s = t[ok], s[ok]
    if len(t) < 4:
        return TheisFit(None, None, fix_s is not None, None, len(t), False, ["insufficient data"])

    def resid(p):
        T = 10 ** p[0]
        S = fix_s if fix_s is not None else 10 ** p[1]
        return theis_drawdown(q_gpm, T, S, r_ft, t) - s

    p0 = [math.log10(t_guess)] + ([] if fix_s is not None else [math.log10(s_guess)])
    lb = [0.0] + ([] if fix_s is not None else [-7.0])
    ub = [6.0] + ([] if fix_s is not None else [0.0])
    res = least_squares(resid, p0, bounds=(lb, ub))
    T = float(10 ** res.x[0])
    S = float(fix_s) if fix_s is not None else float(10 ** res.x[1])
    rmse = float(np.sqrt(np.mean(res.fun**2)))
    notes = []
    if fix_s is None and not (1e-6 < S < 0.5):
        notes.append("fitted storativity outside the plausible range; a single-well test cannot resolve S reliably")
    return TheisFit(T, S, fix_s is not None, rmse, len(t), res.success and rmse < max(0.05 * float(np.max(s)), 0.5), notes)


@dataclass
class RecoveryFit:
    t_ft2d: float | None
    slope_ft_per_cycle: float | None
    r2: float | None
    n: int
    valid: bool
    notes: list = field(default_factory=list)
    ratio_used: list = field(default_factory=list)
    residual_used_ft: list = field(default_factory=list)


def recovery_fit(t_since_start_min, t_since_stop_min, residual_s_ft, q_gpm: float) -> RecoveryFit:
    """Theis recovery: s' = 2.303 Q / (4 pi T) log10(t / t')."""
    t = np.asarray(t_since_start_min, dtype=float)
    tp = np.asarray(t_since_stop_min, dtype=float)
    sp = np.asarray(residual_s_ft, dtype=float)
    ok = (t > 0) & (tp > 0) & np.isfinite(sp)
    t, tp, sp = t[ok], tp[ok], sp[ok]
    if len(t) < 4:
        return RecoveryFit(None, None, None, len(t), False, ["insufficient data"])
    x = np.log10(t / tp)
    if np.ptp(x) <= 0:
        # Every t/t' identical, which means the stop time was not known. A polyfit here returns NaN, and NaN
        # survives the slope test below, so the caller would adopt a NaN transmissivity.
        return RecoveryFit(None, None, None, len(t), False,
                           ["t/t' does not vary; the time pumping stopped could not be established"])
    slope, intercept = np.polyfit(x, sp, 1)
    if not np.isfinite(slope) or slope <= 0:
        return RecoveryFit(None, None if not np.isfinite(slope) else float(slope), None, len(t), False,
                           ["non-positive slope" if np.isfinite(slope) else "fit did not produce a finite slope"])
    pred = slope * x + intercept
    ss_res = float(np.sum((sp - pred) ** 2))
    ss_tot = float(np.sum((sp - sp.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    T = 2.303 * q_gpm * GPM_TO_CFD / (4 * math.pi * slope)
    return RecoveryFit(float(T), float(slope), r2, len(t), r2 is None or r2 > 0.9, [], x.tolist(), sp.tolist())


@dataclass
class StepFit:
    b_ft_per_gpm: float | None
    c_ft_per_gpm2: float | None
    n_steps: int
    r2: float | None
    valid: bool
    notes: list = field(default_factory=list)
    steps: list = field(default_factory=list)   # [{q_gpm, s_ft, sc_gpm_ft, s_over_q}]

    def efficiency_at(self, q_gpm: float) -> float | None:
        if self.b_ft_per_gpm is None or self.c_ft_per_gpm2 is None:
            return None
        aq = self.b_ft_per_gpm * q_gpm
        return aq / (aq + self.c_ft_per_gpm2 * q_gpm**2)

    def drawdown_at(self, q_gpm: float) -> float | None:
        if self.b_ft_per_gpm is None:
            return None
        return self.b_ft_per_gpm * q_gpm + self.c_ft_per_gpm2 * q_gpm**2


def step_test_fit(steps: list[tuple[float, float]]) -> StepFit:
    """Jacob (1947): s/Q = B + C Q fitted to the end-of-step drawdowns (incremental drawdowns summed)."""
    q = np.array([x[0] for x in steps], dtype=float)
    s = np.array([x[1] for x in steps], dtype=float)
    rows = [{"q_gpm": float(a), "s_ft": float(b), "sc_gpm_ft": float(a / b) if b > 0 else None, "s_over_q": float(b / a)} for a, b in zip(q, s, strict=True)]
    if len(q) < 2:
        return StepFit(None, None, len(q), None, False, ["need at least two steps"], rows)
    y = s / q
    C, B = np.polyfit(q, y, 1)
    notes = []
    if C < 0:
        notes.append("negative well-loss coefficient; well-loss term not physically meaningful, C set to zero")
        C = 0.0
        B = float(np.mean(y))
    pred = B + C * q
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = (1 - ss_res / ss_tot) if ss_tot > 0 and len(q) > 2 else None
    if len(q) == 2:
        notes.append("two steps only: B and C solved exactly, no goodness-of-fit")
    return StepFit(float(B), float(C), len(q), r2, True, notes, rows)


def compare_transmissivity(t_measured: float, t_reference: float) -> dict:
    pct = (t_measured - t_reference) / t_reference * 100.0
    if abs(pct) < 10:
        word = "consistent with"
    elif pct > 0:
        word = "higher than"
    else:
        word = "lower than"
    return {"percent_difference": pct, "relation": word}
