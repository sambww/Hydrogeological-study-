"""A review submission must become a review.yaml the report actually honours.

The end-to-end test here is the one that matters: a filled review has to clear every placeholder and, when the
reviewer overrides a parameter, change the numbers the report prints.
"""

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hydrostudy.review_import import payload_to_review, write_review

ROOT = Path(__file__).resolve().parents[1]
BLACK_OAK = ROOT / "examples" / "black_oak_well_2"

OPINION_KEYS = ("conclusion", "lithology_basis", "recharge_features", "confinement", "water_quality",
                "aquifer_identification", "parameter_selection", "spacing")


def _payload(**over):
    p = {
        "reviewer": {"name": "A. Geoscientist", "license_type": "P.G.", "license_no": "12345",
                     "firm": "Example Geoscience", "status": "reviewed"},
        "decisions": {},
        # Deliberately free of figures: a reviewer citing an untraceable number is covered in test_report.py.
        "opinions": {k: "Confirmed by the undersigned on review of the draft and the supporting data."
                     for k in OPINION_KEYS},
        "notes": ["Reviewed against the driller's design."],
        "_form": {"slug": "review-black-oak-r1", "submitted_at": "2026-09-14T01:00:00Z",
                  "reviewer": "A. Geoscientist"},
    }
    p.update(over)
    return p


def test_payload_validates_and_keeps_the_reviewers_prose(tmp_path):
    review, data, meta = payload_to_review(_payload())
    assert review.reviewer.license_type == "P.G."
    assert review.reviewer.status == "reviewed"
    assert data["opinions"]["conclusion"].startswith("Confirmed by the undersigned")
    assert meta["slug"] == "review-black-oak-r1"


def test_writes_review_yaml_with_a_header_naming_the_submission(tmp_path):
    target = write_review(tmp_path, _payload())
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# Written by 'hydrostudy import-review'")
    assert "A. Geoscientist" in text
    loaded = yaml.safe_load(text)
    assert loaded["reviewer"]["status"] == "reviewed"
    assert loaded["notes"] == ["Reviewed against the driller's design."]


def test_refuses_to_overwrite_without_force(tmp_path):
    write_review(tmp_path, _payload())
    with pytest.raises(FileExistsError):
        write_review(tmp_path, _payload())
    assert write_review(tmp_path, _payload(), force=True).exists()


def test_a_bad_licence_type_is_rejected_and_writes_nothing(tmp_path):
    bad = _payload()
    bad["reviewer"]["license_type"] = "P.Eng"
    with pytest.raises(ValidationError):
        write_review(tmp_path, bad)
    assert not (tmp_path / "review.yaml").exists()


def test_a_bad_status_is_rejected(tmp_path):
    bad = _payload()
    bad["reviewer"]["status"] = "sealed"
    with pytest.raises(ValidationError):
        write_review(tmp_path, bad)


def test_blank_entries_do_not_become_nulls(tmp_path):
    sparse = _payload(reviewer={"name": "A. Geoscientist", "title": "", "license_no": None, "status": "draft"})
    loaded = yaml.safe_load(write_review(tmp_path, sparse).read_text(encoding="utf-8"))
    assert "title" not in loaded["reviewer"] and "license_no" not in loaded["reviewer"]


def test_a_review_clears_the_placeholders_and_applies_an_override(tmp_path):
    """The whole point of the sheet: what the reviewer sends changes the document."""
    proj = tmp_path / "reviewed"
    shutil.copytree(BLACK_OAK, proj)
    shutil.rmtree(proj / "build", ignore_errors=True)
    write_review(proj, _payload(decisions={"t_ft2d": {"Evangeline": 1100}}), force=True)

    from hydrostudy.pipeline import Project
    p = Project(proj)
    p.run_analysis()
    p.run_figures()
    p.artifacts["checklist"] = p.run_checklist()
    result = p.run_report(pdf=False)

    assert result["lint"]["ok"]
    assert result["placeholders"] == [], "a filled review should leave nothing for the P.G. to provide"
    assert Path(result["docx"]).name == "report_v1_reviewed.docx"

    params = p.artifacts["analysis"]["aquifer_params"]["Evangeline"]
    assert params["t_ft2d"] == pytest.approx(1100)
    assert "T" in params["review_overrides"]

    # A higher transmissivity must reduce drawdown: the override reached the analysis, not just the file.
    scenarios = {s["key"]: s for s in p.artifacts["analysis"]["scenarios"]}
    drawdown = scenarios["proposed_W2_24h_1"]["results_by_aquifer"]["Evangeline"]["pumped_wells"][0]["total_ft"]
    assert drawdown < 98.7
