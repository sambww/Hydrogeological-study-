"""Well-field design: how many wells, where, and at what rate each, to meet a demand.

`analysis/siting.py` answers "where may one well go and what can it make there". A municipality does not
ask that. It asks for 700 gpm, and the answer is a *field*: some number of wells, somewhere on the tract,
each at some rate, that together meet the demand without breaking spacing, without pulling the water level
past what the pumps can lift, and without putting more drawdown on a neighbour than is defensible.

Two observations make that tractable rather than a simulation study.

**For fixed well positions, the best rate split is a linear program.** Every constraint is linear in the
rate vector Q: spacing caps each well individually; Theis (or Hantush-Jacob) drawdown is linear in Q, so
drawdown at each new well and at each neighbouring well is a linear function of Q; the demand is a linear
sum. Maximising total production, or minimising impact at a given production, is therefore an LP in as
many variables as there are wells. No heuristic decides the rates.

**The positions are chosen by greedy placement then coordinate descent.** Placement is genuinely
non-convex - the wells interfere with each other - so it is searched on the same candidate grid the siting
tool uses: place each well where it adds the most deliverable rate, then revisit each well in turn and move
it to the best point with the others held, until nothing improves. This finds a good field, not a provably
optimal one, and the output says so.

The duration is coupled to the answer exactly as in the siting search: max-production duration is
`annual volume / (total rate * 1440)`, so the total rate changes the duration, which changes the drawdown,
which changes the total rate. The LP is re-solved until the total settles.

**Cost.** Nothing here invents a price. A well count is reported always; dollars only when the operator
supplies their own `cost_per_well` and `cost_per_ft`, because drilling costs are a fact about a market and
a rig, not something this module can know.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linprog

from hydrostudy.analysis.siting import (
    MAX_RATE_ITERATIONS,
    MIN_GRID_SPACING_FT,
    RATE_TOL_GPM,
    SQ_FT_PER_ACRE,
    SitingNotPossible,
    candidate_grid,
    fixed_system_wells,
    production_days,
)
from hydrostudy.analysis.solution import resolve_solution
from hydrostudy.analysis.spacing import counts_against_spacing, max_rate_for_distance
from hydrostudy.districts.status import rule_status
from hydrostudy.units import MIN_PER_DAY

#: How many passes of coordinate descent. Each pass moves every well at most once; in practice the field
#: stops moving after two or three.
REFINE_PASSES = 4


class FieldNotPossible(SitingNotPossible):
    """The field cannot be designed: no tract, no spacing multiplier, or no usable candidate points."""


@dataclass
class FieldRequest:
    """What the field has to deliver, and what it is allowed to do to get there."""

    target_rate_gpm: float
    max_wells: int = 6
    grid_spacing_ft: float = 200.0
    setback_ft: float | None = None
    #: A well below this rate is not worth drilling; the LP is free to shut one off entirely instead.
    min_well_rate_gpm: float = 50.0
    #: The most any single well can produce, whatever the aquifer allows: pump, column and screen limits.
    max_well_rate_gpm: float | None = None
    available_drawdown_ft: float | None = None
    max_interference_ft: float | None = None
    #: Distance held back from every spacing limit. An optimal rate split sits exactly *on* its binding
    #: constraint, so without this the design has no margin against the coordinate accuracy of the
    #: District's well export: a well whose location is off by 30 ft turns a compliant design into a
    #: spacing violation. Reported either way, as `spacing_margin_ft` on each well.
    spacing_safety_ft: float = 0.0
    #: Spacing the operator wants between the new wells. The District's rule flags own-system wells inside
    #: the radius rather than forbidding them, so this is a design preference, not a rule, and it is
    #: reported as such.
    min_well_spacing_ft: float | None = None
    aquifer: str | None = None
    #: Operator's own costs. Both must be given for any dollar figure to be reported.
    cost_per_well: float | None = None
    cost_per_ft: float | None = None
    well_depth_ft: float | None = None


@dataclass
class _Layout:
    idx: list                      # indices into the candidate grid
    rates: np.ndarray              # gpm per well, from the LP
    total_gpm: float
    days: float
    worst_neighbour_ft: float
    worst_neighbour_index: int | None
    self_drawdown_ft: np.ndarray   # drawdown at each new well, including every other well's share
    #: The part of the worst neighbour's drawdown that the *existing* system already imposes. On a system
    #: with a well already pumping this is most of it, and calling the total "what this field puts on
    #: that well" would overstate the new field's effect.
    worst_fixed_ft: float = 0.0
    binding: list = field(default_factory=list)


def _unit_matrix(sol, t_ft2d, s, t_days, xa, ya, xb, yb, r_min):
    """Drawdown per gpm at each point b from a well at each point a: shape (len(b), len(a))."""
    r = np.maximum(np.hypot(xb[:, None] - xa[None, :], yb[:, None] - ya[None, :]), r_min)
    return np.asarray(sol.drawdown(1.0, t_ft2d, s, r, t_days), dtype=float)


def _solve_rates(req, caps, a_self, a_neigh, fixed_self, fixed_neigh, target):
    """The best rate split for one set of positions, as a linear program.

    Maximise total production, capped at the target (there is no credit for exceeding the demand, and
    letting it exceed would spend drawdown budget the operator did not ask to spend), subject to:
    per-well spacing caps, available drawdown at each new well, and the interference cap at each
    neighbouring well. Returns (rates, status) with rates all-zero when the program is infeasible.
    """
    n = len(caps)
    ub_rows, ub_vals = [], []
    if req.available_drawdown_ft is not None:
        for i in range(n):
            ub_rows.append(a_self[i])
            ub_vals.append(req.available_drawdown_ft - fixed_self[i])
    if req.max_interference_ft is not None and len(a_neigh):
        for k in range(a_neigh.shape[0]):
            ub_rows.append(a_neigh[k])
            ub_vals.append(req.max_interference_ft - fixed_neigh[k])
    # Never produce more than the demand.
    ub_rows.append(np.ones(n))
    ub_vals.append(target)

    hi = caps.copy()
    if req.max_well_rate_gpm is not None:
        hi = np.minimum(hi, req.max_well_rate_gpm)
    res = linprog(c=-np.ones(n), A_ub=np.array(ub_rows), b_ub=np.array(ub_vals),
                  bounds=[(0.0, float(h)) for h in hi], method="highs")
    if not res.success or res.x is None:
        return np.zeros(n), False
    rates = np.maximum(res.x, 0.0)
    # A well below the operator's minimum is not worth drilling: shut it off and re-solve the rest, so the
    # reported field is one that would actually be built.
    keep = rates >= req.min_well_rate_gpm
    if not keep.all() and keep.any():
        hi2 = np.where(keep, hi, 0.0)
        res2 = linprog(c=-np.ones(n), A_ub=np.array(ub_rows), b_ub=np.array(ub_vals),
                       bounds=[(0.0, float(h)) for h in hi2], method="highs")
        if res2.success and res2.x is not None:
            rates = np.maximum(res2.x, 0.0)
    rates = np.where(rates >= req.min_well_rate_gpm, rates, 0.0)
    return rates, True


def _evaluate(req, idx, ctx, fast: bool = False) -> _Layout:
    """Solve the rates for one set of candidate positions, with the duration coupled to the total.

    `fast` fixes the duration at the one the target rate implies and solves the LP once, instead of
    iterating the rate and the duration to convergence. The search compares thousands of layouts and only
    needs them ranked against each other, which a duration common to all of them does; the layout that
    wins is then re-solved exactly. Without this a single design is twenty thousand linear programs.
    """
    xa = ctx["xs"][idx]
    ya = ctx["ys"][idx]
    caps = ctx["spacing_cap"][idx]
    total = float(min(req.target_rate_gpm, caps.sum()))
    rates = np.zeros(len(idx))
    days = 0.0
    for _ in range(1 if fast else MAX_RATE_ITERATIONS):
        days = float(production_days(req.target_rate_gpm if fast else total,
                                     ctx["fixed_total"], ctx["annual_gal"]))
        a_self = _unit_matrix(ctx["sol"], ctx["T"], ctx["S"], days, xa, ya, xa, ya, ctx["r_w"])
        fixed_self = ctx["fixed_at"](xa, ya, days)
        if len(ctx["nb_x"]):
            a_neigh = _unit_matrix(ctx["sol"], ctx["T"], ctx["S"], days, xa, ya, ctx["nb_x"], ctx["nb_y"],
                                   ctx["r_w"])
            fixed_neigh = ctx["fixed_at"](ctx["nb_x"], ctx["nb_y"], days)
        else:
            a_neigh, fixed_neigh = np.zeros((0, len(idx))), np.zeros(0)
        rates, ok = _solve_rates(req, caps, a_self, a_neigh, fixed_self, fixed_neigh, req.target_rate_gpm)
        if not ok:
            return _Layout(list(idx), np.zeros(len(idx)), 0.0, days, 0.0, None, np.zeros(len(idx)))
        new_total = float(rates.sum())
        if abs(new_total - total) <= RATE_TOL_GPM:
            total = new_total
            break
        total = new_total
        if total <= 0:
            break

    days = float(production_days(max(total, 1e-9), ctx["fixed_total"], ctx["annual_gal"]))
    a_self = _unit_matrix(ctx["sol"], ctx["T"], ctx["S"], days, xa, ya, xa, ya, ctx["r_w"])
    self_dd = a_self @ rates + ctx["fixed_at"](xa, ya, days)
    worst, worst_i, worst_fixed = 0.0, None, 0.0
    if len(ctx["nb_x"]):
        a_neigh = _unit_matrix(ctx["sol"], ctx["T"], ctx["S"], days, xa, ya, ctx["nb_x"], ctx["nb_y"],
                               ctx["r_w"])
        fixed_nb = np.atleast_1d(ctx["fixed_at"](ctx["nb_x"], ctx["nb_y"], days))
        nb_dd = a_neigh @ rates + fixed_nb
        worst_i = int(np.argmax(nb_dd))
        worst = float(nb_dd[worst_i])
        worst_fixed = float(fixed_nb[worst_i])
    return _Layout(list(idx), rates, float(rates.sum()), days, worst, worst_i, self_dd, worst_fixed)


def _allowed(idx, cand, ctx, min_spacing) -> bool:
    """Whether adding `cand` to `idx` respects the operator's well-to-well spacing preference."""
    if not min_spacing:
        return True
    for i in idx:
        if math.hypot(ctx["xs"][cand] - ctx["xs"][i], ctx["ys"][cand] - ctx["ys"][i]) < min_spacing:
            return False
    return True


def _place(req, ctx, n_wells: int, min_spacing) -> _Layout | None:
    """Greedy placement to `n_wells`, then coordinate descent on the same grid."""
    # Seed on the point with the most spacing headroom; ties go to the quietest neighbourhood.
    order = np.lexsort((ctx["neighbour_proximity"], -ctx["spacing_cap"]))
    idx = [int(order[0])]
    best = _evaluate(req, idx, ctx, fast=True)
    while len(idx) < n_wells:
        # A well that adds nothing is not worth a hole, so only keep an addition that raises the total.
        chosen, chosen_layout = None, None
        for cand in order:
            c = int(cand)
            if c in idx or not _allowed(idx, c, ctx, min_spacing):
                continue
            trial = _evaluate(req, [*idx, c], ctx, fast=True)
            if chosen_layout is None or _better(trial, chosen_layout, req):
                chosen, chosen_layout = c, trial
            if trial.total_gpm >= req.target_rate_gpm - RATE_TOL_GPM:
                break          # meets the demand; no need to keep scanning this pass
        if chosen is None or not _better(chosen_layout, best, req):
            break
        idx.append(chosen)
        best = chosen_layout

    for _ in range(REFINE_PASSES):
        moved = False
        for slot in range(len(idx)):
            others = [i for j, i in enumerate(idx) if j != slot]
            for cand in order:
                c = int(cand)
                if c in idx or not _allowed(others, c, ctx, min_spacing):
                    continue
                # The moved well keeps its position in the list. Appending it instead shifts every later
                # slot, so the pass would skip one well and re-examine the one just moved.
                trial_idx = [*idx[:slot], c, *idx[slot + 1:]]
                trial = _evaluate(req, trial_idx, ctx, fast=True)
                if _better(trial, best, req):
                    idx, best, moved = trial_idx, trial, True
        if not moved:
            break
    return best


def _better(a: _Layout, b: _Layout, req: FieldRequest) -> bool:
    """Prefer meeting the demand; among fields that meet it, prefer the least impact on a neighbour."""
    a_meets = a.total_gpm >= req.target_rate_gpm - RATE_TOL_GPM
    b_meets = b.total_gpm >= req.target_rate_gpm - RATE_TOL_GPM
    if a_meets != b_meets:
        return a_meets
    if a_meets and b_meets:
        return a.worst_neighbour_ft < b.worst_neighbour_ft - 1e-9
    return a.total_gpm > b.total_gpm + RATE_TOL_GPM


def design_field(project, req: FieldRequest) -> dict:
    """The cheapest field that meets the demand, and the trade-off curve behind that answer."""
    intake, district, review = project.intake, project.district, project.review
    boundary = getattr(project, "boundary_geom", None)
    if boundary is None:
        raise FieldNotPossible(
            "a well-field design needs the applicant's tract: set site.boundary_geojson in intake.yaml, "
            "or add a `boundary` entry to data/manifest.yaml")
    if req.grid_spacing_ft < MIN_GRID_SPACING_FT:
        raise FieldNotPossible(f"--grid-ft must be at least {MIN_GRID_SPACING_FT:g} ft")
    if req.target_rate_gpm <= 0:
        raise FieldNotPossible("the target rate must be positive")
    if req.target_rate_gpm < req.min_well_rate_gpm:
        raise FieldNotPossible(
            f"the demand ({req.target_rate_gpm:,.0f} gpm) is below the minimum rate a well is worth "
            f"drilling at ({req.min_well_rate_gpm:,.0f} gpm), so every well would be shut off. Lower "
            "--min-well-rate if a well that small is worth it.")
    if req.max_wells < 1:
        raise FieldNotPossible("--max-wells must be at least 1")
    if project.build_boundaries():
        raise FieldNotPossible(
            "this project defines hydraulic boundaries, which the field designer does not yet model, for "
            "the same reason the siting search does not: every candidate carries its own image wells and "
            "points beyond a boundary have no drawdown at all.")

    aquifer = req.aquifer or intake.proposed_wells[0].aquifer
    mult = district.spacing_ft_per_gpm(aquifer)
    if mult is None or mult <= 0:
        raise FieldNotPossible(
            f"the {district['id']} rules file carries no spacing multiplier for the {aquifer}, so no "
            "field can be laid out against the spacing rule")
    params = project.artifacts["analysis"]["aquifer_params"].get(aquifer)
    if params is None:
        known = ", ".join(sorted(project.artifacts["analysis"]["aquifer_params"]))
        raise FieldNotPossible(
            f"the intake defines no aquifer named {aquifer!r}, so it has no transmissivity to design "
            f"against (defined: {known})")
    t_ft2d, s = params["t_ft2d"], params["s"]
    sol, sol_flags = resolve_solution(intake, aquifer, t_ft2d)
    status = rule_status(district)

    template = next((w for w in intake.proposed_wells if w.aquifer == aquifer), intake.proposed_wells[0])
    # A reviewer's evaluation-radius decision governs here exactly as it does in the scenarios, or the
    # drawdown this designs to is not the drawdown the report publishes.
    override = review.decisions.r_w_ft.get(template.id) if review.decisions.r_w_ft else None
    r_w = float(override or template.effective_r_w_ft())
    # Every proposed well in this aquifer is being redesigned, so only the *existing* system wells stay put.
    fixed = [w for w in fixed_system_wells(intake, review, template.id)
             if w.id not in {p.id for p in intake.proposed_wells}]
    fixed_same_aq = [w for w in fixed if w.aquifer == aquifer]
    fixed_total = sum(w.q_gpm for w in fixed)

    # `or` would read an explicit --setback-ft 0 as "not given" and silently apply the district's.
    district_setback = district.get("spacing", {}).get("property_line_setback_ft")
    if req.setback_ft is not None:
        setback_ft, setback_basis = float(req.setback_ft), "supplied on the command line"
    elif district_setback:
        setback_ft, setback_basis = float(district_setback), f"{district['id']} rule (property_line_setback_ft)"
    else:
        setback_ft, setback_basis = 0.0, "none: no property-line setback is recorded for this district"
    xs, ys, edge = candidate_grid(boundary, req.grid_spacing_ft, setback_ft)

    nearby = project.artifacts["nearby_wells"]
    counting = [n for n in nearby if counts_against_spacing(n)]
    if not counting:
        raise FieldNotPossible(
            "the well database holds no well that constrains spacing, so the layout is unconstrained and "
            "there is nothing to design against; check data/district_wells.csv")
    neighbours = [n for n in counting if n["aquifer"] in (aquifer, None)]

    cwx = np.array([n["x_ft"] for n in counting])
    cwy = np.array([n["y_ft"] for n in counting])
    d_counting = np.hypot(xs[:, None] - cwx[None, :], ys[:, None] - cwy[None, :])
    nearest_ft = d_counting.min(axis=1)
    spacing_cap = max_rate_for_distance(nearest_ft, mult, req.spacing_safety_ft)
    nearest_idx = d_counting.argmin(axis=1)

    nb_x = np.array([n["x_ft"] for n in neighbours]) if neighbours else np.zeros(0)
    nb_y = np.array([n["y_ft"] for n in neighbours]) if neighbours else np.zeros(0)

    def fixed_at(tx, ty, days):
        if not fixed_same_aq or len(tx) == 0:
            return np.zeros(len(tx))
        return sum(np.asarray(sol.drawdown(w.q_gpm, t_ft2d, s,
                                           np.maximum(np.hypot(tx - w.x_ft, ty - w.y_ft), w.r_w_ft), days),
                              dtype=float)
                   for w in fixed_same_aq)

    ctx = {"xs": xs, "ys": ys, "edge": edge, "spacing_cap": spacing_cap, "nearest_idx": nearest_idx,
           "nb_x": nb_x, "nb_y": nb_y, "sol": sol, "T": t_ft2d, "S": s, "r_w": r_w,
           "fixed_at": fixed_at, "fixed_total": fixed_total,
           "annual_gal": intake.permit.annual_volume_gal,
           # Tie-break for the greedy seed: prefer points that are far from the wells we would affect.
           "neighbour_proximity": (-np.min(np.hypot(xs[:, None] - nb_x[None, :], ys[:, None] - nb_y[None, :]),
                                           axis=1) if len(nb_x) else np.zeros(len(xs)))}

    min_spacing = req.min_well_spacing_ft
    options = []
    for n_wells in range(1, req.max_wells + 1):
        layout = _place(req, ctx, n_wells, min_spacing)
        if layout is None:
            continue
        # Search was approximate; the field that is going to be reported is solved properly.
        layout = _evaluate(req, layout.idx, ctx)
        drilled = [i for i, q in enumerate(layout.rates) if q > 0]
        if len(drilled) != len(layout.idx):
            # The LP shut some wells off; report the field as the wells that would actually be drilled.
            layout = _Layout([layout.idx[i] for i in drilled], layout.rates[drilled],
                             float(layout.rates[drilled].sum()), layout.days, layout.worst_neighbour_ft,
                             layout.worst_neighbour_index, layout.self_drawdown_ft[drilled],
                             layout.worst_fixed_ft)
        option = _present(layout, n_wells, req, ctx, project, counting, neighbours, mult, aquifer)
        if options and option["total_rate_gpm"] <= options[-1]["total_rate_gpm"] + RATE_TOL_GPM:
            # Another well bought nothing, and a further one cannot: when a neighbour's drawdown is the
            # binding constraint, spreading the same demand over more wells on the same tract barely
            # changes the distance to that well. The row is not added, because a trade-off table that
            # repeats the same field under a bigger well count is worse than one that stops.
            break
        options.append(option)
        if option["meets_target"]:
            break          # the first well count that meets the demand is the cheapest one that can

    met = [o for o in options if o["meets_target"]]
    chosen = met[0] if met else (max(options, key=lambda o: o["total_rate_gpm"]) if options else None)
    if chosen is None:
        raise FieldNotPossible("no layout could be evaluated on this tract")

    notes = list(_notes(req, chosen, status, sol, sol_flags, setback_ft, district, min_spacing, nearby))
    return {
        "aquifer": aquifer, "target_rate_gpm": req.target_rate_gpm,
        "t_ft2d": t_ft2d, "s": s, "r_w_ft": r_w, "ft_per_gpm": mult,
        "solution": sol.to_json(), "rule_status": status,
        "provisional": not status["spacing_authoritative"],
        "setback_ft": setback_ft, "setback_basis": setback_basis, "min_well_spacing_ft": min_spacing,
        "spacing_safety_ft": req.spacing_safety_ft,
        "available_drawdown_ft": req.available_drawdown_ft, "max_interference_ft": req.max_interference_ft,
        "min_well_rate_gpm": req.min_well_rate_gpm, "max_well_rate_gpm": req.max_well_rate_gpm,
        "existing_system_rate_gpm": fixed_total,
        "grid": {"spacing_ft": req.grid_spacing_ft, "candidates": int(len(xs)),
                 "tract_area_acres": boundary.area / SQ_FT_PER_ACRE},
        "feasible": bool(met),
        "recommended": chosen,
        "options": options,
        "notes": notes,
    }


def _present(layout, n_requested, req, ctx, project, counting, neighbours, mult, aquifer) -> dict:
    wells = []
    for slot, gi in enumerate(layout.idx):
        lon, lat = project.crs.to_wgs84(float(ctx["xs"][gi]), float(ctx["ys"][gi]))
        near = counting[int(ctx["nearest_idx"][gi])]
        wells.append({
            "slot": slot + 1, "x_ft": float(ctx["xs"][gi]), "y_ft": float(ctx["ys"][gi]),
            "lat": lat, "lon": lon,
            "rate_gpm": float(layout.rates[slot]),
            "spacing_cap_gpm": float(ctx["spacing_cap"][gi]),
            "required_spacing_ft": float(layout.rates[slot] * mult),
            # How much room is left between the radius this rate claims and the nearest well that
            # constrains it. At the optimum this is the safety distance, and zero without one.
            "spacing_margin_ft": float(math.hypot(ctx["xs"][gi] - near["x_ft"],
                                                  ctx["ys"][gi] - near["y_ft"]) - layout.rates[slot] * mult),
            "drawdown_ft": float(layout.self_drawdown_ft[slot]),
            "boundary_distance_ft": float(ctx["edge"][gi]),
            "nearest_counting_well": {"map_id": near["map_id"], "owner": near["owner"],
                                      "distance_ft": float(math.hypot(ctx["xs"][gi] - near["x_ft"],
                                                                      ctx["ys"][gi] - near["y_ft"]))},
        })
    nb = neighbours[layout.worst_neighbour_index] if layout.worst_neighbour_index is not None else None
    cost = None
    if req.cost_per_well is not None and req.cost_per_ft is not None and req.well_depth_ft:
        cost = len(layout.idx) * (req.cost_per_well + req.cost_per_ft * req.well_depth_ft)
    return {
        "wells_requested": n_requested, "wells_drilled": len(layout.idx),
        "total_rate_gpm": layout.total_gpm,
        "meets_target": layout.total_gpm >= req.target_rate_gpm - RATE_TOL_GPM,
        "shortfall_gpm": max(0.0, req.target_rate_gpm - layout.total_gpm),
        "duration_days": layout.days,
        "volume_gal": (layout.total_gpm + ctx["fixed_total"]) * MIN_PER_DAY * layout.days,
        "worst_neighbour": None if nb is None else {
            "map_id": nb["map_id"], "owner": nb["owner"], "registration_no": nb["registration_no"] or None,
            "aquifer": nb["aquifer"], "drawdown_ft": layout.worst_neighbour_ft,
            "drawdown_from_fixed_wells_ft": layout.worst_fixed_ft,
            "drawdown_from_new_wells_ft": layout.worst_neighbour_ft - layout.worst_fixed_ft},
        "max_well_drawdown_ft": float(np.max(layout.self_drawdown_ft)) if len(layout.idx) else 0.0,
        "wells": wells,
        "estimated_cost": cost,
    }


def _notes(req, chosen, status, sol, sol_flags, setback_ft, district, min_spacing, nearby):
    if not status["spacing_authoritative"]:
        yield ("The spacing multiplier this layout is built on is not from an authoritative reading of the "
               f"District Rules ({status['spacing_source']}), so the whole field is provisional: it is a "
               "layout that complies with the multiplier applied, not a District-approved design.")
    yield ("This is a good field, not a provably optimal one. Well placement is non-convex, so the "
           "positions come from a greedy search refined by local moves on a "
           f"{req.grid_spacing_ft:,.0f}-ft grid; the rate split at those positions is optimal, because "
           "every constraint is linear in the rates.")
    for f in sol_flags:
        yield f["text"]
    if sol.is_leaky:
        yield (f"Drawdown was computed with the {sol.citation}, the same solution the report uses "
               f"(leakance {sol.leakance:g} per day, leakage factor {sol.b_ft:,.0f} ft).")
    if min_spacing:
        yield (f"The new wells were kept {min_spacing:,.0f} ft apart as a design preference. The District "
               "rule flags the applicant's own wells inside a spacing radius rather than forbidding them, "
               "so this distance is the operator's choice and not a requirement.")
    else:
        yield ("No well-to-well spacing was imposed between the new wells. The District rule flags own-system "
               "wells inside a spacing radius rather than forbidding them, so the layout may place wells "
               "closer together than the rule's distance; set --min-well-spacing-ft to prevent that.")
    if not setback_ft:
        yield ("No property-line setback was applied, so a well may sit on the tract line. Confirm the "
               "District's spacing to property lines and the sanitary control easement, then re-run with "
               "--setback-ft.")
    if req.available_drawdown_ft is None:
        yield ("No available-drawdown budget was given, so nothing limited how far the water level is "
               f"pulled down: the deepest well in this field draws {chosen['max_well_drawdown_ft']:,.0f} ft. "
               "Pass --available-drawdown-ft (static level to pump intake) to design against the pump.")
    if req.max_interference_ft is None and chosen.get("worst_neighbour"):
        nb = chosen["worst_neighbour"]
        yield (f"No interference cap was given. The worst-affected well in the database is map ID "
               f"{nb['map_id']}, at {nb['drawdown_ft']:,.1f} ft in total, of which "
               f"{nb['drawdown_from_new_wells_ft']:,.1f} ft is this new field and "
               f"{nb['drawdown_from_fixed_wells_ft']:,.1f} ft is the existing system.")
    thin = [w for w in chosen["wells"] if w["spacing_margin_ft"] < max(req.spacing_safety_ft, 50.0)]
    if thin:
        worst = min(w["spacing_margin_ft"] for w in thin)
        yield (f"The rate split is optimal, which means it sits *on* the spacing limit: "
               f"{len(thin)} well(s) clear the nearest constraining well by as little as {worst:,.0f} ft. "
               "The District's well coordinates are not that precise, so a design with no margin can "
               "become a violation when a neighbour's location is corrected. Re-run with "
               "--spacing-safety-ft to hold back a margin and see what it costs in rate.")
    extent = float(max(n["distance_ft"] for n in nearby)) if nearby else 0.0
    yield (f"Spacing headroom is only as good as the well database, which extends {extent:,.0f} ft from the "
           "intake location. A rate this layout allows assumes no unrecorded well nearer than the nearest "
           "one in that file.")
    if req.cost_per_well is None or req.cost_per_ft is None or not req.well_depth_ft:
        yield ("No cost estimate is reported: pass --cost-per-well, --cost-per-ft and --well-depth-ft to "
               "get one. Drilling costs are a fact about your market and your rig, so this tool does not "
               "supply them.")
