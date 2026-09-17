"""Stage runner: intake + local data -> build/*.json -> figures -> report."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

from hydrostudy import __version__
from hydrostudy.analysis.aquifer_params import resolve_params
from hydrostudy.analysis.checks import collect_flags
from hydrostudy.analysis.interference import pumping_level_checks, system_interference_matrix
from hydrostudy.analysis.scenarios import build_scenarios, run_scenario
from hydrostudy.analysis.solution import leakage_reach_note, resolve_solution
from hydrostudy.analysis.spacing import spacing_analysis
from hydrostudy.analysis.theis import PumpingWell
from hydrostudy.data.hydrography import build_hydrography
from hydrostudy.data.manifest import load_manifest
from hydrostudy.data.water_quality import build_water_quality
from hydrostudy.data.wells import build_nearby_wells
from hydrostudy.districts.loader import load_district
from hydrostudy.districts.status import rule_status
from hydrostudy.geo.crs import LocalCRS
from hydrostudy.schema.loaders import load_intake, load_review
from hydrostudy.units import FT_PER_MILE


def _json_default(o):
    if is_dataclass(o):
        return asdict(o)
    if hasattr(o, "tolist"):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def dump_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=_json_default)


class Project:
    def __init__(self, project_dir: str | Path):
        self.dir = Path(project_dir).resolve()
        self.build_dir = self.dir / "build"
        self.intake = load_intake(self.dir / "intake.yaml")
        self.review = load_review(self.dir / "review.yaml")
        self.district = load_district(self.intake.district.id)
        self.manifest = load_manifest(self.dir, self.intake.data.manifest)
        # local CRS centered on the first proposed well
        pw = self.intake.proposed_wells[0]
        self.crs = LocalCRS(pw.lat, pw.lon)
        self.intake._local_xy = {w.id: tuple(map(float, self.crs.to_local(w.lon, w.lat))) for w in self.intake.all_wells}
        self.boundary_geom = None
        self.boundary_source = None
        bpath = None
        if self.intake.site.boundary_geojson and (self.dir / self.intake.site.boundary_geojson).exists():
            bpath = self.dir / self.intake.site.boundary_geojson
        elif self.manifest.get("boundary") is not None:
            bpath = self.manifest.get("boundary").path
        if bpath is not None:
            from hydrostudy.geo.geometry import load_boundary
            self.boundary_geom = load_boundary(bpath, self.crs)
            self.boundary_source = str(bpath)
        self.artifacts: dict = {}

    def build_boundaries(self) -> list:
        """Hydraulic boundaries from the intake, projected into the project's local feet."""
        from hydrostudy.analysis.boundaries import LineBoundary
        out = []
        for b in self.intake.analysis.boundaries:
            x1, y1 = self.crs.to_local(b.lon1, b.lat1)
            x2, y2 = self.crs.to_local(b.lon2, b.lat2)
            out.append(LineBoundary(b.kind, x1, y1, x2, y2, b.name, b.source, b.aquifer))
        return out

    # ---------------- stages ----------------
    def run_analysis(self) -> dict:
        intake, district, review = self.intake, self.district, self.review
        t0 = time.time()
        boundary_flags = []
        boundary_distances = {}
        for w in intake.all_wells:
            entry = {"ft": w.nearest_property_boundary_ft, "source": "intake" if w.nearest_property_boundary_ft is not None else None}
            if self.boundary_geom is not None:
                from shapely.geometry import Point

                from hydrostudy.geo.geometry import distance_to_boundary_ft
                d = distance_to_boundary_ft(*intake._local_xy[w.id], self.boundary_geom)
                # `covers` rather than `contains`, so a well surveyed exactly on the tract line still counts as on
                # the tract instead of losing its boundary distance.
                inside = self.boundary_geom.covers(Point(*intake._local_xy[w.id]))
                entry["polygon_ft"] = d
                entry["inside_boundary"] = bool(inside)
                if inside:
                    if w.nearest_property_boundary_ft is None:
                        w.nearest_property_boundary_ft = d
                        entry.update({"ft": d, "source": "boundary polygon"})
                    elif w.nearest_property_boundary_ft > 0 and abs(d - w.nearest_property_boundary_ft) / w.nearest_property_boundary_ft > 0.10:
                        boundary_flags.append({"level": "review", "code": "BOUNDARY_DISTANCE_MISMATCH",
                                               "text": f"{w.label}: intake boundary distance {w.nearest_property_boundary_ft:,.0f} ft differs from the "
                                                       f"property polygon distance {d:,.0f} ft by more than 10%; intake value used."})
                elif w.nearest_property_boundary_ft is None:
                    # The polygon is the applicant's tract. A well outside it (an existing system well on another
                    # parcel) is not that distance from its own property line, so the figure is not adopted; the
                    # 10% cross-check does not apply to it either, for the same reason.
                    boundary_flags.append({
                        "level": "warn", "code": "WELL_OUTSIDE_BOUNDARY",
                        "text": f"{w.label} lies outside the supplied property polygon ({d:,.0f} ft from its edge); "
                                "its distance to its own property line must be supplied in the intake."})
            boundary_distances[w.id] = entry
        from hydrostudy.data.gam import load_gam_lookup
        gam = load_gam_lookup(self.manifest)
        as_built = None
        if intake.mode == "lsgcd_post_drilling":
            from hydrostudy.analysis.asbuilt import analyze_as_built
            pre_params = resolve_params(intake, review, gam, apply_review=False)
            as_built = analyze_as_built(self, pre_params)
            # What the re-run actually uses, so the narrative can describe that rather than assuming the measured
            # value was applied. Empty when nothing was substituted at all.
            as_built["applied"] = {}
            if as_built["rerun_interference"] and as_built["adopted"]["t_ft2d"]:
                aq = as_built["aquifer"]
                # The measured value seeds the decision; an explicit reviewer decision still wins, because that is
                # what `decisions` is for. Merging the other way round silently dropped their number while the
                # report went on claiming a reviewer override had been applied.
                for field, value in (("t_ft2d", as_built["adopted"]["t_ft2d"]),
                                     ("s", as_built["adopted"]["s"] if
                                      as_built["adopted"]["s_source"] != "GAM (pre-drilling value)" else None)):
                    if value is None:
                        continue
                    current = dict(getattr(review.decisions, field) or {})
                    if aq in current:
                        as_built["applied"][field] = {"value": current[aq], "basis": "reviewer"}
                        boundary_flags.append({
                            "level": "review", "code": "ASBUILT_VALUE_NOT_ADOPTED",
                            "text": f"{aq}: the reviewer's {field} decision is used in place of the value measured at "
                                    f"well {as_built['well_id']}; the measured value is reported for comparison only."})
                        continue
                    setattr(review.decisions, field, {aq: value} | current)
                    as_built["applied"][field] = {"value": value, "basis": "measured"}
        aquifer_params = resolve_params(intake, review, gam)

        # search radius = max(1/2 mile, largest required spacing radius among proposed wells)
        spacing_radii = [district.required_spacing_ft(w.aquifer, w.max_rate_gpm) or 0 for w in intake.proposed_wells]
        spacing_radius_ft = max(spacing_radii) if spacing_radii else 0.0
        half_mile = float(district.get("search_radius", {}).get("half_mile_ft", 2640))
        search_radius_ft = max(half_mile, spacing_radius_ft)

        nearby = build_nearby_wells(intake, district, self.crs, self.manifest, search_radius_ft, spacing_radius_ft)
        rules_status = rule_status(district)
        spacing = spacing_analysis(intake, district, nearby, rules_status)
        wq = build_water_quality(self.manifest)
        site_xy = intake._local_xy[intake.proposed_wells[0].id]
        hydro = build_hydrography(self.manifest, self.crs, site_xy, float(district.get("surface_water_radius_mi", 1.0)))
        hydro_geoms = hydro.pop("_geoms")

        # One solution per aquifer and one set of boundaries for the whole project, resolved here so
        # the tables, the maps, the curves and the narrative cannot describe different calculations.
        solutions, solution_flags = {}, []
        for aq, prm in aquifer_params.items():
            solutions[aq], fl = resolve_solution(intake, aq, prm["t_ft2d"])
            solution_flags.extend(fl)
            note = leakage_reach_note(solutions[aq], search_radius_ft)
            if note:
                # 'review' rather than 'info': the CLI summary and the reviewer sheet both filter
                # info out, and "confirm this" that nobody sees is not a caveat, it is decoration.
                solution_flags.append({"level": "review", "code": "LEAKAGE_REACH", "text": f"{aq}: {note}"})
        boundaries = self.build_boundaries()
        if boundaries:
            from hydrostudy.analysis.boundaries import truncation_note, with_images
            probe = [PumpingWell(w.id, *intake._local_xy[w.id], w.max_rate_gpm, w.effective_r_w_ft(), w.aquifer)
                     for w in intake.proposed_wells]
            _, probe_images = with_images(probe, boundaries, intake.analysis.image_max_order)
            solution_flags.append({
                "level": "review", "code": "HYDRAULIC_BOUNDARIES",
                "text": truncation_note(boundaries, probe_images)})

        scen_defs = build_scenarios(intake, review, aquifer_params)
        scenarios = [run_scenario(sc, intake, review, aquifer_params, nearby, boundaries, solutions)
                     for sc in scen_defs]
        interference = {sc["key"]: system_interference_matrix(sc) for sc in scenarios if sc["group"] == "system"}
        pumping = pumping_level_checks(intake, scenarios)
        flags = collect_flags(intake, review, aquifer_params, spacing, scenarios, pumping, hydro, wq, district["id"])
        flags = solution_flags + flags
        if as_built:
            flags = as_built["flags"] + flags
        flags = boundary_flags + flags

        geo = {
            "crs_proj4": self.crs.proj4, "origin": {"lat": self.crs.lat0, "lon": self.crs.lon0},
            "wells_xy": intake._local_xy,
            "search_radius_ft": search_radius_ft, "spacing_radius_ft": spacing_radius_ft,
            "half_mile_ft": half_mile, "map_radius_ft": float(district.get("wells_map_radius_mi", 1.0)) * FT_PER_MILE,
            "boundary_source": self.boundary_source, "boundary_distances": boundary_distances,
            "hydraulic_boundaries": [{"kind": b.kind, "name": b.label, "source": b.source,
                                      "aquifer": b.aquifer,
                                      "x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2}
                                     for b in boundaries],
        }
        provenance = {
            "hydrostudy_version": __version__, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "project_dir": str(self.dir), "intake": "intake.yaml", "review": "review.yaml",
            "district_rules": {"id": district["id"], "version": district["rules"].get("version"),
                               "verified_on": district["rules"].get("verified_on"),
                               "verified_by": district["rules"].get("verified_by"),
                               "source": rules_status["source"],
                               "spacing_source": rules_status["spacing_source"],
                               "spacing_verified_on": rules_status["spacing_verified_on"],
                               "attested_by": rules_status["attested_by"],
                               "attested_on": rules_status["attested_on"],
                               "stale": rules_status["stale"]},
            "files": [f.provenance() for f in self.manifest.files.values()],
            "tceq_limits": {"version": wq["limits_version"], "verify_on": wq["limits_verify_on"]},
        }
        analysis = {
            "aquifer_params": aquifer_params, "scenarios": scenarios, "system_interference": interference,
            "solutions": {aq: sol.to_json() for aq, sol in solutions.items()},
            "pumping_levels": pumping, "spacing": spacing,
            "wells": [{"id": w.id, "kind": "proposed" if w in intake.proposed_wells else "existing",
                       "aquifer": w.aquifer, "q_gpm": w.max_rate_gpm, "r_w_ft": w.effective_r_w_ft(),
                       "x_ft": intake._local_xy[w.id][0], "y_ft": intake._local_xy[w.id][1],
                       "lat": w.lat, "lon": w.lon,
                       "in_system": True if w in intake.proposed_wells else w.include_in_system} for w in intake.all_wells],
            "elapsed_s": time.time() - t0,
        }
        self.artifacts = {"geo": geo, "nearby_wells": nearby, "water_quality": wq, "hydrography": hydro,
                          "analysis": analysis, "flags": flags, "provenance": provenance,
                          "_hydro_geoms": hydro_geoms}
        if as_built:
            self.artifacts["as_built"] = as_built
        self.artifacts["gam"] = gam
        for k, v in self.artifacts.items():
            if k.startswith("_"):
                continue
            if k == "water_quality":
                v = {kk: vv for kk, vv in v.items() if kk != "limits"} | {"limits": v["limits"]}
            dump_json(v, self.build_dir / f"{k}.json")
        return self.artifacts

    def run_figures(self):
        from hydrostudy.figures import render_all, render_all_post
        self.artifacts["figures"] = render_all_post(self) if self.intake.mode == "lsgcd_post_drilling" else render_all(self)
        dump_json(self.artifacts["figures"], self.build_dir / "figures.json")
        return self.artifacts["figures"]

    def run_report(self, pdf: bool = True, strict_lint: bool = True):
        if self.intake.mode == "lsgcd_post_drilling":
            from hydrostudy.report.assemble_post import build_post_report as build_report
        else:
            from hydrostudy.report.assemble import build_report
        result = build_report(self, pdf=pdf, strict_lint=strict_lint)
        dump_json(result, self.build_dir / "report.json")
        return result

    def run_checklist(self):
        from hydrostudy.qa.checklist import build_checklist
        cl = build_checklist(self)
        dump_json(cl, self.build_dir / "checklist.json")
        return cl

    def run_all(self, pdf: bool = True):
        self.run_analysis()
        self.run_figures()
        self.run_checklist()
        return self.run_report(pdf=pdf)
