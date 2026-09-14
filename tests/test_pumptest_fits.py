"""Edge cases in the aquifer-test fits, where a wrong answer becomes the well's adopted transmissivity.

These are the paths a real field data set reaches and the synthetic example does not: a fit whose late-time point
selection does not settle on the first pass, a recovery series identified only by its time-since-stop column, and a
recovery series with no recorded stop time at all.
"""

import numpy as np
import pytest

from hydrostudy.analysis.pumptest import cooper_jacob_fit, recovery_fit
from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.data.pumptest import TestSeries as Series
from hydrostudy.figures.pumptest import evaluation_radius
from hydrostudy.units import GPM_TO_CFD

T, S, Q = 1023.0, 3.36e-4, 385.0


def _implied_t(slope, q_gpm=Q):
    """Transmissivity the Cooper-Jacob relation gives for a reported slope."""
    return 2.303 * q_gpm * GPM_TO_CFD / (4 * np.pi * slope)


@pytest.mark.parametrize("r_ft", [0.5, 25.0, 150.0, 600.0])
def test_reported_transmissivity_always_matches_the_reported_slope(r_ft):
    """T, slope, n_used and u_max must all describe the same points.

    The point mask is refined against the T it just produced, so the loop can end holding a T from the previous
    pass. Larger radii need more trimming and are where that showed up; T is what gets adopted for the well.
    """
    t = np.unique(np.concatenate([np.arange(1, 10), np.arange(10, 100, 10), np.arange(100, 2161, 60)]))
    s = theis_drawdown(Q, T, S, r_ft, t / 1440)
    fit = cooper_jacob_fit(t, s, Q, r_ft, S, observation_well=r_ft > 1)
    if fit.t_ft2d is None:
        pytest.skip("no fit at this radius")
    assert fit.t_ft2d == pytest.approx(_implied_t(fit.slope_ft_per_cycle), rel=1e-9)
    # And it should still recover the true transmissivity.
    assert fit.t_ft2d == pytest.approx(T, rel=0.1)


def test_a_flat_recovery_series_yields_no_transmissivity_rather_than_nan():
    """Identical t/t' means the stop time was never established; polyfit returns NaN, which passed the slope test."""
    t = np.arange(10, 200, 10, dtype=float)
    fit = recovery_fit(t, t, np.linspace(30, 2, len(t)), Q)   # t' == t for every row
    assert fit.t_ft2d is None
    assert not fit.valid
    assert any("t/t'" in n for n in fit.notes)


def test_recovery_fit_still_works_on_a_real_series():
    t = np.arange(100, 400, 10, dtype=float)
    tp = t - 90.0
    residual = 2.303 * Q * GPM_TO_CFD / (4 * np.pi * T) * np.log10(t / tp)
    fit = recovery_fit(t, tp, residual, Q)
    assert fit.t_ft2d == pytest.approx(T, rel=0.02)
    assert fit.valid


def test_a_recovery_series_is_found_from_t_since_stop_when_no_phase_column_exists():
    """`phase` is documented as optional, so a recovery series must not go unanalysed without it."""
    series = Series(elapsed_min=[10, 20, 30, 40, 50], drawdown_ft=[30, 31, 20, 10, 5],
                    t_since_stop_min=[np.nan, np.nan, 5, 15, 25])
    rec = series.recovery()
    assert rec is not None
    assert rec.n == 3
    # The same rows must be kept out of the pumping curve, or recovery data is fitted as drawdown.
    assert series.pumping().n == 2


def test_a_series_with_neither_phase_nor_stop_times_is_all_pumping():
    series = Series(elapsed_min=[1, 2, 3], drawdown_ft=[1, 2, 3])
    assert series.recovery() is None
    assert series.pumping().n == 3


def test_the_theis_curve_is_drawn_at_the_radius_the_fit_used():
    assert evaluation_radius({"r_w_ft": 0.5, "observation_well": None}) == 0.5
    assert evaluation_radius({"r_w_ft": 0.5, "observation_well": {"id": "OW", "distance_ft": 250.0}}) == 250.0
