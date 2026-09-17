"""Parameter uncertainty by Monte Carlo.

An uncertainty analysis has a failure mode the rest of the package does not: it is *about* how much to
trust the other numbers, so an invented spread or an irreproducible interval is worse than no analysis
at all. These tests hold three lines: nothing is defaulted, the same seed gives the same answer, and the
reported quantiles behave like quantiles.
"""

import math
import shutil

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from hydrostudy.analysis.uncertainty import (
    UncertaintyNotPossible,
    UncertaintyRequest,
    propagate,
    quantile_standard_error,
    sample,
)
from hydrostudy.pipeline import Project
from hydrostudy.schema.intake import ParamDistribution
from tests.conftest import ROOT

T_SPREAD = {"kind": "lognormal", "p10": 1023.0, "p90": 1231.2,
            "source": "36-hour test at Well No. 1 and the HAGM value at the same cell"}
S_SPREAD = {"kind": "lognormal", "median": 3.36e-4, "gsd": 1.6,
            "source": "illustrative fixture, not a real determination"}


def _project(tmp_path, name="unc", uncertainty=None):
    dst = tmp_path / name
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    if uncertainty is not None:
        intake = yaml.safe_load((dst / "intake.yaml").read_text())
        intake["aquifers"][0]["uncertainty"] = uncertainty
        (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()
    return p


@pytest.fixture(scope="module")
def propagated(tmp_path_factory):
    p = _project(tmp_path_factory.mktemp("u"), uncertainty={"t_ft2d": T_SPREAD, "s": S_SPREAD})
    return p, propagate(p, UncertaintyRequest(draws=4000, thresholds_ft=(25.0, 50.0)))


# --------------------------------------------------------------------------------------------------
# Nothing is defaulted
# --------------------------------------------------------------------------------------------------

def test_with_no_declared_spread_it_refuses_and_says_what_to_supply(tmp_path):
    """Inventing a coefficient of variation would be inventing the confidence interval."""
    p = _project(tmp_path)
    with pytest.raises(UncertaintyNotPossible) as e:
        propagate(p)
    msg = str(e.value)
    assert "no parameter uncertainty is declared" in msg
    assert "uncertainty:" in msg and "source:" in msg, "the refusal has to show the shape to supply"
    assert "deliberately not defaulted" in msg


def test_a_distribution_cannot_be_declared_without_a_source():
    """The source is required by the schema, not by convention."""
    with pytest.raises(ValidationError):
        ParamDistribution(kind="lognormal", p10=900, p90=1300)
    ok = ParamDistribution(kind="lognormal", p10=900, p90=1300, source="a test")
    assert ok.source == "a test"


def test_a_parameter_with_no_spread_is_held_and_said_to_be_held(tmp_path):
    p = _project(tmp_path, uncertainty={"t_ft2d": T_SPREAD})
    out = propagate(p, UncertaintyRequest(draws=1000))
    assert out["parameters"]["t_ft2d"]["declared"]
    assert not out["parameters"]["s"]["declared"]
    held = out["parameters"]["s"]
    assert held["declared_p10"] == held["declared_p90"] == pytest.approx(3.36e-4)
    assert held["sample_p10"] == held["sample_p90"] == pytest.approx(3.36e-4)
    assert any("Storativity was held at its intake value" in n for n in out["notes"])


# --------------------------------------------------------------------------------------------------
# It is reproducible
# --------------------------------------------------------------------------------------------------

def test_the_same_seed_gives_bit_identical_numbers(propagated):
    """A sealed report has to be re-derivable. An interval nobody can reproduce is not evidence."""
    p, first = propagated
    again = propagate(p, UncertaintyRequest(draws=4000, thresholds_ft=(25.0, 50.0)))
    for a, b in zip(first["receptors"], again["receptors"], strict=True):
        assert a["quantiles"] == b["quantiles"]
        assert a["exceedance"] == b["exceedance"]
    assert first["seed"] == again["seed"]


def test_a_different_seed_moves_the_answer_only_within_its_own_standard_error(propagated):
    p, first = propagated
    other = propagate(p, UncertaintyRequest(draws=4000, seed=999, thresholds_ft=(25.0, 50.0)))
    for a, b in zip(first["receptors"], other["receptors"], strict=True):
        for q in ("0.1", "0.5", "0.9"):
            se = a["quantiles"][q]["standard_error_ft"]
            assert abs(a["quantiles"][q]["ft"] - b["quantiles"][q]["ft"]) < 4 * se, (a["label"], q)
    # ...but it is a different sample, so it is not the identical answer.
    assert first["receptors"][0]["quantiles"]["0.5"]["ft"] != other["receptors"][0]["quantiles"]["0.5"]["ft"]


def test_the_draw_count_and_seed_are_recorded(propagated):
    _, out = propagated
    assert out["draws"] == 4000 and out["seed"] == 20260917
    assert any("recorded so this interval can be reproduced" in n for n in out["notes"])


# --------------------------------------------------------------------------------------------------
# The quantiles behave like quantiles
# --------------------------------------------------------------------------------------------------

def test_quantiles_are_ordered_and_bracket_the_median(propagated):
    _, out = propagated
    for r in out["receptors"]:
        q = r["quantiles"]
        assert r["min_ft"] <= q["0.1"]["ft"] < q["0.5"]["ft"] < q["0.9"]["ft"] <= r["max_ft"]


def test_the_exceedance_probability_of_the_median_is_a_half(propagated):
    p, out = propagated
    median = out["receptors"][0]["quantiles"]["0.5"]["ft"]
    one = propagate(p, UncertaintyRequest(draws=4000, thresholds_ft=(median,)))
    assert one["receptors"][0]["exceedance"][f"{median:g}"] == pytest.approx(0.5, abs=0.02)


def test_the_standard_error_falls_with_the_square_root_of_the_draws(tmp_path):
    p = _project(tmp_path, uncertainty={"t_ft2d": T_SPREAD, "s": S_SPREAD})
    small = propagate(p, UncertaintyRequest(draws=1000))["receptors"][0]["quantiles"]["0.5"]
    large = propagate(p, UncertaintyRequest(draws=16000))["receptors"][0]["quantiles"]["0.5"]
    # 16x the draws should be about 4x tighter; allow a wide band because the estimate is itself noisy.
    ratio = small["standard_error_ft"] / large["standard_error_ft"]
    assert 2.5 < ratio < 6.0, ratio


def test_too_few_draws_is_refused_rather_than_answered_badly(tmp_path):
    p = _project(tmp_path, uncertainty={"t_ft2d": T_SPREAD})
    with pytest.raises(UncertaintyNotPossible, match="at least 100 draws"):
        propagate(p, UncertaintyRequest(draws=50))
    assert math.isnan(quantile_standard_error(np.arange(50.0), 0.9))


# --------------------------------------------------------------------------------------------------
# The physics is the right way round
# --------------------------------------------------------------------------------------------------

def test_a_higher_transmissivity_spread_means_less_drawdown(tmp_path):
    """Drawdown falls as T rises, so shifting the whole distribution up must lower every quantile."""
    low = _project(tmp_path, "low", uncertainty={
        "t_ft2d": {"kind": "lognormal", "p10": 800.0, "p90": 1000.0, "source": "fixture"}})
    high = _project(tmp_path, "high", uncertainty={
        "t_ft2d": {"kind": "lognormal", "p10": 1600.0, "p90": 2000.0, "source": "fixture"}})
    a = propagate(low, UncertaintyRequest(draws=2000))["receptors"][0]["quantiles"]
    b = propagate(high, UncertaintyRequest(draws=2000))["receptors"][0]["quantiles"]
    for q in ("0.1", "0.5", "0.9"):
        assert b[q]["ft"] < a[q]["ft"], q


def test_a_wider_spread_gives_a_wider_interval(tmp_path):
    narrow = _project(tmp_path, "narrow", uncertainty={
        "t_ft2d": {"kind": "lognormal", "median": 1023.0, "gsd": 1.05, "source": "fixture"}})
    wide = _project(tmp_path, "wide", uncertainty={
        "t_ft2d": {"kind": "lognormal", "median": 1023.0, "gsd": 1.5, "source": "fixture"}})
    def width(project):
        q = propagate(project, UncertaintyRequest(draws=3000))["receptors"][0]["quantiles"]
        return q["0.9"]["ft"] - q["0.1"]["ft"]
    assert width(wide) > 3 * width(narrow)


def test_a_spread_centred_on_the_intake_value_puts_it_near_the_median(tmp_path):
    """The reported value is the median only when the intake's parameter is the centre of the spread."""
    p = _project(tmp_path, uncertainty={
        "t_ft2d": {"kind": "lognormal", "median": 1023.0, "gsd": 1.2, "source": "fixture"}})
    out = propagate(p, UncertaintyRequest(draws=8000))
    for r in out["receptors"]:
        assert r["deterministic_percentile"] == pytest.approx(0.5, abs=0.06), r["label"]


def test_an_off_centre_spread_is_called_out_rather_than_left_to_be_misread(tmp_path):
    """T's intake value is the p10 of this spread, so the reported drawdown is a high percentile. Saying
    so is what stops the median being quoted as a correction to the report."""
    p = _project(tmp_path, uncertainty={"t_ft2d": T_SPREAD})
    out = propagate(p, UncertaintyRequest(draws=4000))
    assert all(r["deterministic_percentile"] > 0.65 for r in out["receptors"])
    assert any("percentile of this distribution" in n and "conservative" in n for n in out["notes"])


# --------------------------------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("spec", "check"), [
    ({"kind": "lognormal", "p10": 100.0, "p90": 400.0},
     lambda d: (np.quantile(d, 0.10) == pytest.approx(100.0, rel=0.05)
                and np.quantile(d, 0.90) == pytest.approx(400.0, rel=0.05))),
    ({"kind": "lognormal", "median": 200.0, "gsd": 2.0},
     lambda d: np.median(d) == pytest.approx(200.0, rel=0.05)),
    ({"kind": "uniform", "minimum": 10.0, "maximum": 20.0},
     lambda d: d.min() >= 10.0 and d.max() <= 20.0 and np.mean(d) == pytest.approx(15.0, rel=0.02)),
    ({"kind": "triangular", "minimum": 10.0, "mode": 12.0, "maximum": 20.0},
     lambda d: d.min() >= 10.0 and d.max() <= 20.0 and np.mean(d) == pytest.approx(14.0, rel=0.03)),
])
def test_each_distribution_reproduces_what_was_declared(spec, check):
    dist = ParamDistribution(source="fixture", **spec)
    rng = np.random.default_rng(7)
    draws = sample(dist, 40000, rng)
    assert np.all(draws > 0)
    assert check(draws)


def test_the_normal_scale_sampler_agrees_with_the_direct_one(tmp_path):
    """Correlated draws go through a shared normal scale; that path must give the same distribution."""
    from hydrostudy.analysis.uncertainty import _from_normal
    for spec in ({"kind": "lognormal", "p10": 100.0, "p90": 400.0},
                 {"kind": "uniform", "minimum": 10.0, "maximum": 20.0},
                 {"kind": "triangular", "minimum": 10.0, "mode": 12.0, "maximum": 20.0}):
        dist = ParamDistribution(source="fixture", **spec)
        rng = np.random.default_rng(11)
        direct = sample(dist, 40000, np.random.default_rng(11))
        viaz = _from_normal(dist, rng.normal(0.0, 1.0, 40000))
        for q in (0.1, 0.5, 0.9):
            assert np.quantile(viaz, q) == pytest.approx(np.quantile(direct, q), rel=0.04), (spec, q)


def test_a_declared_correlation_is_applied_and_recorded(tmp_path):
    independent = _project(tmp_path, "ind", uncertainty={"t_ft2d": T_SPREAD, "s": S_SPREAD})
    correlated = _project(tmp_path, "cor", uncertainty={
        "t_ft2d": T_SPREAD, "s": S_SPREAD, "log_correlation": 0.9,
        "correlation_source": "both fitted from the same single-well test"})
    a = propagate(independent, UncertaintyRequest(draws=6000))
    b = propagate(correlated, UncertaintyRequest(draws=6000))
    assert a["parameters"]["log_correlation"] is None
    assert b["parameters"]["log_correlation"] == 0.9
    assert any("drawn independently" in n for n in a["notes"])
    assert any("rank correlation of +0.90" in n for n in b["notes"])
    assert any("same single-well test" in n for n in b["notes"])
    # T and S both reduce drawdown at a distant well, so correlating them positively widens its spread.
    def width(out):
        r = next(x for x in out["receptors"] if x["kind"] == "registered")
        return r["quantiles"]["0.9"]["ft"] - r["quantiles"]["0.1"]["ft"]
    assert width(b) > width(a)


# --------------------------------------------------------------------------------------------------
# Consistency with the rest of the package
# --------------------------------------------------------------------------------------------------

def test_it_reports_the_scenario_the_district_decides_on(propagated):
    _, out = propagated
    assert out["scenario_key"].startswith("system_max_production")
    assert "All system wells" in out["scenario_title"]
    assert out["duration_days"] == pytest.approx(27.4, abs=0.1)


def test_a_named_scenario_can_be_chosen_and_an_unknown_one_is_refused(propagated):
    p, _ = propagated
    key = p.artifacts["analysis"]["scenarios"][0]["key"]
    out = propagate(p, UncertaintyRequest(draws=500, scenario_key=key))
    assert out["scenario_key"] == key
    with pytest.raises(UncertaintyNotPossible, match="no scenario"):
        propagate(p, UncertaintyRequest(draws=500, scenario_key="not_a_scenario"))


def test_it_uses_the_projects_own_solution(tmp_path):
    aq = yaml.safe_load((ROOT / "examples" / "black_oak_well_2" / "intake.yaml").read_text())["aquifers"]
    aq[0]["confinement"] = {"status": "semi-confined", "thickness_ft": 100.0,
                            "leakance_per_day": 1e-4, "leakance_source": "fixture"}
    aq[0]["uncertainty"] = {"t_ft2d": T_SPREAD}
    dst = tmp_path / "leaky"
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    intake["aquifers"] = aq
    intake["analysis"]["solution"] = "hantush"
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()

    out = propagate(p, UncertaintyRequest(draws=2000))
    assert out["solution"]["kind"] == "hantush"
    theis = propagate(_project(tmp_path, "theis", uncertainty={"t_ft2d": T_SPREAD}),
                      UncertaintyRequest(draws=2000))
    # Leakage reduces drawdown, so every quantile at the pumped well must come in lower.
    for q in ("0.1", "0.5", "0.9"):
        assert (out["receptors"][0]["quantiles"][q]["ft"]
                < theis["receptors"][0]["quantiles"][q]["ft"]), q


def test_every_receptor_the_report_quotes_is_covered(propagated):
    p, out = propagated
    res = p.artifacts["analysis"]["scenarios"]
    scen = next(s for s in res if s["key"] == out["scenario_key"])["results_by_aquifer"]["Evangeline"]
    assert {r["label"] for r in out["receptors"] if r["kind"] == "pumped"} == {
        next(w.label for w in p.intake.all_wells if w.id == pw["id"]) for pw in scen["pumped_wells"]}
    covered = {r["map_id"] for r in out["receptors"] if r["kind"] == "registered"}
    expected = {i["map_id"] for i in scen["nearby_impacts"]
                if i["drawdown_ft"] is not None and i["applicability"] == "same" and not i["is_system_well"]}
    assert covered == expected


def test_the_deterministic_value_is_carried_alongside_every_distribution(propagated):
    _, out = propagated
    for r in out["receptors"]:
        assert r["deterministic_ft"] is not None
        assert out["deterministic"][r["key"]] == pytest.approx(r["deterministic_ft"])


def test_it_says_what_it_does_not_cover(propagated):
    """A narrow interval is not a statement that the answer is right, and the output has to say so."""
    _, out = propagated
    assert any("says nothing about whether the Theis assumptions hold" in n for n in out["notes"])
    assert any("standard error" in n for n in out["notes"])


def test_an_aquifer_the_intake_does_not_define_is_refused(propagated):
    p, _ = propagated
    with pytest.raises(UncertaintyNotPossible, match="defines no aquifer"):
        propagate(p, UncertaintyRequest(draws=500, aquifer="Jasper"))


# --------------------------------------------------------------------------------------------------
# Whatever quantiles were asked for
# --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("quantiles", [(0.05, 0.5, 0.95), (0.5, 0.9), (0.5,), (0.01, 0.25, 0.5, 0.75, 0.99)])
def test_any_requested_quantiles_work_end_to_end_including_the_figure(tmp_path, quantiles):
    """The runbook recommends --quantiles 0.05,0.5,0.95, which used to die with a KeyError - and worse,
    die in the figure *after* the analysis had succeeded, losing the whole run."""
    from hydrostudy.figures import uncertainty_plot
    p = _project(tmp_path, f"q{len(quantiles)}", uncertainty={"t_ft2d": T_SPREAD, "s": S_SPREAD})
    out = propagate(p, UncertaintyRequest(draws=1000, quantiles=quantiles, thresholds_ft=(50.0,)))
    keys = [f"{q:g}" for q in sorted(quantiles)]
    for r in out["receptors"]:
        assert list(r["quantiles"]) == keys
    assert any("most exposed to the parameter spread" in n for n in out["notes"])

    d = p.build_dir / "figures"
    d.mkdir(parents=True, exist_ok=True)
    samples = out.pop("_samples")
    fig = uncertainty_plot.render(p, out, samples, d / "fig_unc.png")
    assert fig["path"].endswith(".png")


def test_the_quantile_keys_helper_picks_the_extremes_and_the_most_central():
    from hydrostudy.analysis.uncertainty import quantile_keys
    assert quantile_keys((0.1, 0.5, 0.9)) == ("0.1", "0.5", "0.9")
    assert quantile_keys((0.95, 0.05, 0.5)) == ("0.05", "0.5", "0.95")
    assert quantile_keys((0.25, 0.75)) == ("0.25", "0.25", "0.75"), "no exact median: the nearest one"
    assert quantile_keys((0.5,)) == ("0.5", "0.5", "0.5")


# --------------------------------------------------------------------------------------------------
# The declaration is quoted, not a sample of it
# --------------------------------------------------------------------------------------------------

def test_the_declared_quantiles_are_exact_not_sampled(tmp_path):
    """A caption saying "T from 1,023 to 1,231 as declared" has to mean the declaration. A sample
    quantile from 10,000 draws lands a few units off, and printing that misstates the input."""
    from hydrostudy.analysis.uncertainty import declared_quantile
    from hydrostudy.schema.intake import ParamDistribution
    ln = ParamDistribution(kind="lognormal", p10=1023.0, p90=1231.2, source="fixture")
    assert declared_quantile(ln, 0.10) == pytest.approx(1023.0, rel=1e-9)
    assert declared_quantile(ln, 0.90) == pytest.approx(1231.2, rel=1e-9)
    uni = ParamDistribution(kind="uniform", minimum=800.0, maximum=1200.0, source="fixture")
    assert declared_quantile(uni, 0.0) == pytest.approx(800.0)
    assert declared_quantile(uni, 1.0) == pytest.approx(1200.0)
    assert declared_quantile(uni, 0.5) == pytest.approx(1000.0)

    p = _project(tmp_path, uncertainty={"t_ft2d": T_SPREAD})
    par = propagate(p, UncertaintyRequest(draws=1000))["parameters"]["t_ft2d"]
    assert par["declared_p10"] == pytest.approx(1023.0, rel=1e-9)
    assert par["declared_p90"] == pytest.approx(1231.2, rel=1e-9)
    # The sample is close but not the declaration, and is reported separately rather than as it.
    assert par["sample_p10"] != par["declared_p10"]
    assert par["sample_p10"] == pytest.approx(par["declared_p10"], rel=0.05)


def test_one_sampler_so_the_tests_cover_the_path_production_uses():
    """`sample` and the correlated path must be the same derivation; two would eventually disagree."""
    from hydrostudy.analysis.uncertainty import _from_normal
    from hydrostudy.schema.intake import ParamDistribution
    for spec in ({"kind": "lognormal", "p10": 100.0, "p90": 400.0},
                 {"kind": "uniform", "minimum": 10.0, "maximum": 20.0},
                 {"kind": "triangular", "minimum": 10.0, "mode": 12.0, "maximum": 20.0}):
        dist = ParamDistribution(source="fixture", **spec)
        a = sample(dist, 500, np.random.default_rng(3))
        b = _from_normal(dist, np.random.default_rng(3).normal(0.0, 1.0, 500))
        np.testing.assert_allclose(a, b, rtol=0, atol=0)


# --------------------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------------------

def test_two_wells_with_the_same_display_name_keep_their_own_numbers(tmp_path):
    """Nothing requires `display_name` to be unique; only ids are. Keying on the name merged two wells
    and handed each the other's reported value."""
    import copy
    dst = tmp_path / "twins"
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    first = intake["proposed_wells"][0]
    second = copy.deepcopy(first)
    second["id"] = "W3"
    second["lat"] = 30.1725            # a few hundred feet away, same name on purpose
    intake["proposed_wells"].append(second)
    intake["aquifers"][0]["uncertainty"] = {"t_ft2d": T_SPREAD}
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()

    out = propagate(p, UncertaintyRequest(draws=1000))
    pumped = [r for r in out["receptors"] if r["kind"] == "pumped"]
    assert len({r["label"] for r in pumped}) < len(pumped), "the fixture really does have duplicate names"
    assert len({r["key"] for r in pumped}) == len(pumped), "keys must stay distinct"
    assert {r["key"] for r in pumped} >= {"well:W2", "well:W3"}
    # Each well's reported value is its own, taken from the scenario by id.
    scen = next(s for s in p.artifacts["analysis"]["scenarios"] if s["key"] == out["scenario_key"])
    by_id = {w["id"]: w["total_ft"] for w in scen["results_by_aquifer"]["Evangeline"]["pumped_wells"]}
    for r in pumped:
        assert r["deterministic_ft"] == pytest.approx(by_id[r["well_id"]])
    assert len({r["deterministic_ft"] for r in pumped}) == len(pumped), "two wells, two different values"
