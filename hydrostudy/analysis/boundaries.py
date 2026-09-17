"""Hydraulic boundaries by the method of images.

Theis assumes an aquifer of infinite extent. Two features break that in a way a reviewing geoscientist
will raise, and both have exact analytical answers:

* A **barrier** boundary, where the aquifer ends or a fault throws the sand out of contact. Water cannot
  cross it, so the cone piles up against it and drawdown is *deeper* than Theis predicts.
* A **recharge** boundary, a fully penetrating river or lake in good hydraulic contact, which holds the
  head fixed. Drawdown there is zero and the cone is *shallower* than Theis predicts.

Either is represented exactly by an image well reflected across the boundary line: same sign for a
barrier (its drawdown adds), opposite sign for a recharge boundary (its build-up cancels). The image is
an ordinary pumping well, so everything downstream superposes it without knowing it is not real.

Two facts make this testable to machine precision rather than by eyeball, and `tests/test_boundaries.py`
asserts both: on a recharge boundary the computed drawdown must be exactly zero, and on a barrier
boundary it must be exactly twice the unbounded value, because the real well and its image are
equidistant from every point on the line.

**One boundary is exact.** With two or more, the images reflect in each other forever and the series is
truncated at `max_order`; the truncation is reported rather than hidden, because with two close and
nearly parallel boundaries it is not a small error. Accepting a truncated answer is a judgement for the
sealing professional, not for this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from hydrostudy.analysis.theis import PumpingWell

BoundaryKind = Literal["barrier", "recharge"]
# Reflecting an image back through the boundary that made it returns the original well, so the useful
# series only grows through *other* boundaries. Order 6 covers two boundaries well past the point where
# the terms matter; the cost is linear in the number of images.
DEFAULT_MAX_ORDER = 6
# An image this close to its parent is the same well numerically, and a well sitting on a recharge
# boundary cancels itself exactly.
COINCIDENT_FT = 1e-6
#: Marks an image well's id. Anything reporting per-well numbers uses this to tell an image from a well.
IMAGE_MARKER = "~img"


@dataclass(frozen=True)
class LineBoundary:
    """A straight boundary through two points, in the project's local feet."""

    kind: BoundaryKind
    x1: float
    y1: float
    x2: float
    y2: float
    name: str = ""
    source: str | None = None
    #: The aquifer this boundary bounds, or None to apply it to every aquifer. `for_aquifer` filters on
    #: it, so a fault interpreted in one sand does not silently reshape another's cone.
    aquifer: str | None = None

    def __post_init__(self):
        if self.kind not in ("barrier", "recharge"):
            raise ValueError(f"boundary kind must be 'barrier' or 'recharge', not {self.kind!r}")
        if math.hypot(self.x2 - self.x1, self.y2 - self.y1) < COINCIDENT_FT:
            raise ValueError(f"boundary {self.name or '(unnamed)'} is defined by two coincident points")

    @property
    def sign(self) -> float:
        """What the image well's rate is multiplied by: a barrier adds, a recharge boundary cancels."""
        return 1.0 if self.kind == "barrier" else -1.0

    @property
    def label(self) -> str:
        return self.name or f"{self.kind} boundary"

    def _unit(self) -> tuple[float, float]:
        dx, dy = self.x2 - self.x1, self.y2 - self.y1
        length = math.hypot(dx, dy)
        return dx / length, dy / length

    def distance_ft(self, x: float, y: float) -> float:
        """Perpendicular distance from a point to the (infinite) boundary line."""
        ux, uy = self._unit()
        return abs(-uy * (x - self.x1) + ux * (y - self.y1))

    def signed_offset_ft(self, x: float, y: float) -> float:
        """Perpendicular offset with a sign, so two points can be compared for which side they are on."""
        ux, uy = self._unit()
        return -uy * (x - self.x1) + ux * (y - self.y1)

    def same_side(self, x: float, y: float, ref_x: float, ref_y: float, tol_ft: float = 1e-9) -> bool:
        """Whether a point is on the same side as a reference point (a point on the line counts as same).

        The image-well solution only represents the aquifer on the pumping side of the boundary. On the
        far side it is arithmetic without physical meaning: past a recharge boundary it returns negative
        drawdown, and past a barrier it returns drawdown that grows with distance.
        """
        a = self.signed_offset_ft(x, y)
        b = self.signed_offset_ft(ref_x, ref_y)
        return abs(a) <= tol_ft or (a > 0) == (b > 0)

    def ray_crossing_ft(self, cx: float, cy: float, ux: float, uy: float) -> float:
        """Distance from (cx, cy) along a unit ray to this boundary, or infinity if it never crosses."""
        ny, nx = -self._unit()[1], self._unit()[0]
        denom = ny * ux + nx * uy
        if abs(denom) < 1e-15:
            return math.inf
        r = -self.signed_offset_ft(cx, cy) / denom
        return r if r > 0 else math.inf

    def reflect(self, x: float, y: float) -> tuple[float, float]:
        """Mirror a point across the line."""
        ux, uy = self._unit()
        # Signed perpendicular offset, then step twice that back along the normal.
        d = -uy * (x - self.x1) + ux * (y - self.y1)
        return (x - 2.0 * d * -uy, y - 2.0 * d * ux)


@dataclass(frozen=True)
class ImageWell:
    """An image and where it came from, so the report can say why it is in the superposition."""

    well: PumpingWell
    parent_id: str
    order: int
    boundary_labels: tuple[str, ...]


def image_wells(wells, boundaries, max_order: int = DEFAULT_MAX_ORDER) -> list[ImageWell]:
    """The image wells implied by these boundaries. Empty when there are no boundaries.

    Images of a well are placed in the same aquifer as their parent and carry ids derived from it, so
    nothing downstream mistakes an image for a real well or reports drawdown "at" one.
    """
    if not boundaries:
        return []
    if max_order < 1:
        raise ValueError("max_order must be at least 1")

    out: list[ImageWell] = []
    # (well, index of the boundary that produced it) - reflecting back through that one is the identity.
    for w in wells:
        for b in boundaries:
            if b.kind == "recharge" and b.distance_ft(w.x_ft, w.y_ft) < COINCIDENT_FT:
                raise ValueError(
                    f"well {w.id} lies on recharge boundary {b.label}; a well on a constant-head "
                    "boundary cannot produce drawdown, so check the coordinates")
    frontier = [(w, None, w.id, ()) for w in wells]
    seen = {(round(w.x_ft, 3), round(w.y_ft, 3), w.id) for w in wells}
    for order in range(1, max_order + 1):
        nxt = []
        for parent, from_idx, root_id, labels in frontier:
            for bi, b in enumerate(boundaries):
                if bi == from_idx:
                    continue
                x, y = b.reflect(parent.x_ft, parent.y_ft)
                if math.hypot(x - parent.x_ft, y - parent.y_ft) < COINCIDENT_FT:
                    # This well or image sits on the boundary, so reflecting it is the identity and it
                    # contributes no image. Real wells on a recharge boundary were already refused
                    # above; an *image* landing on another boundary is ordinary geometry, not an error.
                    continue
                key = (round(x, 3), round(y, 3), root_id)
                if key in seen:
                    continue
                seen.add(key)
                new_labels = (*labels, b.label)
                image = PumpingWell(f"{root_id}{IMAGE_MARKER}{len(out) + 1}", x, y, parent.q_gpm * b.sign,
                                    parent.r_w_ft, parent.aquifer)
                out.append(ImageWell(image, root_id, order, new_labels))
                nxt.append((image, bi, root_id, new_labels))
        frontier = nxt
        if not frontier:
            break
    return out


def with_images(wells, boundaries, max_order: int = DEFAULT_MAX_ORDER) -> tuple[list[PumpingWell], list[ImageWell]]:
    """`(wells + their images, the image records)`, ready for superposition."""
    images = image_wells(wells, boundaries, max_order)
    return list(wells) + [i.well for i in images], images


def truncation_note(boundaries, images) -> str | None:
    """What to tell the reader about the exactness of this superposition."""
    if not boundaries:
        return None
    if len(boundaries) == 1:
        b = boundaries[0]
        return (f"The {b.label} is represented by a single image well, which is the exact analytical "
                f"solution for one straight {b.kind} boundary.")
    return (f"{len(boundaries)} boundaries are represented by {len(images)} image wells. Images of "
            "images reflect indefinitely between multiple boundaries, so this series is truncated; "
            "the residual grows as the boundaries get closer together and more nearly parallel, and "
            "the reviewer should confirm the truncation is acceptable for this geometry.")


def is_image(well_id: str) -> bool:
    """Whether an id names an image well rather than a real one."""
    return IMAGE_MARKER in str(well_id)


def beyond(boundaries, x: float, y: float, ref_x: float, ref_y: float) -> list[str]:
    """Labels of the boundaries this point lies beyond, seen from the pumping side.

    A receptor beyond a boundary is outside the aquifer this solution represents, so its drawdown is
    not computed rather than computed wrongly.
    """
    return [b.label for b in boundaries if not b.same_side(x, y, ref_x, ref_y)]


def ray_limit_ft(boundaries, cx: float, cy: float, ux: float, uy: float) -> float:
    """How far a ray from (cx, cy) may be followed before it leaves the aquifer."""
    if not boundaries:
        return math.inf
    return min((b.ray_crossing_ft(cx, cy, ux, uy) for b in boundaries), default=math.inf)


def for_aquifer(boundaries, aquifer: str) -> list:
    """The boundaries that apply to one aquifer: those naming it, plus those naming none."""
    return [b for b in boundaries if getattr(b, "aquifer", None) in (None, "", aquifer)]
