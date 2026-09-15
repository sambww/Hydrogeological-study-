"""The web intake form's submissions must land as a working project, not just a syntactically valid file.

The strongest check available is the regression example: the Black Oak intake is exactly the shape the form emits, so
feeding it through the importer and running the pipeline must reproduce the District-accepted drawdown. If a submission
cannot do that, the form is not finished.
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hydrostudy.intake_import import load_payload, prune, split_payload, write_intake

ROOT = Path(__file__).resolve().parents[1]
BLACK_OAK = ROOT / "examples" / "black_oak_well_2"


def _payload():
    return yaml.safe_load((BLACK_OAK / "intake.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------------- pruning

def test_blank_optional_answers_are_dropped_so_defaults_apply():
    """An untouched number field arrives as "", which pydantic must never see."""
    out = prune({"a": "", "b": "  ", "c": None, "d": {}, "e": [], "f": "kept"})
    assert out == {"f": "kept"}


def test_false_and_zero_are_real_answers_and_survive():
    out = prune({"include_in_system": False, "top_ft": 0, "spacing_exception_requested": False})
    assert out == {"include_in_system": False, "top_ft": 0, "spacing_exception_requested": False}


def test_pruning_reaches_into_nested_rows():
    out = prune({"wells": [{"id": "W1", "slot_in": ""}, {}], "site": {"address": None}})
    assert out == {"wells": [{"id": "W1"}]}


def test_form_metadata_is_split_off_before_validation():
    data, meta = split_payload({"_form": {"slug": "black-oak", "submitted_at": "2026-09-14"}, "mode": "feasibility"})
    assert meta["slug"] == "black-oak"
    assert "_form" not in data


# ------------------------------------------------------------------------------------------------------- writing

def test_writes_intake_and_scaffolds_supporting_files(tmp_path):
    target = write_intake(tmp_path / "proj", _payload())
    assert target.exists()
    for rel in ("review.yaml", "data/manifest.yaml", "data/district_wells.csv",
                "data/water_quality_samples.csv"):
        assert (tmp_path / "proj" / rel).exists(), rel


def test_written_file_keeps_the_operator_input_including_dms_coordinates(tmp_path):
    target = write_intake(tmp_path / "proj", _payload())
    text = target.read_text(encoding="utf-8")
    assert "30° 10' 12.60\"" in text          # not normalised to a decimal degree
    assert text.startswith("# Written by 'hydrostudy import-intake'")
    loaded = yaml.safe_load(text)
    assert loaded["proposed_wells"][0]["id"] == "W2"


def test_header_records_who_submitted_and_when(tmp_path):
    payload = _payload()
    payload["_form"] = {"slug": "black-oak-2", "submitted_at": "2026-09-14T12:00:00Z", "entered_by": "front office"}
    text = write_intake(tmp_path / "proj", payload).read_text(encoding="utf-8")
    assert "black-oak-2" in text and "front office" in text


def test_refuses_to_overwrite_without_force(tmp_path):
    write_intake(tmp_path / "proj", _payload())
    with pytest.raises(FileExistsError):
        write_intake(tmp_path / "proj", _payload())
    assert write_intake(tmp_path / "proj", _payload(), force=True).exists()


def test_invalid_submission_raises_and_leaves_no_file(tmp_path):
    payload = _payload()
    payload["proposed_wells"][0]["lon"] = 95.578097        # east longitude: a real and easy operator mistake
    with pytest.raises(ValidationError):
        write_intake(tmp_path / "proj", payload)
    assert not (tmp_path / "proj" / "intake.yaml").exists()


def test_construction_geometry_is_still_enforced(tmp_path):
    payload = _payload()
    payload["proposed_wells"][0]["screen"][0]["bottom_ft"] = 9999
    with pytest.raises(ValidationError):
        write_intake(tmp_path / "proj", payload)


def test_load_payload_rejects_a_json_array(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_payload(p)


def test_load_payload_reads_a_submission_object(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps(_payload()), encoding="utf-8")
    assert load_payload(p)["proposed_wells"][0]["id"] == "W2"


# ------------------------------------------------------------------------------------------------- the real proof

def test_submission_reproduces_the_district_accepted_report(tmp_path):
    proj = tmp_path / "black_oak_from_form"
    write_intake(proj, _payload())
    shutil.copytree(BLACK_OAK / "data", proj / "data", dirs_exist_ok=True)

    from hydrostudy.pipeline import Project
    p = Project(proj)
    p.run_analysis()
    res = {s["key"]: s for s in p.artifacts["analysis"]["scenarios"]}
    w24 = res["proposed_W2_24h_1"]["results_by_aquifer"]["Evangeline"]
    assert w24["pumped_wells"][0]["total_ft"] == pytest.approx(98.7, abs=0.2)
    assert p.artifacts["analysis"]["spacing"]["wells"][0]["required_spacing_ft"] == 770
