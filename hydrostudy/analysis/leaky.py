"""Hantush-Jacob (1955) drawdown in a leaky confined aquifer.

Theis assumes the confining unit passes no water at all. Where a real confining clay leaks, drawdown
stops growing with the logarithm of time and flattens towards a steady cone, because the pumped water
is increasingly supplied from across the confining unit rather than from storage. Reporting Theis in
that setting overstates long-term drawdown, which is conservative at a neighbour's well and
*un*conservative nowhere - but it also overstates the drawdown at the pumped well, and a reviewing
geoscientist will ask why a semi-confined aquifer was modelled as perfectly confined.

    s = Q / (4 pi T) * W(u, beta),   u = r^2 S / (4 T t),   beta = r / B,   B = sqrt(T / (K' / b'))

`B` is the leakage factor and `K' / b'` the leakance (vertical hydraulic conductivity of the confining
unit over its thickness), in 1/day. The well function is

    W(u, beta) = integral from u to infinity of  exp(-y - beta^2 / (4y)) / y  dy

which has no closed form. It is evaluated here by Gauss-Legendre quadrature after the substitution
y = u e^t, which turns the semi-infinite integral into

    W(u, beta) = integral from 0 to infinity of  exp(-u e^t - (beta^2 / 4u) e^-t)  dt

a smooth unimodal integrand, truncated where both exponents make the contribution negligible. Two
exact limits pin the result and are asserted in `tests/test_leaky.py`: at beta = 0 it must reduce to
the Theis well function E1(u), and as u -> 0 it must approach the Hantush-Jacob steady state
2 K_0(beta). Both hold to better than 1e-13 across the range of practical interest.
"""

from __future__ import annotations

import math

import numpy as np

from hydrostudy.units import GPM_TO_CFD

# Quadrature: 120 nodes carries the two limiting cases to ~1e-14. The integrand is analytic and
# unimodal with a width of order one in t, so nodes buy accuracy cheaply.
QUAD_NODES = 120
# exp(-45) is below double-precision significance next to the peak, so the integrand is truncated
# where either exponent passes this.
EXP_CUTOFF = 45.0
# Elements evaluated per block. Each block allocates a handful of (block x QUAD_NODES) float64 arrays,
# so the peak is roughly block x QUAD_NODES x 8 bytes x (a few): at 10,000 x 120 that is about 10 MB per
# array and well under 100 MB in total, however large the grid is.
BLOCK = 10_000

_X, _W = np.polynomial.legendre.leggauss(QUAD_NODES)
_TINY = 1e-300


def _w_block(u, beta):
    a = beta**2 / 4.0
    u_safe = np.maximum(u, _TINY)
    # Upper limit: where u e^t alone kills the integrand. Lower limit: where (a/u) e^-t does.
    hi = np.log(np.maximum(EXP_CUTOFF / u_safe, 1.0 + 1e-12))
    lo = np.where(a > 0, np.log(np.maximum(a / (u_safe * EXP_CUTOFF), _TINY)), 0.0)
    lo = np.minimum(np.maximum(lo, 0.0), hi)
    mid, half = (hi + lo) / 2.0, (hi - lo) / 2.0
    t = mid[..., None] + half[..., None] * _X
    arg = -(u_safe[..., None] * np.exp(t)) - (a[..., None] / u_safe[..., None]) * np.exp(-t)
    return (np.exp(arg) * _W).sum(-1) * half


def hantush_well_function(u, beta):
    """W(u, beta), vectorized. `beta = 0` returns the Theis well function E1(u)."""
    u = np.asarray(u, dtype=float)
    beta = np.asarray(beta, dtype=float)
    if np.any(u < 0) or np.any(beta < 0):
        raise ValueError("u and beta must be non-negative")
    u, beta = np.broadcast_arrays(u, beta)
    flat_u, flat_b = u.reshape(-1), beta.reshape(-1)
    out = np.empty(flat_u.shape, dtype=float)
    for start in range(0, flat_u.size, BLOCK):
        sl = slice(start, start + BLOCK)
        out[sl] = _w_block(flat_u[sl], flat_b[sl])
    return out.reshape(u.shape)


def leakance_per_day(k_prime_ftd: float, thickness_ft: float) -> float:
    """K' / b' for a confining unit: its vertical conductivity over its thickness, in 1/day."""
    if k_prime_ftd <= 0 or thickness_ft <= 0:
        raise ValueError("confining-unit conductivity and thickness must be positive")
    return k_prime_ftd / thickness_ft


def leakage_factor_ft(t_ft2d, leakance: float):
    """B = sqrt(T / (K'/b')), the distance over which leakage becomes the dominant supply.

    `t_ft2d` may be an array of parameter draws, in which case so is B.
    """
    t_arr = np.asarray(t_ft2d, dtype=float)
    if np.any(t_arr <= 0) or leakance <= 0:
        raise ValueError("transmissivity and leakance must be positive")
    out = np.sqrt(t_arr / leakance)
    return float(out) if out.ndim == 0 else out


def leaky_drawdown(q_gpm: float, t_ft2d, s, r_ft, t_days, leakance: float):
    """Drawdown (ft) at radius r after t days from one well pumping q_gpm through a leaky confining unit.

    As with `theis_drawdown`, T and S may be arrays of parameter draws.
    """
    t_days = np.asarray(t_days, dtype=float)
    t_ft2d = np.asarray(t_ft2d, dtype=float)
    s = np.asarray(s, dtype=float)
    if np.any(t_ft2d <= 0) or np.any(s <= 0) or np.any(t_days <= 0):
        raise ValueError("T, S and t must be positive")
    r = np.asarray(r_ft, dtype=float)
    if np.any(r <= 0):
        raise ValueError("r must be positive")
    b = leakage_factor_ft(t_ft2d, leakance)
    u = r**2 * s / (4.0 * t_ft2d * t_days)
    return (q_gpm * GPM_TO_CFD) / (4.0 * math.pi * t_ft2d) * hantush_well_function(u, r / b)


def steady_drawdown(q_gpm: float, t_ft2d: float, r_ft, leakance: float):
    """The cone this solution settles into: s = Q / (2 pi T) * K_0(r / B), independent of time and S.

    Useful as the ceiling on a leaky-aquifer projection: no pumping duration produces more than this.
    """
    from scipy.special import kv
    b = leakage_factor_ft(t_ft2d, leakance)
    r = np.asarray(r_ft, dtype=float)
    return (q_gpm * GPM_TO_CFD) / (2.0 * math.pi * t_ft2d) * kv(0, r / b)
