"""Hantush-Jacob leaky-aquifer solution.

The well function has no closed form, so it is pinned by two exact limits and one independent
quadrature. If any of these three drift, the solution is wrong and every number built on it is wrong.
"""

import math

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.special import exp1, kv

from hydrostudy.analysis.leaky import (
    hantush_well_function,
    leakage_factor_ft,
    leakance_per_day,
    leaky_drawdown,
    steady_drawdown,
)
from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.units import GPM_TO_CFD


@pytest.mark.parametrize("u", [1e-8, 1e-6, 1e-4, 1e-2, 0.1, 0.5, 1.0, 5.0, 20.0])
def test_no_leakage_reduces_to_the_theis_well_function(u):
    """beta = 0 means a confining unit that passes nothing, which is Theis exactly."""
    assert float(hantush_well_function(u, 0.0)) == pytest.approx(float(exp1(u)), rel=1e-12)


@pytest.mark.parametrize("beta", [0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 4.0])
def test_long_time_reaches_the_hantush_jacob_steady_state(beta):
    """As u -> 0 the cone stops growing: W(0, beta) = 2 K_0(beta)."""
    assert float(hantush_well_function(1e-12, beta)) == pytest.approx(2 * float(kv(0, beta)), rel=1e-10)


@pytest.mark.parametrize(("u", "beta"), [(0.01, 0.1), (0.1, 0.5), (1e-4, 1.0), (0.5, 2.0),
                                         (1e-6, 0.05), (2.0, 0.3), (1e-3, 3.0), (1e-7, 0.2)])
def test_the_mid_range_matches_independent_quadrature(u, beta):
    """Neither limit constrains the middle, where real pump tests live, so integrate it another way."""
    want = quad(lambda y: math.exp(-y - beta**2 / (4 * y)) / y, u, np.inf, limit=400)[0]
    assert float(hantush_well_function(u, beta)) == pytest.approx(want, rel=1e-9)


def test_leakage_always_reduces_drawdown_and_more_leakage_reduces_it_further():
    """The physical claim being made. Water from across the confining unit is water not from storage."""
    T, S, r, t = 1023.0, 3.36e-4, 500.0, 27.4
    theis = float(theis_drawdown(385, T, S, r, t))
    previous = theis
    for leakance in (1e-6, 1e-5, 1e-4, 1e-3):
        got = float(leaky_drawdown(385, T, S, r, t, leakance))
        assert got < previous
        previous = got
    # A vanishingly leaky unit is indistinguishable from Theis.
    assert float(leaky_drawdown(385, T, S, r, t, 1e-14)) == pytest.approx(theis, rel=1e-6)


def test_the_leaky_solution_never_exceeds_its_own_steady_state():
    """The ceiling on a leaky projection: no duration draws the level below the steady cone."""
    T, S, leakance = 1023.0, 3.36e-4, 1e-4
    for r in (0.5, 50.0, 500.0, 2000.0):
        ceiling = float(steady_drawdown(385, T, r, leakance))
        for t in (1.0, 27.4, 365.0, 3650.0, 36500.0):
            assert float(leaky_drawdown(385, T, S, r, t, leakance)) <= ceiling + 1e-9
        # and it gets there
        assert float(leaky_drawdown(385, T, S, r, 1e7, leakance)) == pytest.approx(ceiling, rel=1e-6)


def test_the_leakage_factor_and_leakance_are_the_documented_combinations():
    assert leakance_per_day(0.01, 100.0) == pytest.approx(1e-4)
    # B = sqrt(T / (K'/b'))
    assert leakage_factor_ft(1023.0, 1e-4) == pytest.approx(math.sqrt(1023.0 / 1e-4))
    for bad in ((0.0, 100.0), (0.01, 0.0), (-1.0, 100.0)):
        with pytest.raises(ValueError):
            leakance_per_day(*bad)
    with pytest.raises(ValueError):
        leakage_factor_ft(1023.0, 0.0)


def test_drawdown_is_linear_in_the_rate_at_fixed_duration():
    """Relied on by anything that inverts a drawdown budget into a rate."""
    T, S, r, t, k = 1023.0, 3.36e-4, 300.0, 10.0, 1e-4
    one = float(leaky_drawdown(1.0, T, S, r, t, k))
    for q in (1.0, 50.0, 385.0, 700.0):
        assert float(leaky_drawdown(q, T, S, r, t, k)) == pytest.approx(q * one, rel=1e-12)


def test_the_well_function_broadcasts_and_blocks_without_changing_answers():
    """Grids are evaluated in blocks to cap memory; the blocking must not be visible in the result."""
    from hydrostudy.analysis import leaky
    u = np.logspace(-9, 1, 137)
    beta = np.linspace(0.0, 3.0, 137)
    reference = np.array([float(hantush_well_function(a, b)) for a, b in zip(u, beta, strict=True)])
    vector = hantush_well_function(u, beta)
    assert vector.shape == (137,)
    np.testing.assert_allclose(vector, reference, rtol=1e-12)

    original = leaky.BLOCK
    try:
        leaky.BLOCK = 7            # force many blocks
        np.testing.assert_allclose(hantush_well_function(u, beta), reference, rtol=1e-12)
    finally:
        leaky.BLOCK = original

    grid = hantush_well_function(u[:, None], beta[None, :])
    assert grid.shape == (137, 137)


def test_rejects_impossible_inputs():
    with pytest.raises(ValueError):
        hantush_well_function(-1.0, 0.5)
    with pytest.raises(ValueError):
        hantush_well_function(0.5, -1.0)
    with pytest.raises(ValueError):
        leaky_drawdown(385, 1023.0, 3.36e-4, 0.0, 1.0, 1e-4)
    with pytest.raises(ValueError):
        leaky_drawdown(385, 1023.0, 3.36e-4, 100.0, 0.0, 1e-4)
    with pytest.raises(ValueError):
        leaky_drawdown(385, 0.0, 3.36e-4, 100.0, 1.0, 1e-4)


def test_the_steady_state_is_the_textbook_expression():
    """s = Q / (2 pi T) K_0(r/B), which is W(0, beta) = 2 K_0(beta) carried through the coefficient."""
    T, r, leakance = 1023.0, 400.0, 2e-4
    b = leakage_factor_ft(T, leakance)
    want = (385 * GPM_TO_CFD) / (2 * math.pi * T) * float(kv(0, r / b))
    assert float(steady_drawdown(385, T, r, leakance)) == pytest.approx(want, rel=1e-12)
