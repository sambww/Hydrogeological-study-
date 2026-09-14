"""The review sheet must describe the draft in front of the reviewer, and every review field must be collectable.

The sheet is generated per project on purpose: a sealed report is reviewed against one specific build, and the number
check it performs is only meaningful against that build's own allowed set.
"""

import json
import re
from pathlib import Path

import pytest

from hydrostudy.review_sheet import OPINION_META, SheetNotReady, build_sheet_context, render_sheet
from hydrostudy.schema.review import Decisions, Opinions, Review, Reviewer

ROOT = Path(__file__).resolve().parents[1]
BLACK_OAK = ROOT / "examples" / "black_oak_well_2"


def _block(html, block_id):
    pattern = r'<script type="application/json" id="' + re.escape(block_id) + r'">(.*?)</script>'
    m = re.search(pattern, html, re.S)
    assert m, f"the sheet has no {block_id} block"
    return json.loads(m.group(1))


@pytest.fixture(scope="module")
def built_project(black_oak_project):
    """The example with a full build on disk, which is what the sheet reads."""
    p = black_oak_project
    if not (BLACK_OAK / "build" / "report.json").exists():
        p.run_figures()
        p.run_checklist()
        p.run_report(pdf=False)
    return BLACK_OAK


@pytest.fixture(scope="module")
def context(built_project):
    return build_sheet_context(built_project)


@pytest.fixture(scope="module")
def html(built_project, tmp_path_factory):
    out = tmp_path_factory.mktemp("sheet") / "review_sheet.html"
    return render_sheet(built_project, out).read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------ drift guards

def test_opinion_metadata_covers_exactly_the_schema_opinions():
    """Add an opinion to the schema and this fails, rather than the sheet quietly not asking for it."""
    assert set(OPINION_META) == set(Opinions.model_fields)


def test_every_opinion_has_a_prompt_and_a_guideline_reference():
    for key, meta in OPINION_META.items():
        assert meta["label"] and meta["prompt"], key
        assert meta["guideline"].startswith(("I.", "II.", "III.")), (key, meta["guideline"])


def test_every_review_field_is_collectable(html, context):
    """Review has no required fields, so a required-only check would assert nothing: demand all of them."""
    spec = {f["p"] for f in _block(html, "field-spec")}
    spec |= {"opinions." + o["key"] for o in _block(html, "sheet-context")["opinions"]}
    expected = {f"reviewer.{k}" for k in Reviewer.model_fields}
    expected |= {f"decisions.{k}" for k in Decisions.model_fields}
    expected |= {f"opinions.{k}" for k in Opinions.model_fields}
    expected |= {k for k in Review.model_fields if k not in ("reviewer", "decisions", "opinions")}
    missing = sorted(expected - spec)
    assert not missing, f"the sheet cannot collect: {missing}"


def test_every_control_names_a_real_review_field(html):
    known = {f"reviewer.{k}" for k in Reviewer.model_fields} | {f"decisions.{k}" for k in Decisions.model_fields} \
        | {f"opinions.{k}" for k in Opinions.model_fields} | set(Review.model_fields)
    unknown = sorted(f["p"] for f in _block(html, "field-spec") if f["p"] not in known)
    assert not unknown, f"the sheet collects field(s) that do not exist: {unknown}"


# ------------------------------------------------------------------------------------------------ context

def test_sheet_refuses_when_there_is_no_draft_to_review(tmp_path):
    with pytest.raises(SheetNotReady) as e:
        build_sheet_context(tmp_path)
    assert "hydrostudy run" in str(e.value)


def test_context_identifies_the_exact_draft(context):
    p = context["project"]
    assert p["docx"] == "report_v1_draft.docx"
    assert p["revision"] == 1 and p["status"] == "draft"
    assert p["county"] == "Montgomery"


def test_context_marks_which_opinions_are_still_placeholders(context):
    by_key = {o["key"]: o for o in context["opinions"]}
    assert by_key["conclusion"]["pending"] is True
    # Black Oak's example review supplies this one, so it is not pending.
    assert by_key["lithology_basis"]["pending"] is False
    assert by_key["lithology_basis"]["current"]


def test_context_shows_the_draft_wording_an_opinion_replaces(context):
    by_key = {o["key"]: o for o in context["opinions"]}
    assert any("II.B.3(a)" in t for t in by_key["aquifer_identification"]["draft_text"])
    # A section holding exactly one placeholder is matched even when the prose cites no guideline number.
    assert by_key["water_quality"]["draft_text"]


def test_context_carries_the_parameters_a_decision_would_override(context):
    aq = {a["name"]: a for a in context["aquifers"]}["Evangeline"]
    assert aq["t_ft2d"] == pytest.approx(1023, abs=1)
    assert aq["s"] == pytest.approx(3.36e-4, rel=1e-3)
    assert aq["source_kind"] == "site_test"
    assert {w["id"] for w in context["wells"]} == {"W2", "W1"}
    assert all(w["r_w_ft"] for w in context["wells"])


def test_context_carries_the_flags_and_open_checklist_items(context):
    assert context["flags"], "the reviewer should see what the pipeline raised"
    assert all(f["level"] in ("review", "warn") for f in context["flags"])
    assert {i["id"] for i in context["checklist"]} >= {"II.B.3(a)", "II.B.3(b)"}


def test_context_carries_the_builds_allowed_numbers(context):
    allowed = set(context["allowed_numbers"])
    assert "98.7" in allowed          # a drawdown the report computes
    assert "770" in allowed           # the spacing distance
    assert "4321" not in allowed      # nothing invented


def test_rendered_sheet_embeds_the_context_and_no_template_marker(html):
    assert "__CONTEXT__" not in html
    assert _block(html, "sheet-context")["project"]["docx"] == "report_v1_draft.docx"


def test_sheet_reaches_every_capability_through_the_guarded_helper(html):
    direct = re.findall(r"(?<!function )claude\.use\(", html)
    assert len(direct) == 1, "capability access should go through the single cap() helper"
    assert 'await cap("db")' in html and 'await cap("downloads")' in html
