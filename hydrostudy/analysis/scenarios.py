"""Scenario construction and execution (per-aquifer Theis superposition)."""

from __future__ import annotations

from dataclasses import dataclass

from hydrostudy.analysis.boundaries import beyond, for_aquifer, is_image, ray_limit_ft, with_images
from hydrostudy.analysis.solution import Solution
from hydrostudy.analysis.theis import PumpingWell, drawdown_at_well, pumping_center, radius_at_drawdown
from hydrostudy.units import DAYS_PER_YEAR, MIN_PER_DAY, fmt_days


@dataclass
class Duration:
    days: float
    label: str
    kind: str          # "24h" | "max_production" | "fixed"
    capped: bool = False
    flags: list = None


def max_production_days(annual_volume_gal: float, total_rate_gpm: float) -> Duration:
    if total_rate_gpm <= 0:
        raise ValueError("rate must be positive")
    days = annual_volume_gal / (total_rate_gpm * MIN_PER_DAY)
    flags = []
    capped = False
    if days > DAYS_PER_YEAR:
        flags.append(f"Annual volume cannot be produced within one year at {total_rate_gpm:,.0f} gpm "
                     f"({days:,.1f} days); simulation capped at 365 days.")
        days, capped = DAYS_PER_YEAR, True
    if days < 1:
        flags.append("Annual volume is reached in less than 24 hours at the maximum rate.")
    return Duration(days, f"{fmt_days(days)} days", "max_production", capped, flags)


def _pumping_wells(intake, review, well_ids) -> list[PumpingWell]:
    xy = intake._local_xy  # set by the pipeline
    wells = []
    for w in intake.all_wells:
        if w.id not in well_ids:
            continue
        r_w = w.effective_r_w_ft()
        if review.decisions.r_w_ft and w.id in review.decisions.r_w_ft:
            r_w = review.decisions.r_w_ft[w.id]
        wells.append(PumpingWell(w.id, xy[w.id][0], xy[w.id][1], w.max_rate_gpm, r_w, w.aquifer))
    return wells


def build_scenarios(intake, review, aquifer_params: dict) -> list[dict]:
    cfg = intake.analysis.scenarios
    system_ids = [w.id for w in intake.proposed_wells] + [w.id for w in intake.existing_wells if w.include_in_system]
    scen = []
    # A) each proposed well alone
    for pw in intake.proposed_wells:
        durs = []
        if cfg.include_24h:
            durs.append(Duration(1.0, "24 hours", "24h"))
        if cfg.include_max_production:
            durs.append(max_production_days(intake.permit.annual_volume_gal, pw.max_rate_gpm))
        for i, d in enumerate(cfg.fixed_durations_days):
            lbl = cfg.fixed_duration_labels[i] if i < len(cfg.fixed_duration_labels) else f"{fmt_days(d)} days"
            durs.append(Duration(d, lbl, "fixed"))
        for d in durs:
            scen.append({"key": f"proposed_{pw.id}_{d.kind}_{d.days:g}", "group": "proposed_only",
                         "title": f"Proposed {pw.id} only, {d.label}", "well_ids": [pw.id],
                         "focus_well": pw.id, "duration": d})
    # B) whole system (only if more than one system well)
    if len(system_ids) > 1:
        total = sum(w.max_rate_gpm for w in intake.all_wells if w.id in system_ids)
        durs = []
        if cfg.include_24h:
            durs.append(Duration(1.0, "24 hours", "24h"))
        if cfg.include_max_production:
            durs.append(max_production_days(intake.permit.annual_volume_gal, total))
        for i, d in enumerate(cfg.fixed_durations_days):
            lbl = cfg.fixed_duration_labels[i] if i < len(cfg.fixed_duration_labels) else f"{fmt_days(d)} days"
            durs.append(Duration(d, lbl, "fixed"))
        for d in durs:
            scen.append({"key": f"system_{d.kind}_{d.days:g}", "group": "system",
                         "title": f"All system wells, {d.label}", "well_ids": list(system_ids),
                         "focus_well": None, "duration": d})
        if cfg.include_single_well_subcases:
            proposed_ids = {w.id for w in intake.proposed_wells}
            for w in intake.all_wells:
                if w.id in system_ids and w.id not in proposed_ids:   # proposed wells alone are already group A
                    for i, dd in enumerate(cfg.fixed_durations_days):
                        lbl = cfg.fixed_duration_labels[i] if i < len(cfg.fixed_duration_labels) else f"{fmt_days(dd)} days"
                        scen.append({"key": f"single_{w.id}_fixed_{dd:g}", "group": "single_well_subcase",
                                     "title": f"Only {w.id} pumping, {lbl}", "well_ids": [w.id],
                                     "focus_well": w.id, "duration": Duration(dd, lbl, "fixed")})
    return scen


def run_scenario(sc: dict, intake, review, aquifer_params: dict, nearby: list[dict],
                 boundaries: list | None = None, solutions: dict | None = None) -> dict:
    """One scenario, per aquifer.

    `group` is the real pumping wells, which is what gets reported; `field` is that group plus any
    image wells the boundaries imply, which is what drawdown is computed from. Keeping them separate is
    the whole trick: an image well belongs in every superposition and in no table.
    """
    d: Duration = sc["duration"]
    wells = _pumping_wells(intake, review, set(sc["well_ids"]))
    by_aq = {}
    for w in wells:
        by_aq.setdefault(w.aquifer, []).append(w)
    thresholds = review.decisions.cone_edge_thresholds_ft or intake.analysis.cone_edge_thresholds_ft
    mode = review.decisions.other_aquifer_wells or intake.analysis.other_aquifer_wells
    boundaries = boundaries or []
    results = {}
    for aq, group in by_aq.items():
        p = aquifer_params[aq]
        T, S = p["t_ft2d"], p["s"]
        sol = (solutions or {}).get(aq) or Solution("theis")
        fn = sol.drawdown
        # A boundary is interpreted for a specific sand unless it names none, so an interpretation about
        # one aquifer does not silently bend another aquifer's cone.
        aq_bounds = for_aquifer(boundaries, aq)
        field, images = with_images(group, aq_bounds, intake.analysis.image_max_order)
        center = pumping_center(group)

        # Everything from the enclosing loop is bound as a default: this closure is only ever called
        # within the iteration that made it, and binding makes that true by construction.
        def receptor(x, y, cx=center[0], cy=center[1], bl=aq_bounds, fld=None, days=None,
                     fn=fn, T=T, S=S):
            """Drawdown at a point, or None when the point lies beyond a boundary.

            Past a boundary the image superposition is arithmetic without meaning: negative drawdown
            beyond a recharge boundary, drawdown growing with distance beyond a barrier. Reporting
            nothing and saying why is the only defensible answer.
            """
            outside = beyond(bl, x, y, cx, cy)
            if outside:
                return None, outside
            return float(sum(fn(g.q_gpm, T, S, max(g.distance_to(x, y), g.r_w_ft), days) for g in fld)), []
        pumped = []
        for w in group:
            bd = drawdown_at_well(w, field, T, S, d.days, fn)
            iw = next(x for x in intake.all_wells if x.id == w.id)
            # An image's contribution is real drawdown but it is not "from" another well, so it is
            # reported as the boundary's effect instead of hiding inside an interference cell.
            image_share = float(sum(v for k, v in bd.contributions_ft.items() if is_image(k)))
            if iw.nearest_property_boundary_ft is None:
                bp_ft, bp_beyond = None, []
            else:
                bp_ft, bp_beyond = receptor(*_boundary_point(w, iw.nearest_property_boundary_ft),
                                            fld=field, days=d.days)
            pumped.append({"id": w.id, "q_gpm": w.q_gpm, "r_w_ft": w.r_w_ft, "total_ft": bd.total_ft,
                           "self_ft": bd.self_ft,
                           "distances_ft": {k: v for k, v in bd.distances_ft.items() if not is_image(k)},
                           "boundary_distance_ft": iw.nearest_property_boundary_ft,
                           "boundary_effect_ft": image_share,
                           "contributions_ft": {k: v for k, v in bd.contributions_ft.items() if not is_image(k)},
                           "boundary_drawdown_ft": bp_ft, "boundary_drawdown_beyond": bp_beyond})
        # all system wells in this aquifer (including idle ones) get a drawdown value
        idle = []
        for x in intake.all_wells:
            if x.aquifer == aq and x.id not in {w.id for w in group}:
                xy = intake._local_xy[x.id]
                s_idle, outside = receptor(*xy, fld=field, days=d.days)
                idle.append({"id": x.id, "total_ft": s_idle, "beyond_boundary": outside})
        def limit(ux, uy, cx=center[0], cy=center[1], bl=aq_bounds):
            return ray_limit_ft(bl, cx, cy, ux, uy)

        edges = [radius_at_drawdown(field, T, S, d.days, th, fn=fn, center=center,
                                    limit_fn=limit if aq_bounds else None) for th in thresholds]
        impacts = []
        for n in nearby:
            if not n["in_search_radius"] and not n["is_system_well"]:
                continue
            same = (n["aquifer"] == aq)
            if n["aquifer"] is None:
                applic = "unknown"
            elif same:
                applic = "same"
            else:
                applic = "different"
            outside = []
            if applic != "same" and mode == "na":
                dd = None
            else:
                dd, outside = receptor(n["x_ft"], n["y_ft"], fld=field, days=d.days)
            impacts.append({"map_id": n["map_id"], "registration_no": n["registration_no"], "permit_no": n["permit_no"],
                            "owner": n["owner"], "total_depth_ft": n["total_depth_ft"],
                            "screen_intervals": n["screen_intervals"], "aquifer": n["aquifer"],
                            "aquifer_inferred": n["aquifer_inferred"], "status": n["status"],
                            "distance_ft": n["distance_ft"], "drawdown_ft": dd, "applicability": applic,
                            "beyond_boundary": outside, "is_system_well": n["is_system_well"]})
        results[aq] = {"t_ft2d": T, "s": S, "solution": sol.to_json(), "pumped_wells": pumped, "idle_wells": idle,
                       "cone_edges": [{"threshold_ft": e.threshold_ft, "max_ft": e.max_ft, "mean_ft": e.mean_ft,
                                       "min_ft": e.min_ft, "center_xy": list(e.center_xy),
                                       "truncated_azimuths": e.truncated_azimuths} for e in edges],
                       "nearby_impacts": impacts,
                       "wells_xy": [{"id": w.id, "x_ft": w.x_ft, "y_ft": w.y_ft, "q_gpm": w.q_gpm, "r_w_ft": w.r_w_ft} for w in group],
                       # Images are listed separately so the contour maps superpose exactly what the
                       # tables were computed from, without any table treating one as a real well.
                       "image_wells": [{"id": i.well.id, "parent_id": i.parent_id, "order": i.order,
                                        "x_ft": i.well.x_ft, "y_ft": i.well.y_ft, "q_gpm": i.well.q_gpm,
                                        "r_w_ft": i.well.r_w_ft, "boundaries": list(i.boundary_labels)}
                                       for i in images],
                       "boundary_labels": [b.label for b in aq_bounds],
                       "center_xy": list(center)}
    total_rate = sum(w.q_gpm for w in wells)
    return {"key": sc["key"], "group": sc["group"], "title": sc["title"], "well_ids": sc["well_ids"],
            "focus_well": sc["focus_well"], "duration_days": d.days, "duration_label": d.label,
            "duration_kind": d.kind, "duration_capped": d.capped, "duration_flags": d.flags or [],
            "total_rate_gpm": total_rate, "volume_gal": total_rate * MIN_PER_DAY * d.days,
            "results_by_aquifer": results}


def _boundary_point(w: PumpingWell, dist_ft: float):
    """Nearest property boundary is represented as a point `dist_ft` due east of the well."""
    return (w.x_ft + dist_ft, w.y_ft)
