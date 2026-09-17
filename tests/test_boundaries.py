"""Boundaries by the method of images.

Two exact invariants make this checkable to machine precision rather than by eyeball:

* on a recharge boundary the head is fixed, so computed drawdown there must be zero;
* on a barrier boundary no water crosses, so the normal gradient must vanish, which for one boundary
  means drawdown is exactly twice the unbounded value.

If either fails the superposition is wrong, whatever the contours look like.
"""

import math

import numpy as np
import pytest

from hydrostudy.analysis.boundaries import LineBoundary, image_wells, truncation_note, with_images
from hydrostudy.analysis.theis import PumpingWell, superposed_drawdown, theis_drawdown

T, S, Q, DAYS = 1023.0, 3.36e-4, 385.0, 27.4
# A well 400 ft west of a boundary that runs north-south through x = 0.
WELL = PumpingWell("W2", -400.0, 0.0, Q, 0.5, "Evangeline")
NS = dict(x1=0.0, y1=-5000.0, x2=0.0, y2=5000.0)


def _s(wells, x, y, t=DAYS):
    return float(superposed_drawdown(wells, T, S, x, y, t))


def test_a_recharge_boundary_holds_drawdown_at_exactly_zero_along_its_line():
    wells, images = with_images([WELL], [LineBoundary("recharge", **NS, name="Test Creek")])
    assert len(images) == 1
    for y in (-3000.0, -500.0, 0.0, 250.0, 4000.0):
        assert _s(wells, 0.0, y) == pytest.approx(0.0, abs=1e-12)


def test_a_barrier_boundary_doubles_drawdown_along_its_line_and_passes_no_flow():
    boundary = LineBoundary("barrier", **NS, name="Fault")
    wells, images = with_images([WELL], [boundary])
    assert len(images) == 1
    for y in (-2000.0, 0.0, 900.0):
        r = math.hypot(WELL.x_ft - 0.0, WELL.y_ft - y)
        assert _s(wells, 0.0, y) == pytest.approx(2 * float(theis_drawdown(Q, T, S, r, DAYS)), rel=1e-12)
    # No flow across the line: the normal gradient vanishes, so mirrored points match exactly.
    for dx in (10.0, 100.0, 750.0):
        assert _s(wells, -dx, 300.0) == pytest.approx(_s(wells, dx, 300.0), rel=1e-12)


def test_a_barrier_deepens_and_a_recharge_boundary_shallows_the_cone_at_the_pumped_well():
    """The reason either matters: the sign of the correction to an unbounded projection."""
    unbounded = _s([WELL], WELL.x_ft, WELL.y_ft)
    barrier, _ = with_images([WELL], [LineBoundary("barrier", **NS)])
    recharge, _ = with_images([WELL], [LineBoundary("recharge", **NS)])
    assert _s(barrier, WELL.x_ft, WELL.y_ft) > unbounded
    assert _s(recharge, WELL.x_ft, WELL.y_ft) < unbounded


def test_a_distant_boundary_barely_changes_anything():
    """Sanity on the whole idea: at 20 miles a boundary is the infinite aquifer it replaced."""
    far = LineBoundary("barrier", x1=105600.0, y1=-500000.0, x2=105600.0, y2=500000.0)
    wells, _ = with_images([WELL], [far])
    assert _s(wells, WELL.x_ft, WELL.y_ft) == pytest.approx(_s([WELL], WELL.x_ft, WELL.y_ft), rel=1e-6)


def test_the_image_is_the_mirror_of_the_well_with_the_right_rate():
    for kind, sign in (("barrier", 1.0), ("recharge", -1.0)):
        images = image_wells([WELL], [LineBoundary(kind, **NS)])
        img = images[0].well
        assert (img.x_ft, img.y_ft) == pytest.approx((400.0, 0.0))
        assert img.q_gpm == pytest.approx(sign * Q)
        assert img.aquifer == WELL.aquifer and img.r_w_ft == WELL.r_w_ft
        assert img.id != WELL.id and WELL.id in img.id, "an image must be traceable to its parent"
        assert images[0].parent_id == WELL.id and images[0].order == 1


def test_reflection_and_distance_work_on_a_skew_boundary():
    """Nothing may assume the boundary is axis-aligned; a creek never is."""
    b = LineBoundary("recharge", x1=0.0, y1=0.0, x2=1000.0, y2=1000.0)   # the line y = x
    assert b.reflect(300.0, 0.0) == pytest.approx((0.0, 300.0))
    assert b.distance_ft(300.0, 0.0) == pytest.approx(300.0 / math.sqrt(2))
    assert b.distance_ft(500.0, 500.0) == pytest.approx(0.0)
    wells, _ = with_images([PumpingWell("A", 300.0, 0.0, Q, 0.5, "Evangeline")], [b])
    for d in (-1500.0, 0.0, 2000.0):
        assert _s(wells, d, d) == pytest.approx(0.0, abs=1e-12)


def test_two_boundaries_produce_a_truncated_series_that_says_so():
    east = LineBoundary("barrier", **NS, name="East fault")
    west = LineBoundary("barrier", x1=-2000.0, y1=-5000.0, x2=-2000.0, y2=5000.0, name="West fault")
    wells, images = with_images([WELL], [east, west], max_order=6)
    assert len(images) > 2
    assert all(i.order <= 6 for i in images)
    note = truncation_note([east, west], images)
    assert "truncated" in note
    # Two barriers trap the cone, so drawdown must exceed either barrier alone.
    one, _ = with_images([WELL], [east])
    assert _s(wells, WELL.x_ft, WELL.y_ft) > _s(one, WELL.x_ft, WELL.y_ft)

    # More terms may only add drawdown for parallel barriers, and must converge.
    seq = [_s(with_images([WELL], [east, west], max_order=n)[0], WELL.x_ft, WELL.y_ft) for n in (1, 2, 4, 8)]
    assert seq == sorted(seq)
    assert seq[-1] - seq[-2] < seq[1] - seq[0]


def test_one_boundary_is_reported_as_exact():
    b = LineBoundary("recharge", **NS, name="Spring Creek")
    note = truncation_note([b], image_wells([WELL], [b]))
    assert "exact" in note and "Spring Creek" in note
    assert truncation_note([], []) is None


def test_a_boundary_only_ever_makes_finitely_many_images():
    """A single boundary must not reflect its own image back and forth forever."""
    assert len(image_wells([WELL], [LineBoundary("barrier", **NS)], max_order=50)) == 1


def test_bad_boundaries_are_refused():
    with pytest.raises(ValueError, match="coincident"):
        LineBoundary("barrier", x1=1.0, y1=1.0, x2=1.0, y2=1.0)
    with pytest.raises(ValueError, match="barrier"):
        LineBoundary("river", **NS)
    with pytest.raises(ValueError, match="max_order"):
        image_wells([WELL], [LineBoundary("barrier", **NS)], max_order=0)
    on_the_line = PumpingWell("X", 0.0, 0.0, Q, 0.5, "Evangeline")
    with pytest.raises(ValueError, match="constant-head"):
        image_wells([on_the_line], [LineBoundary("recharge", **NS, name="Creek")])
    # A barrier through the well is simply not a barrier, and must not silently become one.
    assert image_wells([on_the_line], [LineBoundary("barrier", **NS)]) == []


def test_images_superpose_on_a_grid_without_special_casing():
    """Whatever consumes wells must not need to know which are images."""
    wells, _ = with_images([WELL], [LineBoundary("recharge", **NS)])
    xs, ys = np.meshgrid(np.linspace(-800, 800, 9), np.linspace(-800, 800, 9))
    field = superposed_drawdown(wells, T, S, xs, ys, DAYS)
    assert field.shape == (9, 9)
    # Antisymmetric about the boundary: the mirrored point is the same magnitude, opposite sign.
    np.testing.assert_allclose(field, -field[:, ::-1], rtol=1e-9, atol=1e-9)
