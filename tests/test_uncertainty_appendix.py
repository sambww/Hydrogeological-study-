"""The uncertainty appendix on the report path.

The Monte Carlo itself is tested in `test_uncertainty.py`. What is at stake here is different: this is
the first thing to put a *distribution* into a document a District files and a P.G. seals. Three things
have to hold, and each has a test below.

1. It is off unless the intake asks for it, so every report built before it existed is unchanged.
2. Asking for it is not permission to invent a spread. Without a declared distribution the appendix is
   dropped and the build says why, rather than the report going out silently missing the section the
   operator asked for.
3. Every number in the appendix comes from the propagated result. The anti-fabrication lint covers the
   prose; the tables are checked here against `build/uncertainty.json` directly, because a table the
   lint does not read is exactly where a stale or re-derived figure would survive.
"""

import shutil

import pytest
import yaml
from pydantic import ValidationError

from hydrostudy.pipeline import Project
from hydrostudy.report.context import _join, _uncertainty_context, build_context
from hydrostudy.schema.intake import UncertaintyAppendix
from tests.conftest import ROOT

T_SPREAD = {"kind": "lognormal", "p10": 1023.0, "p90": 1231.2,
            "source": "36-hour test at Well No. 1 and the HAGM value at the same cell"}
S_SPREAD = {"kind": "lognormal", "median": 3.36e-4, "gsd": 1.6,
            "source": "illustrative fixture, not a real determination"}
APPENDIX = {"draws": 2000, "seed": 7, "quantiles": [0.1, 0.5, 0.9], "thresholds_ft": [50.0]}


def _project(tmp_path, name="app", uncertainty=None, appendix=None):
    dst = tmp_path / name
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    if uncertainty is not None:
        intake["aquifers"][0]["uncertainty"] = uncertainty
    if appendix is not None:
        intake.setdefault("analysis", {})["uncertainty_appendix"] = appendix
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    return Project(dst)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A full report with the appendix, built once: figures and a DOCX are not cheap."""
    p = _project(tmp_path_factory.mktemp("app"), uncertainty={"t_ft2d": T_SPREAD, "s": S_SPREAD},
                 appendix=APPENDIX)
    p.run_analysis()
    p.run_figures()
    p.run_checklist()
    result = p.run_report(pdf=False)
    return p, result


# --------------------------------------------------------------------------------------------------
# It is opt-in
# --------------------------------------------------------------------------------------------------

def test_no_appendix_and_no_monte_carlo_without_the_intake_asking(tmp_path):
    """The default path must not even run the simulation, or every existing report changes."""
    p = _project(tmp_path, uncertainty={"t_ft2d": T_SPREAD})
    p.run_analysis()
    assert "uncertainty" not in p.artifacts
    assert not (p.build_dir / "uncertainty.json").exists()
    p.run_figures()
    assert "uncertainty" not in p.artifacts["figures"]
    assert build_context(p)["unc"] is None


def test_asking_for_it_runs_it_and_writes_the_artifact(built):
    p, _ = built
    unc = p.artifacts["uncertainty"]
    assert unc["draws"] == APPENDIX["draws"] and unc["seed"] == APPENDIX["seed"]
    assert (p.build_dir / "uncertainty.json").exists()
    # The draws themselves are the one thing that must not reach the JSON: 2,000 floats per receptor.
    assert "_samples" not in unc
    assert yaml.safe_load((p.build_dir / "uncertainty.json").read_text()).get("_samples") is None


def test_the_appendix_figure_takes_no_number_in_the_body_sequence(built):
    """Inserting it into the figure numbering would renumber every figure in a reviewed report."""
    p, result = built
    ctx = build_context(p)
    assert "uncertainty" in p.artifacts["figures"]
    assert "uncertainty" not in ctx["fignum"]
    assert ctx["unc"]["figure_label"] == "Figure D-1"
    without = _figure_numbers_without_appendix(p)
    assert {k: v for k, v in ctx["fignum"].items()} == without


def _figure_numbers_without_appendix(p):
    from hydrostudy.report.context import assign_numbers
    figs = dict(p.artifacts["figures"])
    p.artifacts["figures"] = {k: v for k, v in figs.items() if k != "uncertainty"}
    try:
        return assign_numbers(p)[0]
    finally:
        p.artifacts["figures"] = figs


# --------------------------------------------------------------------------------------------------
# Asking for it is not permission to invent a spread
# --------------------------------------------------------------------------------------------------

def test_requested_but_undeclared_is_flagged_not_guessed(tmp_path):
    p = _project(tmp_path, appendix=APPENDIX)          # appendix asked for, no distribution declared
    p.run_analysis()
    assert "uncertainty" not in p.artifacts
    flag = next(f for f in p.artifacts["flags"] if f["code"] == "UNCERTAINTY_APPENDIX_UNAVAILABLE")
    assert flag["level"] == "review"
    assert "no parameter uncertainty is declared" in flag["text"]
    assert "omitted" in flag["text"], "the flag has to say the report went out without the section"


def test_the_report_still_builds_without_the_declared_spread(tmp_path):
    """A missing spread degrades the report by one appendix; it does not fail the build."""
    p = _project(tmp_path, appendix=APPENDIX)
    p.run_analysis()
    p.run_figures()
    p.run_checklist()
    result = p.run_report(pdf=False)
    assert result["lint"]["ok"]
    assert "uncertainty" not in result["sections"]


def test_a_guessed_quantile_list_is_refused_by_the_schema():
    with pytest.raises(ValidationError):
        UncertaintyAppendix(quantiles=[0.1, 1.4])
    with pytest.raises(ValidationError):
        UncertaintyAppendix(quantiles=[])
    with pytest.raises(ValidationError):
        UncertaintyAppendix(thresholds_ft=[-5.0])
    with pytest.raises(ValidationError):
        UncertaintyAppendix(draws=10)                  # too few for a meaningful quantile
    assert UncertaintyAppendix(quantiles=[0.9, 0.1, 0.5]).quantiles == [0.1, 0.5, 0.9]


# --------------------------------------------------------------------------------------------------
# Every number in the appendix is the propagated one
# --------------------------------------------------------------------------------------------------

def test_the_appendix_renders_and_passes_the_numbers_lint(built):
    _, result = built
    assert result["lint"]["ok"], result["lint"]["problems"]
    assert "uncertainty" in result["sections"]


def test_the_receptor_table_matches_the_propagated_result_row_for_row(built):
    p, _ = built
    unc = p.artifacts["uncertainty"]
    ctx = build_context(p)
    rows = ctx["unc"]["receptor_rows"]
    assert len(rows) == len(unc["receptors"])
    for row, rec in zip(rows, unc["receptors"], strict=True):
        assert row[0] == rec["label"]
        assert row[1] == f"{rec['deterministic_ft']:,.1f}"
        assert row[3] == f"{rec['quantiles']['0.1']['ft']:,.1f}"
        assert row[4] == f"{rec['quantiles']['0.5']['ft']:,.1f}"
        assert row[5] == f"{rec['quantiles']['0.9']['ft']:,.1f}"
        # The exceedance column the operator asked for, as a probability rather than a count of draws.
        assert row[-1] == _probability(rec["exceedance"]["50"])


def test_the_parameter_table_quotes_the_declaration_not_the_sample(built):
    """A caption saying "p10 as declared" has to be the declaration; the sample lands near it, not on it."""
    p, _ = built
    unc = p.artifacts["uncertainty"]
    ctx = build_context(p)
    t_row = next(r for r in ctx["unc"]["param_rows"] if r[0].startswith("Transmissivity"))
    assert t_row[2] == f"{round(unc['parameters']['t_ft2d']['declared_p10']):,}"
    assert t_row[2] == f"{round(T_SPREAD['p10']):,}", "the declared p10 is the operator's own number"
    assert t_row[-1] == T_SPREAD["source"]


def test_a_parameter_with_no_spread_is_shown_as_held_not_as_a_range(tmp_path):
    p = _project(tmp_path, uncertainty={"t_ft2d": T_SPREAD}, appendix=APPENDIX)
    p.run_analysis()
    unc = _uncertainty_context(p.artifacts["uncertainty"], _join)
    s_row = next(r for r in unc["param_rows"] if r[0] == "Storativity")
    assert s_row[1] == "held at the intake value"
    assert s_row[2] == "" and s_row[4] == "", "a held parameter must not be given a spread it does not have"
    assert s_row[-1] == "no spread declared"


def test_the_appendix_says_where_the_reported_value_falls(built):
    """The percentile is the point of the appendix: without it the median reads as a correction."""
    p, _ = built
    ctx = build_context(p)
    assert "Percentile of the reported value" in ctx["unc"]["receptor_header"]
    for row, rec in zip(ctx["unc"]["receptor_rows"], p.artifacts["uncertainty"]["receptors"], strict=True):
        assert row[2] == _probability(rec["deterministic_percentile"])
    # On this example the intake's T is the low end of the declared spread, so the reported value sits
    # high in the distribution and the "do not read the median as a correction" note must fire. The
    # caveat that is present unconditionally is the table note, asserted in the document test below.
    pcts = [rec["deterministic_percentile"] for rec in p.artifacts["uncertainty"]["receptors"]]
    assert all(pct > 0.65 for pct in pcts), pcts
    assert any("should not be quoted as a correction" in n for n in ctx["unc"]["notes"])


def test_the_document_carries_the_appendix_and_moves_the_review_log(built):
    """Appendix D is the uncertainty; the draft-only review log moves to E rather than being replaced."""
    from docx import Document
    _, result = built
    text = "\n".join(p.text for p in Document(result["docx"]).paragraphs)
    assert "Appendix D. Parameter uncertainty" in text
    assert "Appendix E. Review log" in text
    assert "Appendix D. Review log" not in text
    assert "Table D-1" in text and "Table D-2" in text and "Figure D-1" in text
    assert "it is not a correction to that value" in text


def test_the_same_seed_gives_the_same_appendix(tmp_path):
    """A sealed report has to be re-derivable, and the seed is in the intake precisely for that."""
    rows = []
    for name in ("first", "second"):
        p = _project(tmp_path, name, uncertainty={"t_ft2d": T_SPREAD, "s": S_SPREAD}, appendix=APPENDIX)
        p.run_analysis()
        rows.append(_uncertainty_context(p.artifacts["uncertainty"], _join)["receptor_rows"])
    assert rows[0] == rows[1]


# --------------------------------------------------------------------------------------------------
# A simulation cannot report a certainty
# --------------------------------------------------------------------------------------------------

def _probability(f: float) -> str:
    """The rule the appendix applies, restated here so the test is not the implementation."""
    return ">99%" if f >= 0.995 else ("<1%" if 0 < f < 0.005 else f"{f:.0%}")


def test_a_near_certain_probability_is_reported_as_a_bound_not_as_100_percent(built):
    """`f"{0.9997:.0%}"` is "100%", and no finite simulation establishes a 100% probability.

    On this example every well is certain to exceed 25 ft as far as 10,000 draws can tell, which is
    exactly the case that would otherwise print a certainty into a document a District files.
    """
    p, _ = built
    unc = p.artifacts["uncertainty"]
    ctx = build_context(p)
    col = ctx["unc"]["receptor_header"].index("P(drawdown > 50 ft)")
    shown = [row[col] for row in ctx["unc"]["receptor_rows"]]
    raw = [rec["exceedance"]["50"] for rec in unc["receptors"]]
    assert any(f >= 0.995 for f in raw), "the fixture no longer exercises the near-certain case"
    assert "100%" not in shown, shown
    assert ">99%" in shown
    # And a genuinely uncertain figure is still reported as the percentage it is.
    assert any(v.endswith("%") and v[0].isdigit() for v in shown), shown


def test_an_impossible_probability_is_reported_as_a_bound_too():
    """The same argument at the other end: zero of 10,000 draws is not a zero probability."""
    from hydrostudy.report.context import _uncertainty_context as ctxf
    unc = {
        "quantiles": [0.1, 0.5, 0.9], "thresholds_ft": [1000.0], "aquifer": "Evangeline",
        "scenario_title": "T", "duration_label": "1 day", "total_rate_gpm": 100.0, "draws": 1000,
        "seed": 1, "solution": {"citation": "Theis (1935)"}, "notes": [],
        "parameters": {"t_ft2d": {"declared": False, "kind": None, "source": None, "intake_value": 1.0,
                                  "declared_p10": 1.0, "declared_median": 1.0, "declared_p90": 1.0,
                                  "sample_median": 1.0, "sample_p10": 1.0, "sample_p90": 1.0},
                       "s": {"declared": False, "kind": None, "source": None, "intake_value": 1e-4,
                             "declared_p10": 1e-4, "declared_median": 1e-4, "declared_p90": 1e-4,
                             "sample_median": 1e-4, "sample_p10": 1e-4, "sample_p90": 1e-4},
                       "log_correlation": None},
        "receptors": [{"kind": "registered", "label": "Map ID 2", "deterministic_ft": 3.0,
                       "deterministic_percentile": 0.0,
                       "quantiles": {k: {"ft": 3.0, "standard_error_ft": 0.0} for k in ("0.1", "0.5", "0.9")},
                       "exceedance": {"1000": 0.0}}],
    }
    row = ctxf(unc, _join)["receptor_rows"][0]
    assert row[-1] == "0%", "a probability of exactly zero draws is reported as 0%, not <1%"
    assert row[2] == "0%"
    unc["receptors"][0]["exceedance"]["1000"] = 0.0004
    assert ctxf(unc, _join)["receptor_rows"][0][-1] == "<1%"


# --------------------------------------------------------------------------------------------------
# It must point at the right section, in both report formats
# --------------------------------------------------------------------------------------------------

def _post_project(tmp_path, name="post", uncertainty=None, appendix=None, rerun=None):
    dst = tmp_path / name
    shutil.copytree(ROOT / "examples" / "black_oak_well_2_post", dst, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    if uncertainty is not None:
        intake["aquifers"][0]["uncertainty"] = uncertainty
    if appendix is not None:
        intake.setdefault("analysis", {})["uncertainty_appendix"] = appendix
    if rerun is not None:
        intake["as_built"]["rerun_interference"] = rerun
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    return Project(dst)


def test_the_pre_drilling_appendix_qualifies_section_6(built):
    _, result = built
    from docx import Document
    text = "\n".join(x.text for x in Document(result["docx"]).paragraphs)
    assert "The drawdown figures in Section 6" in text
    assert "Section 5" not in text.split("Appendix D")[1]


def test_the_post_drilling_appendix_qualifies_section_5(tmp_path):
    """The two formats number the interference analysis differently, and the appendix follows suit.

    An appendix qualifying "Section 6" in a report whose interference analysis is Section 5 sends the
    reviewer to the water-quality section, which costs confidence in everything around it.
    """
    p = _post_project(tmp_path, uncertainty={"t_ft2d": T_SPREAD}, appendix=APPENDIX)
    p.run_analysis()
    p.run_figures()
    p.run_checklist()
    result = p.run_report(pdf=False)
    from docx import Document
    body = "\n".join(x.text for x in Document(result["docx"]).paragraphs).split("Appendix D")[1]
    assert "The drawdown figures in Section 5" in body
    assert "Section 6" not in body


def test_no_appendix_when_the_post_drilling_report_has_no_interference_section(tmp_path):
    """Without the re-run there is no section for the appendix to qualify, so it is dropped and said."""
    p = _post_project(tmp_path, uncertainty={"t_ft2d": T_SPREAD}, appendix=APPENDIX, rerun=False)
    p.run_analysis()
    assert "uncertainty" not in p.artifacts
    flag = next(f for f in p.artifacts["flags"] if f["code"] == "UNCERTAINTY_APPENDIX_UNAVAILABLE")
    assert "does not re-run the interference analysis" in flag["text"]
    assert "rerun_interference" in flag["text"], "the flag has to name the setting that would fix it"
