"""Well siting: where on a tract a well may legally go, and how much it can produce there.

Geometry and Theis superposition only.

The spacing limit is closed-form: the District's requirement is a distance proportional to the pumping
rate (`required_spacing_ft = ft_per_gpm * gpm`), so the largest rate spacing permits at a point is the
distance to the nearest counting well divided by that multiplier.

The drawdown limits are not, and the reason is worth stating because it is easy to get wrong. Theis
drawdown is linear in Q at a fixed duration, so a drawdown budget looks like it divides straight into a
rate. But the duration these scenarios run for is the time the permitted annual volume takes to produce,
`volume / (rate * 1440)`, so a lower rate pumps for longer and draws the water level down further. Invert
the budget at the duration the target rate implies and the rate that comes back is too high whenever it
lands below the target. So the rate and the duration are solved together, by iterating from the spacing
limit downwards: each pass takes the rate from the previous one, lengthens the duration accordingly, and
re-inverts the budget. The sequence decreases monotonically from an upper bound, so it converges.

The spacing test is `spacing.counts_against_spacing`, the same predicate the compliance analysis
uses, so the envelope drawn here is the envelope that analysis accepts.

Nothing here decides what the District's multiplier is. When the district rule file does not carry an
authoritative spacing source the whole envelope is reported as provisional, exactly as the spacing
compliance conclusion is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely import contains_xy, distance, points

from hydrostudy.analysis.scenarios import max_production_days
from hydrostudy.analysis.spacing import counts_against_spacing
from hydrostudy.analysis.theis import PumpingWell, theis_drawdown
from hydrostudy.districts.status import rule_status
from hydrostudy.units import DAYS_PER_YEAR, MIN_PER_DAY

SQ_FT_PER_ACRE = 43560.0
# Below this the candidate grid stops being a siting study and starts being a contour plot.
MIN_GRID_SPACING_FT = 5.0
# Rate-and-duration iteration: converged when no candidate's rate moves by more than this.
RATE_TOL_GPM = 0.05
MAX_RATE_ITERATIONS = 40


class SitingNotPossible(RuntimeError):
    """The project cannot be searched: no tract, no spacing multiplier, or an empty candidate set."""


@dataclass
class SitingRequest:
    """What to search for. Everything not given is taken from the project's own intake."""

    well_id: str | None = None
    target_rate_gpm: float | None = None
    grid_spacing_ft: float = 100.0
    setback_ft: float | None = None
    max_interference_ft: float | None = None
    available_drawdown_ft: float | None = None
    top_n: int = 5
    min_separation_ft: float | None = None

    def separation_ft(self) -> float:
        """How far apart ranked locations must be to count as different options.

        Without this the ranking returns one cluster of adjacent grid points, which is a single
        location quoted five times rather than five locations to choose between.
        """
        if self.min_separation_ft is not None:
            return float(self.min_separation_ft)
        return max(2.0 * self.grid_spacing_ft, 200.0)


@dataclass
class _Candidate:
    x_ft: float
    y_ft: float
    boundary_distance_ft: float
    nearest_counting_ft: float
    nearest_counting_index: int
    max_rate_spacing_gpm: float
    max_rate_gpm: float
    binding_constraint: str
    worst_neighbour_ft: float | None
    worst_neighbour_index: int | None
    # At the target rate, over the duration the target rate implies: split into the part the wells that
    # stay put impose and the part per gpm of the sited well.
    self_fixed_ft: float = 0.0
    self_unit_ft: float = 0.0
    worst_fixed_ft: float = 0.0
    worst_unit_ft: float = 0.0
    # At `max_rate_gpm`, over the longer duration that lower rate implies. Not a scaling of the above:
    # the duration moves with the rate, so these have to be evaluated, not multiplied out.
    days_at_max_rate: float = 0.0
    self_at_max_rate_ft: float = 0.0
    max_neighbour_at_max_rate_ft: float = 0.0
    system_wells_inside_radius: list = field(default_factory=list)


def _sited_well(intake, well_id: str | None):
    if well_id is None:
        return intake.proposed_wells[0]
    for w in intake.proposed_wells:
        if w.id == well_id:
            return w
    raise SitingNotPossible(
        f"{well_id} is not a proposed well; siting moves a proposed well, not an existing one "
        f"(proposed: {', '.join(w.id for w in intake.proposed_wells)})")


def _fixed_system_wells(intake, review, sited_id: str) -> list[PumpingWell]:
    """The system wells that stay put while the sited well moves, at their permitted rates."""
    xy = intake._local_xy
    out = []
    for w in intake.all_wells:
        if w.id == sited_id:
            continue
        if w in intake.existing_wells and not w.include_in_system:
            continue
        r_w = w.effective_r_w_ft()
        if review.decisions.r_w_ft and w.id in review.decisions.r_w_ft:
            r_w = review.decisions.r_w_ft[w.id]
        out.append(PumpingWell(w.id, xy[w.id][0], xy[w.id][1], w.max_rate_gpm, r_w, w.aquifer))
    return out


def _grid(boundary, spacing_ft: float, setback_ft: float):
    """Candidate points inside the tract and at least `setback_ft` from its edge, with edge distances."""
    minx, miny, maxx, maxy = boundary.bounds
    nx = max(2, int(math.floor((maxx - minx) / spacing_ft)) + 1)
    ny = max(2, int(math.floor((maxy - miny) / spacing_ft)) + 1)
    # Center the lattice in the tract so the sampled points do not all hug the west and south edges.
    x0 = minx + ((maxx - minx) - (nx - 1) * spacing_ft) / 2.0
    y0 = miny + ((maxy - miny) - (ny - 1) * spacing_ft) / 2.0
    gx, gy = np.meshgrid(x0 + np.arange(nx) * spacing_ft, y0 + np.arange(ny) * spacing_ft)
    xs, ys = gx.ravel(), gy.ravel()
    inside = contains_xy(boundary, xs, ys)
    xs, ys = xs[inside], ys[inside]
    if xs.size == 0:
        raise SitingNotPossible(
            f"no grid point at {spacing_ft:,.0f}-ft spacing falls inside the tract; use a finer --grid-ft")
    edge = distance(points(np.column_stack([xs, ys])), boundary.boundary)
    keep = edge >= setback_ft
    if not keep.any():
        raise SitingNotPossible(
            f"no point on the tract is {setback_ft:,.0f} ft or more from a property line; "
            "the tract is too narrow for that setback")
    return xs[keep], ys[keep], edge[keep]


def _rate_cap(budget_ft: float, fixed_ft, unit_ft):
    """Largest rate whose drawdown keeps `fixed + Q * unit` within the budget, per candidate."""
    headroom = budget_ft - np.asarray(fixed_ft, dtype=float)
    unit = np.asarray(unit_ft, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        cap = np.where(unit > 0, headroom / np.where(unit > 0, unit, 1.0), np.inf)
    # A candidate whose fixed drawdown already exceeds the budget supports no rate at all.
    return np.maximum(cap, 0.0)


def _production_days(rate_gpm, fixed_total_gpm: float, annual_volume_gal: float):
    """Days to produce the permitted annual volume at this rate, capped at a year (element-wise)."""
    total = np.maximum(np.asarray(rate_gpm, dtype=float) + fixed_total_gpm, 1e-9)
    return np.minimum(annual_volume_gal / (total * MIN_PER_DAY), DAYS_PER_YEAR)


def analyze_siting(project, request: SitingRequest | None = None) -> dict:
    """The compliant envelope on the tract, the maximum rate across it, and the best locations."""
    req = request or SitingRequest()
    intake, district, review = project.intake, project.district, project.review
    boundary = getattr(project, "boundary_geom", None)
    if boundary is None:
        raise SitingNotPossible(
            "siting needs the applicant's tract: set site.boundary_geojson in intake.yaml, or add a "
            "`boundary` entry to data/manifest.yaml")
    if req.grid_spacing_ft < MIN_GRID_SPACING_FT:
        raise SitingNotPossible(f"--grid-ft must be at least {MIN_GRID_SPACING_FT:g} ft")

    well = _sited_well(intake, req.well_id)
    # `or` would read 0 as "not given" and quietly search at the intake's rate instead of refusing.
    target = float(req.target_rate_gpm if req.target_rate_gpm is not None else well.max_rate_gpm)
    if target <= 0:
        raise SitingNotPossible("target rate must be positive")
    mult = district.spacing_ft_per_gpm(well.aquifer)
    if mult is None or mult <= 0:
        raise SitingNotPossible(
            f"the {district['id']} rules file carries no spacing multiplier for the {well.aquifer}, so "
            "no envelope can be computed; add one to hydrostudy/districts/ with its source")

    status = rule_status(district)
    params = project.artifacts["analysis"]["aquifer_params"][well.aquifer]
    t_ft2d, s = params["t_ft2d"], params["s"]
    r_w = review.decisions.r_w_ft.get(well.id) if review.decisions.r_w_ft else None
    r_w = float(r_w or well.effective_r_w_ft())

    fixed = _fixed_system_wells(intake, review, well.id)
    fixed_same_aq = [w for w in fixed if w.aquifer == well.aquifer]
    system_rate = target + sum(w.q_gpm for w in fixed)
    duration = max_production_days(intake.permit.annual_volume_gal, system_rate)
    t_days = duration.days

    nearby = project.artifacts["nearby_wells"]
    counting = [n for n in nearby if counts_against_spacing(n)]
    if not counting:
        raise SitingNotPossible(
            "the well database holds no well that constrains spacing, so every point on the tract is "
            "unconstrained and there is nothing to rank; check data/district_wells.csv")
    own_system = [n for n in nearby if n["is_system_well"]]

    # Ranked on wells the drawdown is defensible at: the same aquifer, plus wells whose aquifer the
    # database does not state. A well screened in a different aquifer is reported, never ranked on.
    neighbours = [n for n in counting if n["aquifer"] in (well.aquifer, None)]
    other_aquifer = [n for n in counting if n["aquifer"] not in (well.aquifer, None)]

    # A district setback is a rule and applies whether or not it was asked for; an explicit --setback-ft
    # overrides it either way, including downwards, which is the operator's call to justify.
    district_setback = district.get("spacing", {}).get("property_line_setback_ft")
    if req.setback_ft is not None:
        setback_ft, setback_basis = float(req.setback_ft), "supplied on the command line"
    elif district_setback:
        setback_ft, setback_basis = float(district_setback), f"{district['id']} rule (property_line_setback_ft)"
    else:
        setback_ft, setback_basis = 0.0, "none: no property-line setback is recorded for this district"

    xs, ys, edge = _grid(boundary, req.grid_spacing_ft, setback_ft)
    cwx = np.array([n["x_ft"] for n in counting])
    cwy = np.array([n["y_ft"] for n in counting])
    d_counting = np.hypot(xs[:, None] - cwx[None, :], ys[:, None] - cwy[None, :])
    nearest_idx = d_counting.argmin(axis=1)
    nearest_ft = d_counting.min(axis=1)
    rate_spacing = nearest_ft / mult

    fixed_total = sum(w.q_gpm for w in fixed)
    nb_x = np.array([n["x_ft"] for n in neighbours]) if neighbours else np.zeros(0)
    nb_y = np.array([n["y_ft"] for n in neighbours]) if neighbours else np.zeros(0)
    r_nb = np.maximum(np.hypot(xs[:, None] - nb_x[None, :], ys[:, None] - nb_y[None, :]), r_w)

    def fixed_at(tx, ty, t_days):
        """Drawdown the wells that stay put impose at these points, over these durations."""
        if not fixed_same_aq or tx.size == 0:
            return np.zeros(np.broadcast_shapes(np.shape(tx), np.shape(t_days)))
        return sum(theis_drawdown(w.q_gpm, t_ft2d, s, np.maximum(np.hypot(tx - w.x_ft, ty - w.y_ft), w.r_w_ft),
                                  t_days)
                   for w in fixed_same_aq)

    def caps_at(rate_gpm):
        """Every rate limit, evaluated over the duration that rate itself implies (per candidate)."""
        t = _production_days(rate_gpm, fixed_total, intake.permit.annual_volume_gal)
        out = {"spacing": rate_spacing}
        if neighbours and req.max_interference_ft is not None:
            unit = theis_drawdown(1.0, t_ft2d, s, r_nb, t[:, None])
            # The binding neighbour is the one with the least headroom per gpm, which is not necessarily
            # the one carrying the most drawdown.
            out["interference"] = _rate_cap(req.max_interference_ft,
                                            fixed_at(nb_x, nb_y, t[:, None]), unit).min(axis=1)
        if req.available_drawdown_ft is not None:
            out["available drawdown"] = _rate_cap(req.available_drawdown_ft, fixed_at(xs, ys, t),
                                                  theis_drawdown(1.0, t_ft2d, s, r_w, t))
        return out, t

    # Iterate down from the spacing limit. Dropping the rate lengthens the run, which deepens the
    # drawdown, which drops the rate again, so the sequence is monotone and starts above the answer.
    rate = rate_spacing.copy()
    iterations = 0
    while iterations < MAX_RATE_ITERATIONS:
        iterations += 1
        caps, _ = caps_at(rate)
        nxt = np.min(np.vstack([caps[k] for k in caps]), axis=0)
        moved = float(np.max(np.abs(nxt - rate))) if nxt.size else 0.0
        rate = nxt
        if moved <= RATE_TOL_GPM:
            break
    rate_caps, t_at_rate = caps_at(rate)
    converged = iterations < MAX_RATE_ITERATIONS

    names = list(rate_caps)
    stacked = np.vstack([rate_caps[k] for k in names])
    max_rate = np.minimum(stacked.min(axis=0), rate_spacing)
    binding = [names[i] for i in stacked.argmin(axis=0)]

    # Ranking and the at-target figures use the duration the target rate implies, because that is what a
    # location that can support the target will be pumped for.
    worst_ft = None
    worst_idx = None
    unit_target = None
    fixed_nb_target = None
    if neighbours:
        unit_target = theis_drawdown(1.0, t_ft2d, s, r_nb, t_days)
        fixed_nb_target = fixed_at(nb_x, nb_y, t_days)
        total_at_target = fixed_nb_target[None, :] + target * unit_target
        worst_idx = total_at_target.argmax(axis=1)
        worst_ft = total_at_target.max(axis=1)
    self_unit = float(theis_drawdown(1.0, t_ft2d, s, r_w, t_days))
    self_fixed = fixed_at(xs, ys, t_days)

    # What the location actually does at the rate it can support, over the duration that rate implies.
    self_at_rate = fixed_at(xs, ys, t_at_rate) + max_rate * theis_drawdown(1.0, t_ft2d, s, r_w, t_at_rate)
    if neighbours:
        nb_at_rate = (fixed_at(nb_x, nb_y, t_at_rate[:, None])
                      + max_rate[:, None] * theis_drawdown(1.0, t_ft2d, s, r_nb, t_at_rate[:, None]))
        max_nb_at_rate = nb_at_rate.max(axis=1)
    else:
        max_nb_at_rate = np.full(len(xs), np.nan)

    compliant = max_rate >= target
    spacing_radius_at_target = mult * target
    cand = []
    for i in range(len(xs)):
        inside_own = [{"id": n["registration_no"] or f"map {n['map_id']}", "map_id": n["map_id"],
                       "distance_ft": float(math.hypot(xs[i] - n["x_ft"], ys[i] - n["y_ft"]))}
                      for n in own_system
                      if math.hypot(xs[i] - n["x_ft"], ys[i] - n["y_ft"]) <= spacing_radius_at_target]
        cand.append(_Candidate(
            float(xs[i]), float(ys[i]), float(edge[i]), float(nearest_ft[i]), int(nearest_idx[i]),
            float(rate_spacing[i]), float(max_rate[i]), binding[i],
            None if worst_ft is None else float(worst_ft[i]),
            None if worst_idx is None else int(worst_idx[i]),
            float(self_fixed[i]), self_unit,
            0.0 if worst_idx is None else float(fixed_nb_target[worst_idx[i]]),
            0.0 if worst_idx is None else float(unit_target[i, worst_idx[i]]),
            float(t_at_rate[i]), float(self_at_rate[i]), float(max_nb_at_rate[i]),
            inside_own))

    def describe(n: dict) -> dict:
        return {"map_id": n["map_id"], "registration_no": n["registration_no"] or None, "owner": n["owner"],
                "aquifer": n["aquifer"], "aquifer_inferred": n["aquifer_inferred"], "status": n["status"]}

    def present(c: _Candidate, rank: int) -> dict:
        lon, lat = project.crs.to_wgs84(c.x_ft, c.y_ft)
        nb = neighbours[c.worst_neighbour_index] if c.worst_neighbour_index is not None else None
        # Every drawdown is quoted twice: at the target rate, which is the question asked, and at the rate
        # the location can actually support. Quoting only the first would describe pumping that a
        # rate-limited location is not permitted to do. Only the sited well's term scales with the rate;
        # the wells that stay put contribute the same either way.
        return {
            "rank": rank, "x_ft": c.x_ft, "y_ft": c.y_ft, "lat": lat, "lon": lon,
            "max_rate_gpm": c.max_rate_gpm, "binding_constraint": c.binding_constraint,
            "meets_target": c.max_rate_gpm >= target,
            "max_rate_spacing_gpm": c.max_rate_spacing_gpm,
            "required_spacing_ft": spacing_radius_at_target,
            "nearest_counting_well": describe(counting[c.nearest_counting_index])
            | {"distance_ft": c.nearest_counting_ft},
            "worst_neighbour": None if nb is None else describe(nb) | {
                "distance_ft": float(math.hypot(c.x_ft - nb["x_ft"], c.y_ft - nb["y_ft"])),
                "drawdown_at_target_ft": c.worst_fixed_ft + target * c.worst_unit_ft,
                "drawdown_from_fixed_wells_ft": c.worst_fixed_ft},
            "self_drawdown_at_target_ft": c.self_fixed_ft + target * c.self_unit_ft,
            "self_drawdown_at_max_rate_ft": c.self_at_max_rate_ft,
            "max_neighbour_drawdown_at_max_rate_ft": (None if math.isnan(c.max_neighbour_at_max_rate_ft)
                                                      else c.max_neighbour_at_max_rate_ft),
            "days_at_target_rate": t_days,
            "days_at_max_rate": c.days_at_max_rate,
            "boundary_distance_ft": c.boundary_distance_ft,
            "system_wells_inside_radius": c.system_wells_inside_radius,
            "move_from_intake_ft": float(math.hypot(c.x_ft - project.intake._local_xy[well.id][0],
                                                    c.y_ft - project.intake._local_xy[well.id][1])),
        }

    eligible = [c for c, ok in zip(cand, compliant, strict=True) if ok]
    # Least impact on someone else's well first; where that is a tie (or unknown), most rate headroom.
    order = sorted(eligible, key=lambda c: (c.worst_neighbour_ft if c.worst_neighbour_ft is not None else 0.0,
                                            -c.max_rate_gpm))
    sep = req.separation_ft()
    ranked: list[_Candidate] = []
    for c in order:
        if len(ranked) >= max(1, req.top_n):
            break
        if all(math.hypot(c.x_ft - k.x_ft, c.y_ft - k.y_ft) >= sep for k in ranked):
            ranked.append(c)
    headroom = sorted(cand, key=lambda c: -c.max_rate_gpm)[0]

    cell_acres = req.grid_spacing_ft**2 / SQ_FT_PER_ACRE
    notes = []
    if not status["spacing_authoritative"]:
        notes.append(
            "The spacing multiplier this envelope is built on is not from an authoritative reading of the "
            f"District Rules ({status['spacing_source']}), so the envelope is provisional: it is the area "
            "that complies with the multiplier applied, not a statement of District compliance.")
    # `max_production_days` also flags the un-capped oddity of reaching the annual volume inside a day, which
    # matters here because the whole envelope is evaluated over that duration.
    notes.extend(duration.flags or [])
    if other_aquifer:
        notes.append(
            f"{len(other_aquifer)} well(s) within the data constrain spacing but are screened in another "
            "aquifer; they limit where the well may go and are excluded from the drawdown ranking.")
    if any(n["aquifer"] is None for n in neighbours):
        notes.append("Some wells carry no aquifer in the database and were ranked on as if in the same "
                     "aquifer, which is the conservative reading.")
    data_extent_ft = float(max(n["distance_ft"] for n in nearby)) if nearby else 0.0
    notes.append(
        f"Spacing headroom is only as good as the well database: it extends {data_extent_ft:,.0f} ft from the "
        "intake location. A rate this search allows at a point assumes no unrecorded well nearer than the "
        "nearest one in that file.")
    if setback_ft > 0:
        notes.append(f"A {setback_ft:,.0f}-ft property-line setback was applied ({setback_basis}), so no "
                     "candidate sits closer than that to the tract line.")
    else:
        notes.append(
            "No property-line setback was applied, and the ranking prefers the quietest corner of the tract, so "
            "top locations can sit on the tract line. Confirm the District's spacing to property lines and the "
            "sanitary control easement the well will need, then re-run with --setback-ft.")
    if req.max_interference_ft is not None and "interference" not in names:
        notes.append(
            f"The {req.max_interference_ft:,.2f}-ft interference cap was not applied: no well that constrains "
            "spacing is screened in the "
            f"{well.aquifer} or carries no aquifer in the database, so there is nothing to cap drawdown at.")
    if req.available_drawdown_ft is not None and "available drawdown" not in names:
        notes.append(f"The {req.available_drawdown_ft:,.0f}-ft available-drawdown budget was not applied.")
    if not converged:
        notes.append(
            f"The rate-and-duration iteration did not settle within {MAX_RATE_ITERATIONS} passes; rates are "
            "reported from the last pass and should be treated as approximate.")

    return {
        "well_id": well.id, "well_label": well.label, "aquifer": well.aquifer,
        "target_rate_gpm": target, "r_w_ft": r_w,
        "t_ft2d": t_ft2d, "s": s,
        "duration_days": t_days, "duration_label": duration.label, "duration_capped": duration.capped,
        "system_rate_gpm": system_rate,
        "volume_gal": system_rate * MIN_PER_DAY * t_days,
        "ft_per_gpm": mult, "required_spacing_ft": spacing_radius_at_target,
        "rule_reference": district.get("spacing", {}).get("rule_reference"),
        "rule_status": status, "provisional": not status["spacing_authoritative"],
        "setback_ft": setback_ft, "setback_basis": setback_basis,
        "min_separation_ft": sep,
        "rate_iterations": iterations, "rate_converged": converged,
        "max_interference_ft": req.max_interference_ft,
        "available_drawdown_ft": req.available_drawdown_ft,
        "constraints_applied": names,
        "grid": {
            "spacing_ft": req.grid_spacing_ft, "candidates": len(cand), "compliant": int(compliant.sum()),
            "tract_area_acres": boundary.area / SQ_FT_PER_ACRE,
            "searched_area_acres": len(cand) * cell_acres,
            "compliant_area_acres": float(compliant.sum()) * cell_acres,
        },
        "feasible": bool(compliant.any()),
        "best": [present(c, i + 1) for i, c in enumerate(ranked)],
        "best_by_headroom": present(headroom, 0),
        "counting_wells": [describe(n) | {"distance_ft": n["distance_ft"]} for n in counting],
        "fixed_system_wells": [{"id": w.id, "q_gpm": w.q_gpm, "aquifer": w.aquifer} for w in fixed],
        "notes": notes,
        # The field itself, for the figure and for anyone who wants to contour it.
        "field": {"x_ft": [c.x_ft for c in cand], "y_ft": [c.y_ft for c in cand],
                  "max_rate_gpm": [c.max_rate_gpm for c in cand],
                  "compliant": [bool(v) for v in compliant],
                  "worst_neighbour_ft": [c.worst_neighbour_ft for c in cand]},
    }
