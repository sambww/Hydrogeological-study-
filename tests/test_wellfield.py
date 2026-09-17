"""Well-field design: the field it lays out must be a field the compliance analysis accepts.

The end-to-end test is the one that matters, as with siting: take the designed field, write every well
into the intake at its designed rate, re-run the project, and require `spacing_analysis` to report no
conflict and the reported drawdown to match what the designer promised.
"""

import copy
import math
import shutil

import pytest
import yaml

from hydrostudy.analysis.wellfield import FieldNotPossible, FieldRequest, design_field
from hydrostudy.pipeline import Project
from tests.conftest import ROOT
from tests.geo_fixtures import write_tract

SITE_LAT, SITE_LON = 30.170167, -95.578097


def _project(tmp_path, name="field", half_x_ft=1600.0, half_y_ft=1200.0, **edits):
    dst = tmp_path / name
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    rel = write_tract(dst, SITE_LAT, SITE_LON, half_x_ft, half_y_ft)
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    intake["site"]["boundary_geojson"] = rel
    intake["site"]["nearest_boundary_distance_ft"] = None
    intake["proposed_wells"][0]["nearest_property_boundary_ft"] = None
    for dotted, value in edits.items():
        node = intake
        parts = dotted.split(".")
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()
    return p


def _design(project, **kw):
    kw.setdefault("target_rate_gpm", 700.0)
    kw.setdefault("max_wells", 4)
    kw.setdefault("grid_spacing_ft", 300.0)
    kw.setdefault("setback_ft", 50.0)
    return design_field(project, FieldRequest(**kw))


@pytest.fixture(scope="module")
def designed(tmp_path_factory):
    p = _project(tmp_path_factory.mktemp("wf"))
    return p, _design(p, available_drawdown_ft=150.0, min_well_spacing_ft=400.0)


# --------------------------------------------------------------------------------------------------
# The end-to-end guarantee
# --------------------------------------------------------------------------------------------------

def test_the_designed_field_passes_the_spacing_analysis_and_matches_its_own_drawdown(tmp_path):
    """Write the field into the intake, re-run the pipeline, and hold the designer to its numbers."""
    p = _project(tmp_path)
    out = _design(p, available_drawdown_ft=150.0, min_well_spacing_ft=400.0)
    assert out["feasible"]
    rec = out["recommended"]
    assert rec["wells_drilled"] >= 2, "a 150-ft pump budget cannot make 700 gpm from one well here"

    built = tmp_path / "built"
    shutil.copytree(p.dir, built, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((built / "intake.yaml").read_text())
    template = intake["proposed_wells"][0]
    wells = []
    for w in rec["wells"]:
        new = copy.deepcopy(template)
        new["id"] = f"N{w['slot']}"
        new["display_name"] = f"New Well {w['slot']}"
        new["lat"], new["lon"] = w["lat"], w["lon"]
        new["max_rate_gpm"] = w["rate_gpm"]
        new["nearest_property_boundary_ft"] = None
        wells.append(new)
    intake["proposed_wells"] = wells
    (built / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))

    q = Project(built)
    q.run_analysis()

    # 1. Every well complies with spacing, using the pipeline's own test, not the designer's.
    for rec_w in q.artifacts["analysis"]["spacing"]["wells"]:
        assert rec_w["conflicts"] == [], rec_w["well_id"]
        assert rec_w["complies"]

    # 2. The system delivers the demand.
    assert q.intake.system_rate_gpm == pytest.approx(
        rec["total_rate_gpm"] + out["existing_system_rate_gpm"], rel=1e-6)

    # 3. The drawdown the pipeline reports for the whole system matches what the designer predicted.
    sysc = [s for s in q.artifacts["analysis"]["scenarios"]
            if s["group"] == "system" and s["duration_kind"] == "max_production"]
    assert sysc, "a multi-well system produces a system scenario"
    res = sysc[0]["results_by_aquifer"]["Evangeline"]
    by_id = {pw["id"]: pw["total_ft"] for pw in res["pumped_wells"]}
    for w in rec["wells"]:
        assert by_id[f"N{w['slot']}"] == pytest.approx(w["drawdown_ft"], rel=0.02), (
            "the designer's drawdown must be the pipeline's drawdown")


# --------------------------------------------------------------------------------------------------
# The linear program
# --------------------------------------------------------------------------------------------------

def test_the_binding_constraint_is_saturated_exactly(designed):
    """An optimal rate split sits *on* its binding constraint. Under it means rate was left unused."""
    _, out = designed
    budget = out["available_drawdown_ft"]
    deepest = max(w["drawdown_ft"] for w in out["recommended"]["wells"])
    assert deepest == pytest.approx(budget, rel=0.02), "some well should be pumping right to the budget"
    for w in out["recommended"]["wells"]:
        assert w["drawdown_ft"] <= budget * 1.02


def test_no_well_exceeds_its_own_spacing_cap(designed):
    from hydrostudy.analysis.spacing import SPACING_ROUNDTRIP_FT
    p, out = designed
    for w in out["recommended"]["wells"]:
        assert w["rate_gpm"] <= w["spacing_cap_gpm"] + 1e-6
        # The cap stays strictly inside the distance to the nearest counting well, because the compliance
        # test counts a well at exactly the required radius as a conflict.
        assert w["spacing_cap_gpm"] == pytest.approx(
            (w["nearest_counting_well"]["distance_ft"] - SPACING_ROUNDTRIP_FT) / out["ft_per_gpm"], rel=1e-9)
        assert w["required_spacing_ft"] < w["nearest_counting_well"]["distance_ft"]


def test_the_field_never_produces_more_than_the_demand(designed):
    _, out = designed
    assert out["recommended"]["total_rate_gpm"] <= out["target_rate_gpm"] + 0.05
    assert out["recommended"]["shortfall_gpm"] == pytest.approx(0.0, abs=0.05)


def test_a_tighter_pump_budget_needs_more_wells(tmp_path):
    """The trade-off the tool exists to quantify: less available drawdown means more, smaller wells."""
    p = _project(tmp_path)
    counts = []
    for budget in (250.0, 150.0, 110.0):
        out = _design(p, max_wells=5, available_drawdown_ft=budget, min_well_spacing_ft=400.0)
        assert out["feasible"], budget
        counts.append(out["recommended"]["wells_drilled"])
    assert counts == sorted(counts), f"wells needed should not fall as the pump budget tightens: {counts}"
    assert counts[0] < counts[-1], "the example has to show a real trade-off or this proves nothing"


def test_a_per_well_rate_ceiling_is_respected(tmp_path):
    p = _project(tmp_path)
    out = _design(p, max_wells=5, max_well_rate_gpm=250.0, available_drawdown_ft=250.0)
    for w in out["recommended"]["wells"]:
        assert w["rate_gpm"] <= 250.0 + 1e-6
    assert out["recommended"]["wells_drilled"] >= 3, "700 gpm at 250 gpm a well needs at least three"


def test_a_well_below_the_minimum_rate_is_not_drilled(tmp_path):
    """A 20-gpm well is a hole in the ground, not a water well. The LP may shut it off instead."""
    p = _project(tmp_path)
    out = _design(p, max_wells=5, min_well_rate_gpm=200.0, available_drawdown_ft=150.0)
    for w in out["recommended"]["wells"]:
        assert w["rate_gpm"] >= 200.0 - 1e-6 or w["rate_gpm"] == 0.0
    assert all(w["rate_gpm"] > 0 for w in out["recommended"]["wells"]), "zero-rate wells are not reported"


# --------------------------------------------------------------------------------------------------
# Layout constraints
# --------------------------------------------------------------------------------------------------

def test_the_operators_well_to_well_spacing_is_honoured_and_labelled_a_preference(designed):
    _, out = designed
    sep = out["min_well_spacing_ft"]
    pts = [(w["x_ft"], w["y_ft"]) for w in out["recommended"]["wells"]]
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert math.hypot(a[0] - b[0], a[1] - b[1]) >= sep - 1e-6
    assert any("operator's choice and not a requirement" in n for n in out["notes"])


def test_without_a_well_spacing_preference_the_note_says_what_that_means(tmp_path):
    p = _project(tmp_path)
    out = _design(p, available_drawdown_ft=150.0)
    assert out["min_well_spacing_ft"] is None
    assert any("--min-well-spacing-ft" in n for n in out["notes"])


def test_every_well_respects_the_setback(designed):
    _, out = designed
    for w in out["recommended"]["wells"]:
        assert w["boundary_distance_ft"] >= out["setback_ft"] - 1e-6


# --------------------------------------------------------------------------------------------------
# When the demand cannot be met
# --------------------------------------------------------------------------------------------------

def test_an_impossible_demand_reports_the_best_effort_and_the_shortfall(tmp_path):
    """"You cannot get 700 gpm off this tract" is an answer, and it comes with the number that can."""
    p = _project(tmp_path)
    out = _design(p, max_wells=5, available_drawdown_ft=250.0, max_interference_ft=45.0)
    assert not out["feasible"]
    rec = out["recommended"]
    assert 0 < rec["total_rate_gpm"] < 700.0
    assert rec["shortfall_gpm"] == pytest.approx(700.0 - rec["total_rate_gpm"], rel=1e-9)
    assert not rec["meets_target"]
    # Every option pinned exactly on the neighbour cap: that is the constraint that bound it.
    for o in out["options"]:
        assert o["worst_neighbour"]["drawdown_ft"] <= 45.0 + 1e-3


def test_more_wells_are_not_searched_once_another_one_buys_nothing(tmp_path):
    """When a neighbour's drawdown binds, spreading the demand over more wells barely moves it, and
    re-searching five well counts to learn that is wasted time."""
    p = _project(tmp_path)
    out = _design(p, max_wells=5, available_drawdown_ft=250.0, max_interference_ft=45.0)
    assert len(out["options"]) < 5
    rates = [o["total_rate_gpm"] for o in out["options"]]
    assert rates[-1] <= max(rates) + 1e-9


def test_the_recommendation_is_the_fewest_wells_that_meet_the_demand(tmp_path):
    p = _project(tmp_path)
    out = _design(p, max_wells=5, available_drawdown_ft=150.0, min_well_spacing_ft=400.0)
    assert out["feasible"]
    met = [o for o in out["options"] if o["meets_target"]]
    assert out["recommended"]["wells_drilled"] == met[0]["wells_drilled"]
    for o in out["options"]:
        if o is met[0]:
            break
        assert not o["meets_target"], "a cheaper field that met the demand should have been recommended"


# --------------------------------------------------------------------------------------------------
# Honesty
# --------------------------------------------------------------------------------------------------

def test_no_cost_is_reported_without_the_operators_own_costs(tmp_path):
    p = _project(tmp_path)
    out = _design(p, available_drawdown_ft=150.0)
    assert out["recommended"]["estimated_cost"] is None
    assert any("does not supply them" in n for n in out["notes"])

    priced = _design(p, available_drawdown_ft=150.0, cost_per_well=25_000.0, cost_per_ft=45.0,
                     well_depth_ft=700.0)
    n = priced["recommended"]["wells_drilled"]
    assert priced["recommended"]["estimated_cost"] == pytest.approx(n * (25_000.0 + 45.0 * 700.0))


def test_the_search_says_it_is_not_provably_optimal(designed):
    _, out = designed
    assert any("not a provably optimal one" in n for n in out["notes"])


def test_the_field_uses_the_projects_own_solution(tmp_path):
    aq = yaml.safe_load((ROOT / "examples" / "black_oak_well_2" / "intake.yaml").read_text())["aquifers"]
    aq[0]["confinement"] = {"status": "semi-confined", "thickness_ft": 100.0,
                            "leakance_per_day": 1e-4, "leakance_source": "test fixture"}
    p = _project(tmp_path, name="leaky", **{"analysis.solution": "hantush", "aquifers": aq})
    out = _design(p, available_drawdown_ft=150.0)
    assert out["solution"]["kind"] == "hantush"
    assert any("Hantush-Jacob" in n for n in out["notes"])


def test_the_designer_refuses_a_project_with_hydraulic_boundaries(tmp_path):
    from hydrostudy.geo.crs import LocalCRS
    crs = LocalCRS(SITE_LAT, SITE_LON)
    lon1, lat1 = crs.to_wgs84(1500.0, -9000.0)
    lon2, lat2 = crs.to_wgs84(1500.0, 9000.0)
    p = _project(tmp_path, name="bounded", **{"analysis.boundaries": [
        {"kind": "barrier", "name": "Conroe fault", "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2}]})
    with pytest.raises(FieldNotPossible, match="does not yet model"):
        _design(p, available_drawdown_ft=150.0)


def test_a_project_with_no_tract_says_what_to_supply(black_oak_project):
    with pytest.raises(FieldNotPossible, match="boundary_geojson"):
        design_field(black_oak_project, FieldRequest(target_rate_gpm=700.0))


def test_impossible_requests_are_refused(tmp_path):
    p = _project(tmp_path)
    for kw, match in [({"target_rate_gpm": 0.0}, "must be positive"),
                      ({"target_rate_gpm": 700.0, "max_wells": 0}, "max-wells"),
                      ({"target_rate_gpm": 700.0, "grid_spacing_ft": 1.0}, "grid-ft")]:
        with pytest.raises(FieldNotPossible, match=match):
            design_field(p, FieldRequest(**kw))


def test_the_provisional_qualifier_follows_the_spacing_source(tmp_path):
    p = _project(tmp_path)
    firm = _design(p, available_drawdown_ft=150.0)
    assert not firm["provisional"] and not any("provisional" in n for n in firm["notes"])
    p.district["spacing"]["source"] = "derived"
    out = _design(p, available_drawdown_ft=150.0)
    assert out["provisional"] and any("provisional" in n for n in out["notes"])


def test_a_spacing_safety_margin_is_respected_and_reported(tmp_path):
    """The optimum sits on the constraint, so without a margin the design has none. That is reportable."""
    p = _project(tmp_path)
    tight = _design(p, available_drawdown_ft=150.0, min_well_spacing_ft=400.0)
    # No safety distance: at least one well is designed hard against its spacing limit.
    assert min(w["spacing_margin_ft"] for w in tight["recommended"]["wells"]) < 50.0
    assert any("no margin can" in n for n in tight["notes"])

    safe = _design(p, available_drawdown_ft=150.0, min_well_spacing_ft=400.0, spacing_safety_ft=100.0)
    for w in safe["recommended"]["wells"]:
        assert w["spacing_margin_ft"] >= 100.0 - 1e-6
        assert w["rate_gpm"] <= w["spacing_cap_gpm"] + 1e-6
    assert safe["spacing_safety_ft"] == 100.0
    # And the margin is real: measured against the pipeline's own distances, not the designer's.
    assert not any("no margin can" in n for n in safe["notes"])


def test_the_margin_is_the_distance_left_over_after_the_rate_claims_its_radius(designed):
    _, out = designed
    for w in out["recommended"]["wells"]:
        expected = w["nearest_counting_well"]["distance_ft"] - w["rate_gpm"] * out["ft_per_gpm"]
        assert w["spacing_margin_ft"] == pytest.approx(expected, rel=1e-9)


def test_a_field_designed_hard_against_the_spacing_limit_still_complies(tmp_path):
    """The defect this guards: a cap computed to the last float produces `required == distance`, and the
    compliance test counts that as a conflict. An unreachable demand pushes every well onto its limit,
    which is exactly the case that used to fail."""
    p = _project(tmp_path)
    out = _design(p, target_rate_gpm=5000.0, max_wells=2, min_well_spacing_ft=400.0)
    rec = out["recommended"]
    assert not rec["meets_target"], "5,000 gpm is far beyond this tract; every well should be maxed out"
    for w in rec["wells"]:
        assert w["spacing_margin_ft"] > 0.0, "a design with zero margin does not comply"

    built = tmp_path / "maxed"
    shutil.copytree(p.dir, built, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((built / "intake.yaml").read_text())
    template = intake["proposed_wells"][0]
    new = []
    for w in rec["wells"]:
        row = copy.deepcopy(template)
        row["id"] = f"M{w['slot']}"
        row["lat"], row["lon"], row["max_rate_gpm"] = w["lat"], w["lon"], w["rate_gpm"]
        row["nearest_property_boundary_ft"] = None
        new.append(row)
    intake["proposed_wells"] = new
    (built / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    q = Project(built)
    q.run_analysis()
    for rec_w in q.artifacts["analysis"]["spacing"]["wells"]:
        assert rec_w["conflicts"] == [], f"{rec_w['well_id']} conflicts after a round trip through lat/lon"
        assert rec_w["complies"]


def test_the_worst_neighbours_drawdown_separates_the_new_field_from_the_existing_system(designed):
    """On a system with a well already pumping, most of the impact is there before the new field starts."""
    _, out = designed
    nb = out["recommended"]["worst_neighbour"]
    assert nb["drawdown_from_fixed_wells_ft"] > 0, "the example has an existing system well"
    assert nb["drawdown_from_new_wells_ft"] > 0
    assert (nb["drawdown_from_fixed_wells_ft"] + nb["drawdown_from_new_wells_ft"]
            == pytest.approx(nb["drawdown_ft"], rel=1e-9))
    assert any("is the existing system" in n for n in out["notes"])


def test_a_reviewers_evaluation_radius_governs_the_design(tmp_path):
    """The designed drawdown has to be the reported drawdown, and `r_w` moves it a lot."""
    p = _project(tmp_path)
    base = _design(p, available_drawdown_ft=250.0, max_wells=2)
    review = yaml.safe_load((p.dir / "review.yaml").read_text()) or {}
    review.setdefault("decisions", {})["r_w_ft"] = {"W2": 4.0}
    (p.dir / "review.yaml").write_text(yaml.safe_dump(review, sort_keys=False))
    q = Project(p.dir)
    q.run_analysis()
    wide = _design(q, available_drawdown_ft=250.0, max_wells=2)
    assert wide["r_w_ft"] == 4.0
    # A wider evaluation radius means less drawdown at the well for the same rate.
    assert wide["recommended"]["max_well_drawdown_ft"] < base["recommended"]["max_well_drawdown_ft"]


def test_a_demand_below_the_per_well_minimum_is_refused_with_the_reason(tmp_path):
    p = _project(tmp_path)
    with pytest.raises(FieldNotPossible, match="below the minimum rate"):
        _design(p, target_rate_gpm=30.0, min_well_rate_gpm=50.0)


def test_an_aquifer_the_intake_does_not_define_is_refused_clearly(tmp_path):
    p = _project(tmp_path)
    with pytest.raises(FieldNotPossible, match="defines no aquifer"):
        _design(p, aquifer="Jasper")


def test_an_explicit_zero_setback_is_not_read_as_unset(tmp_path):
    p = _project(tmp_path)
    out = _design(p, setback_ft=0.0, available_drawdown_ft=250.0)
    assert out["setback_ft"] == 0.0
    assert out["setback_basis"] == "supplied on the command line"


def test_the_trade_off_table_has_no_duplicate_rows(tmp_path):
    """A row per well count is only worth printing if that well count changes the answer."""
    p = _project(tmp_path)
    out = _design(p, max_wells=5, available_drawdown_ft=250.0, max_interference_ft=45.0)
    seen = [(o["wells_drilled"], round(o["total_rate_gpm"], 1)) for o in out["options"]]
    assert len(seen) == len(set(seen)), f"the same field is reported more than once: {seen}"
    rates = [o["total_rate_gpm"] for o in out["options"]]
    assert rates == sorted(rates), "each extra well must deliver more than the last or not be listed"
