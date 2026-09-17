"""Siting search: the envelope it draws must be the envelope the compliance analysis accepts.

The end-to-end test is the one that matters: take the location the search ranks first, put it in the
intake, re-run the project, and require `spacing_analysis` to report no conflict. Everything else here
checks a single constraint in isolation.
"""

import math
import shutil

import pytest
import yaml

from hydrostudy.analysis.siting import SitingNotPossible, SitingRequest, analyze_siting
from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.pipeline import Project
from tests.conftest import ROOT
from tests.geo_fixtures import write_tract

SITE_LAT, SITE_LON = 30.170167, -95.578097


def _project(tmp_path, half_x_ft=1000.0, half_y_ft=700.0, **intake_edits):
    dst = tmp_path / "siting"
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    rel = write_tract(dst, SITE_LAT, SITE_LON, half_x_ft, half_y_ft)
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    intake["site"]["boundary_geojson"] = rel
    intake["site"]["nearest_boundary_distance_ft"] = None
    intake["proposed_wells"][0]["nearest_property_boundary_ft"] = None
    for k, v in intake_edits.items():
        intake[k] = v
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()
    return p


@pytest.fixture(scope="module")
def sited(tmp_path_factory):
    p = _project(tmp_path_factory.mktemp("s1"))
    return p, analyze_siting(p, SitingRequest(grid_spacing_ft=100.0))


def test_the_spacing_rate_at_a_point_is_the_distance_to_the_nearest_counting_well_over_the_multiplier(sited):
    p, out = sited
    counting = {n["map_id"] for n in out["counting_wells"]}
    assert counting, "the example carries wells that constrain spacing"
    for c in out["best"]:
        d = min(math.hypot(c["x_ft"] - n["x_ft"], c["y_ft"] - n["y_ft"])
                for n in p.artifacts["nearby_wells"] if n["map_id"] in counting)
        assert c["nearest_counting_well"]["distance_ft"] == pytest.approx(d, rel=1e-9)
        assert c["max_rate_spacing_gpm"] == pytest.approx(d / out["ft_per_gpm"], rel=1e-9)


def test_the_applicants_own_wells_and_plugged_wells_do_not_limit_the_rate(sited):
    p, out = sited
    counted = {n["map_id"] for n in out["counting_wells"]}
    for n in p.artifacts["nearby_wells"]:
        if n["is_system_well"]:
            assert n["map_id"] not in counted, "the applicant's own well is flagged, never a spacing conflict"
        if n["status"].lower() == "plugged":
            assert n["map_id"] not in counted, "a plugged well is not a well the District protects"
    assert any(n["status"].lower() == "plugged" for n in p.artifacts["nearby_wells"]), "fixture covers this case"
    assert any(n["is_system_well"] for n in p.artifacts["nearby_wells"]), "fixture covers this case"


def test_the_top_ranked_location_actually_passes_the_spacing_compliance_analysis(tmp_path):
    """The whole point of the search. A location it ranks must survive `spacing_analysis` unchanged."""
    p = _project(tmp_path)
    out = analyze_siting(p, SitingRequest(grid_spacing_ft=100.0))
    assert out["feasible"]
    best = out["best"][0]

    moved = tmp_path / "moved"
    shutil.copytree(p.dir, moved, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((moved / "intake.yaml").read_text())
    intake["proposed_wells"][0]["lat"] = best["lat"]
    intake["proposed_wells"][0]["lon"] = best["lon"]
    (moved / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))

    q = Project(moved)
    q.run_analysis()
    rec = q.artifacts["analysis"]["spacing"]["wells"][0]
    assert rec["conflicts"] == []
    assert rec["complies"]
    assert rec["required_spacing_ft"] == pytest.approx(out["required_spacing_ft"])


def test_a_rate_no_location_can_support_is_reported_as_infeasible_with_the_best_available(tmp_path):
    p = _project(tmp_path)
    reachable = analyze_siting(p, SitingRequest(grid_spacing_ft=100.0))["best_by_headroom"]["max_rate_gpm"]
    out = analyze_siting(p, SitingRequest(target_rate_gpm=reachable * 2, grid_spacing_ft=100.0))
    assert not out["feasible"]
    assert out["grid"]["compliant"] == 0
    assert out["best_by_headroom"]["max_rate_gpm"] == pytest.approx(reachable)
    assert not out["best_by_headroom"]["meets_target"]


def test_an_interference_cap_produces_exactly_that_drawdown_at_the_binding_well(tmp_path):
    """The rate and the duration are solved together; recompute the drawdown forwards to check.

    Inverting the budget at the duration the *target* rate implies gives a rate that is too high, because
    a lower rate pumps for longer to make the same annual volume and so draws down further. The forward
    check below is at the candidate's own duration, which is what catches that.
    """
    p = _project(tmp_path)
    # The existing system well already imposes most of the drawdown at the neighbours, so a credible cap
    # sits just below what the target rate produces: enough to bite, not enough to forbid pumping.
    uncapped = analyze_siting(p, SitingRequest(grid_spacing_ft=200.0))
    cap = uncapped["best"][0]["worst_neighbour"]["drawdown_at_target_ft"] - 2.0
    out = analyze_siting(p, SitingRequest(grid_spacing_ft=200.0, max_interference_ft=cap))
    assert "interference" in out["constraints_applied"]
    c = out["best_by_headroom"]
    assert c["binding_constraint"] == "interference" and c["max_rate_gpm"] > 0
    # The candidate's own duration, which is longer than the target-rate duration whenever its rate is lower.
    t = c["days_at_max_rate"]
    assert t > out["duration_days"]
    T, S = out["t_ft2d"], out["s"]
    xy = p.intake._local_xy
    fixed = [(xy[w["id"]], w["q_gpm"]) for w in out["fixed_system_wells"] if w["aquifer"] == out["aquifer"]]
    ranked_on = {n["map_id"] for n in out["counting_wells"] if n["aquifer"] in (out["aquifer"], None)}

    worst = 0.0
    for n in p.artifacts["nearby_wells"]:
        if n["map_id"] not in ranked_on:
            continue
        total = float(theis_drawdown(c["max_rate_gpm"], T, S,
                                     max(math.hypot(c["x_ft"] - n["x_ft"], c["y_ft"] - n["y_ft"]), out["r_w_ft"]), t))
        for (fx, fy), q_gpm in fixed:
            total += float(theis_drawdown(q_gpm, T, S, max(math.hypot(fx - n["x_ft"], fy - n["y_ft"]), 0.5), t))
        worst = max(worst, total)
    # A solved cap sits on the budget, not merely under it, and the tool's own reported figure agrees.
    assert worst == pytest.approx(cap, abs=0.05)
    assert c["max_neighbour_drawdown_at_max_rate_ft"] == pytest.approx(worst, rel=1e-6)


def test_an_available_drawdown_budget_limits_the_rate_at_the_well_itself(tmp_path):
    """A location the pump cannot lift from is not a location, however well it spaces."""
    p = _project(tmp_path)
    budget = 40.0
    out = analyze_siting(p, SitingRequest(grid_spacing_ft=200.0, available_drawdown_ft=budget))
    assert "available drawdown" in out["constraints_applied"]
    c = out["best_by_headroom"]
    assert c["binding_constraint"] == "available drawdown", "40 ft is less than this well needs at 385 gpm"
    # The drawdown at the rate the location supports respects the budget; at the target rate it does not,
    # and both numbers are reported so the second cannot be mistaken for the first.
    assert c["self_drawdown_at_max_rate_ft"] == pytest.approx(budget, abs=0.05)
    assert c["self_drawdown_at_target_ft"] > budget
    assert not out["feasible"]

    # Forward check at the candidate's own rate and duration, independent of the tool's arithmetic.
    T, S = out["t_ft2d"], out["s"]
    xy = p.intake._local_xy
    fixed = [(xy[w["id"]], w["q_gpm"]) for w in out["fixed_system_wells"] if w["aquifer"] == out["aquifer"]]
    total = float(theis_drawdown(c["max_rate_gpm"], T, S, out["r_w_ft"], c["days_at_max_rate"]))
    for (fx, fy), q_gpm in fixed:
        total += float(theis_drawdown(q_gpm, T, S, max(math.hypot(fx - c["x_ft"], fy - c["y_ft"]), 0.5),
                                      c["days_at_max_rate"]))
    assert total == pytest.approx(budget, abs=0.05)

    # And the whole reason the rate and the duration are solved together: inverting the budget at the
    # duration the target rate implies returns a rate that overdraws once it is actually pumped.
    naive = budget / float(theis_drawdown(1.0, T, S, out["r_w_ft"], out["duration_days"]))
    assert naive > c["max_rate_gpm"]
    naive_days = p.intake.permit.annual_volume_gal / ((naive + sum(q for _, q in fixed)) * 1440)
    assert float(theis_drawdown(naive, T, S, out["r_w_ft"], naive_days)) > budget


def test_candidates_are_ranked_by_the_impact_they_put_on_someone_elses_well(sited):
    _, out = sited
    impacts = [c["worst_neighbour"]["drawdown_at_target_ft"] for c in out["best"]]
    assert impacts == sorted(impacts)
    assert all(c["meets_target"] for c in out["best"])
    for c in out["best"]:
        # The share already there before the new well starts is called out, and cannot be the whole of it.
        assert 0 < c["worst_neighbour"]["drawdown_from_fixed_wells_ft"] < c["worst_neighbour"]["drawdown_at_target_ft"]


def test_the_worst_neighbour_reported_is_the_worst_one(sited):
    """The ranking is only meaningful if the number it ranks on is the real maximum over the set."""
    p, out = sited
    ranked_on = {n["map_id"] for n in out["counting_wells"] if n["aquifer"] in (out["aquifer"], None)}
    T, S, t, r_w = out["t_ft2d"], out["s"], out["duration_days"], out["r_w_ft"]
    fixed = [(p.intake._local_xy[w["id"]], w["q_gpm"])
             for w in out["fixed_system_wells"] if w["aquifer"] == out["aquifer"]]
    for c in out["best"]:
        worst_id, worst_ft = None, -1.0
        for n in p.artifacts["nearby_wells"]:
            if n["map_id"] not in ranked_on:
                continue
            total = float(theis_drawdown(out["target_rate_gpm"], T, S,
                                         max(math.hypot(c["x_ft"] - n["x_ft"], c["y_ft"] - n["y_ft"]), r_w), t))
            for (fx, fy), q_gpm in fixed:
                total += float(theis_drawdown(q_gpm, T, S, max(math.hypot(fx - n["x_ft"], fy - n["y_ft"]), 0.5), t))
            if total > worst_ft:
                worst_id, worst_ft = n["map_id"], total
        assert c["worst_neighbour"]["map_id"] == worst_id
        assert c["worst_neighbour"]["drawdown_at_target_ft"] == pytest.approx(worst_ft, rel=1e-9)


def test_ranked_locations_are_distinct_places_and_not_one_cluster(sited):
    _, out = sited
    sep = out["min_separation_ft"]
    assert sep > 0
    pts = [(c["x_ft"], c["y_ft"]) for c in out["best"]]
    assert len(pts) > 1, "the example tract has room for more than one option"
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert math.hypot(a[0] - b[0], a[1] - b[1]) >= sep - 1e-6


def test_a_setback_keeps_every_candidate_off_the_property_line(tmp_path):
    p = _project(tmp_path)
    out = analyze_siting(p, SitingRequest(grid_spacing_ft=100.0, setback_ft=250.0))
    for c in out["best"] + [out["best_by_headroom"]]:
        assert c["boundary_distance_ft"] >= 250.0 - 1e-6
    assert any("setback" in n for n in out["notes"])


def test_a_setback_wider_than_the_tract_is_refused_rather_than_returning_nothing(tmp_path):
    p = _project(tmp_path, half_x_ft=300.0, half_y_ft=300.0)
    with pytest.raises(SitingNotPossible, match="too narrow"):
        analyze_siting(p, SitingRequest(grid_spacing_ft=50.0, setback_ft=400.0))


def test_siting_without_a_tract_says_what_to_supply(black_oak_project):
    with pytest.raises(SitingNotPossible, match="boundary_geojson"):
        analyze_siting(black_oak_project, SitingRequest())


def test_the_envelope_shrinks_as_the_rate_rises(tmp_path):
    """The spacing radius is proportional to the rate, so more gpm can only ever mean fewer legal points."""
    p = _project(tmp_path)
    areas = [analyze_siting(p, SitingRequest(target_rate_gpm=q, grid_spacing_ft=100.0))["grid"]["compliant_area_acres"]
             for q in (200, 300, 385, 450)]
    assert areas == sorted(areas, reverse=True)
    assert areas[0] > areas[-1], "the example has to show a real trade-off or this test proves nothing"


def test_the_figure_renders(tmp_path):
    from hydrostudy.figures import siting_map
    p = _project(tmp_path)
    out = analyze_siting(p, SitingRequest(grid_spacing_ft=150.0))
    d = p.build_dir / "figures"
    d.mkdir(parents=True, exist_ok=True)
    fig = siting_map.render(p, out, d / "fig_siting.png")
    assert fig["path"].endswith(".png")
    assert f"{out['target_rate_gpm']:,.0f} gpm" in fig["caption"]


def test_an_envelope_built_on_a_multiplier_nobody_read_says_so(tmp_path):
    """The spacing conclusion is qualified when the multiplier is not authoritative; so is the envelope.

    LSGCD spacing is currently operator_attested, which is authoritative, so the unqualified case is
    the live one and the qualifier has to be provoked.
    """
    p = _project(tmp_path)
    firm = analyze_siting(p, SitingRequest(grid_spacing_ft=200.0))
    assert not firm["provisional"] and not any("provisional" in n for n in firm["notes"])

    p.district["spacing"]["source"] = "derived"
    out = analyze_siting(p, SitingRequest(grid_spacing_ft=200.0))
    assert out["provisional"]
    assert any("provisional" in n for n in out["notes"])

    from hydrostudy.figures import siting_map
    d = p.build_dir / "figures"
    d.mkdir(parents=True, exist_ok=True)
    assert "provisional" in siting_map.render(p, out, d / "fig_siting_prov.png")["caption"]
