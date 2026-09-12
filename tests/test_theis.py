
import pytest

from hydrostudy.analysis.theis import (
    PumpingWell,
    drawdown_at_well,
    radius_at_drawdown,
    superposed_drawdown,
    theis_drawdown,
    transmissivity_from_specific_capacity,
    transmissivity_from_test,
    well_function,
)

T, S = 1023.0, 3.36e-4


@pytest.mark.parametrize("u,expected", [(1e-5, 10.9357), (1e-3, 6.3315), (0.1, 1.8229), (1.0, 0.2194)])
def test_well_function_benchmarks(u, expected):
    assert float(well_function(u)) == pytest.approx(expected, abs=5e-4)


@pytest.mark.parametrize("r,t,expected", [(0.5, 1, 98.7), (0.5, 52.31, 121.5), (25, 1, 53.6), (25, 52.31, 76.4),
                                          (62, 1, 43.2), (62, 52.31, 66.0), (1032, 1, 11.2), (1032, 52.31, 33.5)])
def test_black_oak_reported_values(r, t, expected):
    """District-accepted 2023 submittal: 385 gpm, T=1,023 ft2/d, S=3.36e-4, r_w=0.5 ft."""
    assert float(theis_drawdown(385, T, S, r, t)) == pytest.approx(expected, abs=0.2)


def test_black_oak_system_superposition():
    w2 = PumpingWell("W2", 0, 0, 385, 0.5)
    w1 = PumpingWell("W1", 13.0, -60.6, 350, 0.5)   # coordinates give 62 ft separation
    b = drawdown_at_well(w2, [w1, w2], T, S, 1.0)
    assert b.self_ft == pytest.approx(98.7, abs=0.2)
    assert b.total_ft == pytest.approx(137.3, abs=0.8)     # report 137.3 (consultant used ~65 ft)
    b1 = drawdown_at_well(w1, [w1, w2], T, S, 1.0)
    assert b1.total_ft == pytest.approx(132.3, abs=0.8)
    assert drawdown_at_well(w2, [w1, w2], T, S, 27.4).total_ft == pytest.approx(173.6, abs=1.0)


def test_cone_edges_black_oak():
    w2 = PumpingWell("W2", 0, 0, 385, 0.5)
    e24 = radius_at_drawdown([w2], T, S, 1.0, 1.0)
    assert e24.max_ft == pytest.approx(3731, rel=0.01)       # report reads 3,850 off a raster (within 5%)
    assert abs(e24.max_ft - 3850) / 3850 < 0.05
    e52 = radius_at_drawdown([w2], T, S, 52.31, 1.0)
    assert abs(e52.max_ft / 5280 - 5.3) / 5.3 < 0.05


def test_hidden_forest_values():
    """Jasper Aquifer: 200 gpm, T=440.8, S=3.28e-4, consultant used r_w = 1.0 ft."""
    Tj, Sj = 440.8, 3.28e-4
    assert float(theis_drawdown(200, Tj, Sj, 1.0, 1)) == pytest.approx(103.7, abs=0.6)
    assert float(theis_drawdown(200, Tj, Sj, 1.0, 30)) == pytest.approx(127.8, abs=0.6)
    assert float(theis_drawdown(200, Tj, Sj, 50, 1)) == pytest.approx(49.7, abs=0.5)
    assert float(theis_drawdown(200, Tj, Sj, 50, 30)) == pytest.approx(73.1, abs=0.5)
    e = radius_at_drawdown([PumpingWell("W3", 0, 0, 200, 1.0)], Tj, Sj, 1.0, 5.0)
    assert abs(e.max_ft - 1482.5) / 1482.5 < 0.05
    # Note: the report's 30-day 5-ft edge (9,685 ft) is not reproducible with the stated parameters and is not tested.


def test_enterprise_values():
    """Chicot Aquifer feasibility: two 600-gpm wells ~70 ft apart, T=1917.7, S=4e-4, r_w=1.0 ft, 10 and 20 years."""
    Tc, Sc = 1917.7, 4.0e-4
    assert float(theis_drawdown(600, Tc, Sc, 1.0, 3650)) == pytest.approx(116.9, abs=0.7)
    assert float(theis_drawdown(600, Tc, Sc, 1.0, 7300)) == pytest.approx(120.3, abs=0.7)
    assert float(theis_drawdown(600, Tc, Sc, 70.4, 3650)) == pytest.approx(76.2, abs=0.7)
    assert float(theis_drawdown(600, Tc, Sc, 70.4, 7300)) == pytest.approx(79.4, abs=0.7)
    a = PumpingWell("1", 0, 0, 600, 1.0)
    b = PumpingWell("2", 70.4, 0, 600, 1.0)
    assert drawdown_at_well(a, [a, b], Tc, Sc, 3650).total_ft == pytest.approx(193.7, abs=0.7)
    assert drawdown_at_well(a, [a, b], Tc, Sc, 7300).total_ft == pytest.approx(199.4, abs=0.7)


def test_specific_capacity_to_transmissivity_black_oak():
    """36-hour test of Well No. 1: 270 gpm, 364 -> 434.9 ft; report derived T = 1,023 ft2/day."""
    t = transmissivity_from_test(270, 434.9 - 364, 1.5, 0.5, S)
    assert t == pytest.approx(1023, rel=0.03)
    assert transmissivity_from_specific_capacity(270 / 70.9, 1.5, 0.5, S) == pytest.approx(t)


def test_superposition_grid_symmetry():
    w = PumpingWell("A", 0, 0, 100, 0.5)
    s = superposed_drawdown([w], 1000, 1e-4, [100, -100, 0, 0], [0, 0, 100, -100], 1.0)
    assert all(abs(x - s[0]) < 1e-9 for x in s)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        theis_drawdown(100, 0, 1e-4, 1, 1)
    with pytest.raises(ValueError):
        theis_drawdown(100, 1000, 1e-4, 0, 1)
