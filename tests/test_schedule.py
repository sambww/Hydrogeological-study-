"""Variable pumping rates by superposition in time.

Pinned by three exact identities: one step is the constant-rate solution, pump-then-stop is the Theis
recovery expression, and the whole construction is linear in the rates.
"""

import functools
import math

import numpy as np
import pytest

from hydrostudy.analysis.leaky import leaky_drawdown
from hydrostudy.analysis.schedule import (
    RateStep,
    normalize,
    rate_at,
    residual_drawdown,
    schedule_drawdown,
    volume_gal,
)
from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.units import GPM_TO_CFD, MIN_PER_DAY

T, S, Q, R = 1023.0, 3.36e-4, 385.0, 250.0


def test_one_step_is_the_constant_rate_solution():
    for t in (0.5, 1.0, 27.4, 365.0):
        got = float(schedule_drawdown([RateStep(0.0, Q)], T, S, R, t))
        assert got == pytest.approx(float(theis_drawdown(Q, T, S, R, t)), rel=1e-12)


def test_pumping_then_stopping_is_the_theis_recovery_expression():
    """Residual drawdown after shutdown: s' = Q/(4 pi T) [W(u) - W(u')], and its late-time log form."""
    stop = 1.5
    for t in (1.6, 2.0, 3.0, 10.0):
        got = float(residual_drawdown(Q, stop, T, S, R, t))
        want = float(theis_drawdown(Q, T, S, R, t)) - float(theis_drawdown(Q, T, S, R, t - stop))
        assert got == pytest.approx(want, rel=1e-12)
    # Late time, where u and u' are both small, must match the straight-line recovery formula the
    # post-drilling analysis fits (s' = 2.303 Q / (4 pi T) log10(t / t')).
    t = 400.0
    got = float(residual_drawdown(Q, stop, T, S, R, t))
    want = 2.303 * Q * GPM_TO_CFD / (4 * math.pi * T) * math.log10(t / (t - stop))
    assert got == pytest.approx(want, rel=1e-3)


def test_nothing_happens_before_the_first_step():
    assert float(schedule_drawdown([RateStep(5.0, Q)], T, S, R, 4.9)) == 0.0
    assert float(schedule_drawdown([], T, S, R, 10.0)) == 0.0
    assert rate_at([RateStep(5.0, Q)], 4.9) == 0.0
    assert rate_at([RateStep(5.0, Q)], 5.0) == Q


def test_a_step_up_and_a_step_down_are_both_just_superposition():
    steps = [RateStep(0.0, 200.0), RateStep(2.0, 500.0), RateStep(4.0, 100.0)]
    t = 6.0
    want = (float(theis_drawdown(200.0, T, S, R, t))
            + float(theis_drawdown(300.0, T, S, R, t - 2.0))
            + float(theis_drawdown(-400.0, T, S, R, t - 4.0)))
    assert float(schedule_drawdown(steps, T, S, R, t)) == pytest.approx(want, rel=1e-12)
    # A step down leaves less drawdown than if the high rate had continued.
    held = [RateStep(0.0, 200.0), RateStep(2.0, 500.0)]
    assert float(schedule_drawdown(steps, T, S, R, t)) < float(schedule_drawdown(held, T, S, R, t))


def test_the_schedule_is_linear_in_the_rates():
    steps = [RateStep(0.0, 200.0), RateStep(2.0, 500.0), RateStep(4.0, 0.0)]
    doubled = [RateStep(s.start_day, 2 * s.rate_gpm) for s in steps]
    for t in (1.0, 3.0, 5.0, 50.0):
        a = float(schedule_drawdown(steps, T, S, R, t))
        b = float(schedule_drawdown(doubled, T, S, R, t))
        assert b == pytest.approx(2 * a, rel=1e-12)


def test_a_cycling_well_draws_down_less_than_one_pumping_flat_out():
    """The practical point: duty cycle matters, and the constant-rate case is the conservative one."""
    flat = [RateStep(0.0, Q)]
    cycling = [RateStep(d + phase, rate) for d in range(0, 30, 2)
               for phase, rate in ((0.0, Q), (1.0, 0.0))]
    for t in (10.0, 20.0, 30.0):
        assert float(schedule_drawdown(cycling, T, S, R, t)) < float(schedule_drawdown(flat, T, S, R, t))


def test_the_schedule_works_with_the_leaky_solution_too():
    """The solution is injected, so a rate schedule in a leaky aquifer needs no new code."""
    leakance = 1e-4
    leaky = functools.partial(_leaky, leakance=leakance)
    one_step = float(schedule_drawdown([RateStep(0.0, Q)], T, S, R, 27.4, solution=leaky))
    assert one_step == pytest.approx(float(leaky_drawdown(Q, T, S, R, 27.4, leakance)), rel=1e-12)
    # And leakage still reduces drawdown relative to Theis for the same schedule.
    steps = [RateStep(0.0, 200.0), RateStep(2.0, 500.0)]
    assert (float(schedule_drawdown(steps, T, S, R, 30.0, solution=leaky))
            < float(schedule_drawdown(steps, T, S, R, 30.0)))


def _leaky(q_gpm, t_ft2d, s, r_ft, t_days, leakance):
    return leaky_drawdown(q_gpm, t_ft2d, s, r_ft, t_days, leakance)


def test_volume_and_rate_bookkeeping():
    steps = [RateStep(0.0, 100.0), RateStep(1.0, 0.0), RateStep(2.0, 300.0)]
    assert volume_gal(steps, 1.0) == pytest.approx(100.0 * MIN_PER_DAY * 1.0)
    assert volume_gal(steps, 2.0) == pytest.approx(100.0 * MIN_PER_DAY * 1.0)
    assert volume_gal(steps, 3.0) == pytest.approx(100.0 * MIN_PER_DAY + 300.0 * MIN_PER_DAY)
    assert volume_gal(steps, 0.0) == 0.0


def test_steps_are_normalized_and_bad_ones_refused():
    unsorted = [RateStep(4.0, 100.0), RateStep(0.0, 200.0), RateStep(2.0, 200.0)]
    out = normalize(unsorted)
    assert [s.start_day for s in out] == [0.0, 4.0], "a change to the same rate is not a change"
    with pytest.raises(ValueError, match="same time"):
        normalize([RateStep(1.0, 100.0), RateStep(1.0, 200.0)])
    with pytest.raises(ValueError, match="before time zero"):
        RateStep(-1.0, 100.0)


def test_it_broadcasts_over_radius_and_time():
    steps = [RateStep(0.0, 200.0), RateStep(2.0, 500.0)]
    r = np.array([50.0, 250.0, 1000.0])
    got = schedule_drawdown(steps, T, S, r, 10.0)
    assert got.shape == (3,)
    assert got[0] > got[1] > got[2]
    times = np.array([1.0, 3.0, 30.0])
    over_time = schedule_drawdown(steps, T, S, R, times)
    assert over_time.shape == (3,)
    assert over_time[0] < over_time[1] < over_time[2]
