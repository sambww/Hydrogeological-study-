"""The solution the pipeline ran must be the solution every part of the report describes.

The failure this guards against is not a wrong number, it is a *mislabelled* one: tables computed with
one solution and a methodology section naming another, or a leaky projection built on a leakance nobody
supplied. Those survive review precisely because the numbers look reasonable.
"""

import shutil

import pytest
import yaml

from hydrostudy.pipeline import Project
from tests.conftest import ROOT

SITE_LAT, SITE_LON = 30.170167, -95.578097


def _build(tmp_path, name="p", pdf=False, **edits):
    """A copy of the Black Oak example with intake edits applied, run through analysis and report."""
    dst = tmp_path / name
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    for dotted, value in edits.items():
        node = intake
        parts = dotted.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()
    p.run_figures()
    p.artifacts["checklist"] = p.run_checklist()
    p.artifacts["report"] = p.run_report(pdf=pdf)
    return p


def _first_dd(project):
    """Drawdown at the pumped well in the first scenario, the number everything else hangs off."""
    sc = project.artifacts["analysis"]["scenarios"][0]
    return sc["results_by_aquifer"]["Evangeline"]["pumped_wells"][0]["total_ft"]


def _sections(project):
    """The methodology paragraphs as the report renders them, from the same templates and context."""
    from hydrostudy.report.assemble import _env, _template
    from hydrostudy.report.context import build_context
    ctx = build_context(project)
    env = _env()
    return {name: env.from_string(_template(f"{name}.j2")).render(**ctx)
            for name in ("method", "method_after")}


def _leaky_aquifers(intake_path, leakance=1e-4, status="semi-confined", source="test fixture"):
    aq = yaml.safe_load(intake_path.read_text())["aquifers"]
    aq[0]["confinement"] = {"status": status, "confining_unit": "Burkeville", "thickness_ft": 100.0,
                            "leakance_per_day": leakance, "leakance_source": source}
    return aq


def _nearby_well_beyond(project, boundary_east_ft, aq="Evangeline"):
    """The impact rows for wells on the far side of a boundary."""
    res = project.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"][aq]
    return [i for i in res["nearby_impacts"] if i.get("beyond_boundary")]


@pytest.fixture(scope="module")
def example_aquifers():
    return _leaky_aquifers(ROOT / "examples" / "black_oak_well_2" / "intake.yaml")


# --------------------------------------------------------------------------------------------------
# The default must not move
# --------------------------------------------------------------------------------------------------

def test_the_default_is_theis_with_no_boundaries_and_the_narrative_says_so(black_oak_project):
    an = black_oak_project.artifacts["analysis"]
    assert an["solutions"]["Evangeline"]["kind"] == "theis"
    assert not an["solutions"]["Evangeline"]["fell_back"]
    assert black_oak_project.artifacts["geo"]["hydraulic_boundaries"] == []
    for sc in an["scenarios"]:
        for res in sc["results_by_aquifer"].values():
            assert res["solution"]["kind"] == "theis"
            assert res["image_wells"] == []


def test_adding_the_machinery_did_not_disturb_the_accepted_result(black_oak_project):
    """The regression baseline: the District accepted 98.7 ft of drawdown for this well."""
    sc = next(s for s in black_oak_project.artifacts["analysis"]["scenarios"]
              if s["key"].endswith("24h_1") and s["group"] == "proposed_only")
    assert sc["results_by_aquifer"]["Evangeline"]["pumped_wells"][0]["total_ft"] == pytest.approx(98.7, abs=0.1)


# --------------------------------------------------------------------------------------------------
# A leaky solution, asked for and available
# --------------------------------------------------------------------------------------------------

def test_a_leaky_run_reports_less_drawdown_and_names_the_right_solution(tmp_path, example_aquifers):
    theis = _build(tmp_path, "theis")
    leaky = _build(tmp_path, "leaky", **{"analysis.solution": "hantush", "aquifers": example_aquifers})
    assert leaky.artifacts["analysis"]["solutions"]["Evangeline"]["kind"] == "hantush"
    assert _first_dd(leaky) < _first_dd(theis)

    text = _sections(leaky)["method"]
    assert "Hantush-Jacob (1955)" in text and "Theis (1935)" not in text
    # Plain-text scientific notation, not a bare 0.0001 or a Python 1e-04.
    assert "1.00 x 10^-4 per day" in text, "the leakance must be stated, not merely applied"
    assert "leakage factor B of 3,198 ft" in text
    assert "test fixture" in text, "and its provenance must be named"
    assert leaky.artifacts["report"]["lint"]["ok"]

    after = _sections(leaky)["method_after"]
    assert "Hantush-Jacob solution rests on" in after
    assert "less conservative" in after, "the reader must be told which way the assumption cuts"


def test_the_leaky_run_swaps_the_equations_too(tmp_path, example_aquifers):
    """A methodology section showing the Theis well function beside Hantush numbers is a false report."""
    from hydrostudy.report.context import build_context
    leaky = _build(tmp_path, "eq", **{"analysis.solution": "hantush", "aquifers": example_aquifers})
    assert build_context(leaky)["sol"]["is_leaky"]
    figs = leaky.artifacts["figures"]
    assert "Hantush-Jacob" in figs["distance_drawdown"]["solution"]


def test_every_part_of_a_leaky_build_agrees_on_the_solution(tmp_path, example_aquifers):
    leaky = _build(tmp_path, "agree", **{"analysis.solution": "hantush", "aquifers": example_aquifers})
    an = leaky.artifacts["analysis"]
    for sc in an["scenarios"]:
        for res in sc["results_by_aquifer"].values():
            assert res["solution"]["kind"] == "hantush"
            assert res["solution"]["leakance_per_day"] == pytest.approx(1e-4)


# --------------------------------------------------------------------------------------------------
# A leaky solution asked for and NOT available: the honesty case
# --------------------------------------------------------------------------------------------------

def test_a_leaky_run_without_a_leakance_falls_back_to_theis_and_says_theis(tmp_path):
    """No invented leakance, and above all no report claiming a solution that was not run."""
    p = _build(tmp_path, "nolk", **{"analysis.solution": "hantush"})
    sol = p.artifacts["analysis"]["solutions"]["Evangeline"]
    assert sol["kind"] == "theis" and sol["requested"] == "hantush" and sol["fell_back"]
    assert sol["leakance_per_day"] is None

    codes = [f["code"] for f in p.artifacts["flags"]]
    assert "LEAKANCE_MISSING" in codes

    text = _sections(p)["method"]
    assert "Theis (1935)" in text, "the narrative must describe what actually ran"
    assert "Hantush" not in text
    assert _first_dd(p) == pytest.approx(_first_dd(_build(tmp_path, "plain")), rel=1e-12)


def test_an_uncited_leakance_is_flagged_and_says_so_in_the_report(tmp_path):
    """Every drawdown in a leaky report rests on this one number. It has to be attributable."""
    aq = _leaky_aquifers(ROOT / "examples" / "black_oak_well_2" / "intake.yaml", source=None)
    p = _build(tmp_path, "uncited", **{"analysis.solution": "hantush", "aquifers": aq})
    assert "LEAKANCE_UNCITED" in [f["code"] for f in p.artifacts["flags"]]
    # And the methodology paragraph must not imply a provenance that does not exist.
    text = _sections(p)["method"]
    assert "source not stated in the intake" in text
    assert p.artifacts["report"]["lint"]["ok"]


def test_a_leaky_solution_on_a_confined_aquifer_is_flagged_for_the_reviewer(tmp_path):
    aq = _leaky_aquifers(ROOT / "examples" / "black_oak_well_2" / "intake.yaml", status="confined")
    p = _build(tmp_path, "conf", **{"analysis.solution": "hantush", "aquifers": aq})
    assert "LEAKY_BUT_CONFINED" in [f["code"] for f in p.artifacts["flags"]]


# --------------------------------------------------------------------------------------------------
# Hydraulic boundaries
# --------------------------------------------------------------------------------------------------

def _boundary(kind, name, east_ft=1500.0):
    """A north-south boundary `east_ft` east of the site, as lat/lon."""
    from hydrostudy.geo.crs import LocalCRS
    crs = LocalCRS(SITE_LAT, SITE_LON)
    lon1, lat1 = crs.to_wgs84(east_ft, -8000.0)
    lon2, lat2 = crs.to_wgs84(east_ft, 8000.0)
    return {"kind": kind, "name": name, "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2,
            "source": "test fixture interpretation"}


def test_a_barrier_deepens_and_a_recharge_boundary_shallows_the_reported_drawdown(tmp_path):
    plain = _build(tmp_path, "b_plain")
    barrier = _build(tmp_path, "b_bar", **{"analysis.boundaries": [_boundary("barrier", "Conroe fault")]})
    recharge = _build(tmp_path, "b_rec", **{"analysis.boundaries": [_boundary("recharge", "Spring Creek")]})
    assert _first_dd(barrier) > _first_dd(plain) > _first_dd(recharge)


def test_a_boundary_puts_image_wells_in_the_superposition_and_in_no_table(tmp_path):
    p = _build(tmp_path, "img", **{"analysis.boundaries": [_boundary("barrier", "Conroe fault")]})
    res = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
    assert len(res["image_wells"]) == 1
    img = res["image_wells"][0]
    assert img["parent_id"] == "W2" and img["q_gpm"] > 0

    reported = ({w["id"] for w in res["wells_xy"]} | {w["id"] for w in res["pumped_wells"]}
                | {w["id"] for w in res["idle_wells"]}
                | {str(i["map_id"]) for i in res["nearby_impacts"]})
    assert not any("~img" in i for i in reported), "an image well must never appear as a well"
    # Nor anywhere in the rendered report.
    from hydrostudy.report.context import build_context
    assert "~img" not in str(build_context(p))


def test_the_boundary_is_described_in_the_narrative_with_its_source(tmp_path):
    p = _build(tmp_path, "bnarr", **{"analysis.boundaries": [_boundary("recharge", "Spring Creek")]})
    text = _sections(p)["method"]
    assert "recharge boundary at Spring Creek" in text
    assert "test fixture interpretation" in text, "an interpretation must be attributable"
    assert "method of images" in text
    assert "exact analytical solution for a single straight boundary" in text
    assert p.artifacts["report"]["lint"]["ok"]
    assert "HYDRAULIC_BOUNDARIES" in [f["code"] for f in p.artifacts["flags"]]


def test_two_boundaries_are_reported_as_a_truncated_series(tmp_path):
    p = _build(tmp_path, "two", **{"analysis.boundaries": [_boundary("barrier", "East fault", 1500.0),
                                                           _boundary("barrier", "West fault", -2500.0)]})
    text = _sections(p)["method"]
    assert "truncated" in text
    res = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
    assert len(res["image_wells"]) > 2
    note = next(f for f in p.artifacts["flags"] if f["code"] == "HYDRAULIC_BOUNDARIES")
    assert "truncated" in note["text"]


def test_the_cone_edge_is_still_measured_from_the_real_wells(tmp_path):
    """Image wells carry rates. If they reach the pumping centre, the cone is reported about a point
    halfway to a well that does not exist."""
    plain = _build(tmp_path, "c_plain")
    bounded = _build(tmp_path, "c_bnd", **{"analysis.boundaries": [_boundary("barrier", "Fault")]})
    for p in (plain, bounded):
        res = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
        centre = res["cone_edges"][0]["center_xy"]
        well = next(w for w in res["wells_xy"] if w["id"] == "W2")
        assert centre == pytest.approx([well["x_ft"], well["y_ft"]], abs=1e-6)


def test_leakage_and_a_boundary_compose(tmp_path, example_aquifers):
    """Nothing in either feature assumes the other is off."""
    both = _build(tmp_path, "both", **{"analysis.solution": "hantush", "aquifers": example_aquifers,
                                       "analysis.boundaries": [_boundary("recharge", "Spring Creek")]})
    leaky_only = _build(tmp_path, "lk_only", **{"analysis.solution": "hantush", "aquifers": example_aquifers})
    assert _first_dd(both) < _first_dd(leaky_only)
    res = both.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
    assert res["solution"]["kind"] == "hantush" and len(res["image_wells"]) == 1
    text = _sections(both)["method"]
    assert "Hantush-Jacob (1955)" in text and "Spring Creek" in text
    assert both.artifacts["report"]["lint"]["ok"]


# --------------------------------------------------------------------------------------------------
# Receptors beyond a boundary: the image solution does not represent them
# --------------------------------------------------------------------------------------------------

def test_no_drawdown_is_reported_at_a_well_beyond_a_recharge_boundary(tmp_path):
    """Past a constant-head boundary the superposition returns negative drawdown. Report nothing."""
    # The boundary sits 500 ft east of the site, so the wells to the east are beyond it.
    p = _build(tmp_path, "far_rec", **{"analysis.boundaries": [_boundary("recharge", "Spring Creek", 500.0)]})
    res = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
    outside = [i for i in res["nearby_impacts"] if i["beyond_boundary"]]
    assert outside, "the fixture has registered wells east of the boundary"
    for i in outside:
        assert i["drawdown_ft"] is None
        assert i["beyond_boundary"] == ["Spring Creek"]
    # And nothing anywhere in the build reports a negative drawdown.
    for i in res["nearby_impacts"]:
        assert i["drawdown_ft"] is None or i["drawdown_ft"] >= 0.0


def test_no_drawdown_is_reported_at_a_well_beyond_a_barrier(tmp_path):
    """Past a barrier the superposition grows with distance, which would read as a deeper cone further
    away. Reporting nothing is the only defensible answer."""
    p = _build(tmp_path, "far_bar", **{"analysis.boundaries": [_boundary("barrier", "Conroe fault", 500.0)]})
    res = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
    outside = [i for i in res["nearby_impacts"] if i["beyond_boundary"]]
    assert outside
    assert all(i["drawdown_ft"] is None for i in outside)
    # Inside the aquifer, drawdown must still fall away with distance.
    inside = sorted([i for i in res["nearby_impacts"]
                     if not i["beyond_boundary"] and i["drawdown_ft"] is not None
                     and i["applicability"] == "same"], key=lambda i: i["distance_ft"])
    values = [i["drawdown_ft"] for i in inside]
    assert values == sorted(values, reverse=True), "drawdown must decrease with distance"


def test_the_cone_edge_stops_at_a_barrier_instead_of_running_past_it(tmp_path):
    p = _build(tmp_path, "edge", **{"analysis.boundaries": [_boundary("barrier", "Conroe fault", 800.0)]})
    res = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
    edge = res["cone_edges"][0]
    assert edge["truncated_azimuths"] > 0, "azimuths pointing at the fault must be cut off"
    plain = _build(tmp_path, "edge_plain")
    plain_edge = plain.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]["cone_edges"][0]
    assert plain_edge["truncated_azimuths"] == 0


def test_the_interference_table_adds_up_when_a_boundary_is_in_effect(tmp_path):
    """A row whose printed cells do not make its printed total is a table nobody can check."""
    p = _build(tmp_path, "matrix", **{"analysis.boundaries": [_boundary("barrier", "Conroe fault")]})
    sysm = p.artifacts["analysis"]["system_interference"]
    assert sysm, "the example has an existing system well, so there is a system scenario"
    m = next(iter(sysm.values()))["Evangeline"]
    assert m["has_boundary_effect"]
    for wid in m["well_ids"]:
        row = m["rows"][wid]
        cells = sum(row[j] for j in m["well_ids"]) + row["_boundary"]
        assert cells == pytest.approx(row["_total"], rel=1e-9)
    assert m["rows"][m["well_ids"][0]]["_boundary"] > 0

    from hydrostudy.report.context import build_context
    si = build_context(p)["si"]
    assert si["has_boundary_effect"] and "Conroe fault" in si["header"][-2]
    assert len(si["rows"][0]) == len(si["header"])


def test_a_boundary_named_for_one_aquifer_does_not_bend_another(tmp_path):
    """A fault that throws the Evangeline out of contact says nothing about the Jasper."""
    b = _boundary("barrier", "Jasper-only fault")
    b["aquifer"] = "Jasper"
    scoped = _build(tmp_path, "scoped", **{"analysis.boundaries": [b]})
    plain = _build(tmp_path, "scoped_plain")
    res = scoped.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]
    assert res["image_wells"] == [] and res["boundary_labels"] == []
    assert _first_dd(scoped) == pytest.approx(_first_dd(plain), rel=1e-12)
