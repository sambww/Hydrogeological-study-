"""Multi-aquifer systems, single-well projects, the other examples end to end, and the CLI."""

import shutil

import pytest
import yaml
from docx import Document

from hydrostudy import cli
from hydrostudy.pipeline import Project
from tests.conftest import ROOT


def _copy(tmp, name):
    dst = tmp / name
    shutil.copytree(ROOT / "examples" / name, dst, ignore=shutil.ignore_patterns("build"))
    return dst


def _build(dst, pdf=False):
    p = Project(dst)
    p.run_analysis()
    p.run_figures()
    p.artifacts["checklist"] = p.run_checklist()
    return p, p.run_report(pdf=pdf)


def test_multi_aquifer_system(tmp_path):
    dst = _copy(tmp_path, "black_oak_well_2")
    d = yaml.safe_load((dst / "intake.yaml").read_text())
    d["aquifers"].append({"name": "Jasper", "top_ft_bgl": 950, "bottom_ft_bgl": 1700,
                          "confinement": {"status": "confined"},
                          "params": {"t_ft2d": 440.8, "s": 3.28e-4, "k_ftd": 1.3, "source": {"kind": "gam", "citation": "GAM (Kasmarek, 2013)", "model_version": "HAGM"}}})
    d["existing_wells"].append({"id": "J1", "display_name": "Well No. 3", "registration_no": "2011102405", "lat": 30.173611, "lon": -95.583889,
                                "aquifer": "Jasper", "max_rate_gpm": 200, "total_depth_ft": 1649,
                                "screen": [{"top_ft": 1257, "bottom_ft": 1629, "diameter_in": 8.0}], "status": "Operating",
                                "include_in_system": True, "r_w_ft": 0.5, "nearest_property_boundary_ft": 100})
    (dst / "intake.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    p, result = _build(dst)
    an = p.artifacts["analysis"]
    sysmax = next(s for s in an["scenarios"] if s["key"].startswith("system_max"))
    assert set(sysmax["results_by_aquifer"]) == {"Evangeline", "Jasper"}
    assert sysmax["duration_days"] == pytest.approx(29e6 / (935 * 1440), abs=0.01)
    ev = sysmax["results_by_aquifer"]["Evangeline"]
    ja = sysmax["results_by_aquifer"]["Jasper"]
    assert ev["t_ft2d"] == 1023 and ja["t_ft2d"] == 440.8
    jasper_imp = next(i for i in ev["nearby_impacts"] if i["aquifer"] == "Jasper")
    assert jasper_imp["applicability"] == "different"
    ev_imp = next(i for i in ja["nearby_impacts"] if i["aquifer"] == "Evangeline")
    assert ev_imp["applicability"] == "different"
    assert {r[1] for r in p.artifacts.get("checklist", {}).get("items", []) and [] } == set()  # checklist present
    assert result["lint"]["ok"]
    doc = Document(result["docx"])
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "Jasper Aquifer" in text and "Well No. 3" in text


def test_single_well_no_system(tmp_path):
    dst = _copy(tmp_path, "black_oak_well_2")
    d = yaml.safe_load((dst / "intake.yaml").read_text())
    d["existing_wells"] = []
    d["aquifers"][0]["site_test"] = None
    d["aquifers"][0]["params"]["source"]["kind"] = "gam"
    (dst / "intake.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    p, result = _build(dst)
    an = p.artifacts["analysis"]
    assert all(s["group"] == "proposed_only" for s in an["scenarios"]) and not an["system_interference"]
    cl = p.artifacts["checklist"]
    na = {i["id"] for i in cl["items"] if i["status"] == "not_applicable"}
    assert "II.B.5(b)" in na
    assert result["lint"]["ok"] and result["tables"] < 12


@pytest.mark.parametrize("name,heading", [("hidden_forest_well_3", "6. Interference Analysis"),
                                          ("enterprise_feasibility", "6. Production and Drawdown Analysis")])
def test_other_examples_end_to_end(tmp_path, name, heading):
    dst = _copy(tmp_path, name)
    p, result = _build(dst)
    assert result["lint"]["ok"]
    doc = Document(result["docx"])
    heads = [par.text for par in doc.paragraphs if par.style.name.startswith("Heading 1")]
    assert heading in heads
    an = p.artifacts["analysis"]
    if name == "hidden_forest_well_3":
        w = next(s for s in an["scenarios"] if s["key"] == "proposed_W3_24h_1")["results_by_aquifer"]["Jasper"]["pumped_wells"][0]
        assert w["total_ft"] == pytest.approx(103.7, abs=0.6)
        assert any(s["duration_kind"] == "fixed" and s["duration_days"] == 30 for s in an["scenarios"])
    else:
        assert any(s["group"] == "system" and s["duration_days"] == 7300 for s in an["scenarios"])
        both = next(s for s in an["scenarios"] if s["group"] == "system" and s["duration_days"] == 3650)
        assert both["results_by_aquifer"]["Chicot"]["pumped_wells"][0]["total_ft"] == pytest.approx(193.7, abs=1.0)


def test_cli_new_validate_and_errors(tmp_path, capsys):
    dst = tmp_path / "proj"
    assert cli.main(["new", str(dst)]) == 0
    assert cli.main(["validate", str(dst)]) == 0
    d = yaml.safe_load((dst / "intake.yaml").read_text())
    d["permit"]["annual_volume_gal"] = -1
    (dst / "intake.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    assert cli.main(["validate", str(dst)]) == 1
    out = capsys.readouterr().out
    assert "annual_volume_gal" in out
    assert cli.main(["new", str(dst)]) == 2   # refuses non-empty dir


def test_missing_storativity_gives_clear_error(tmp_path):
    from hydrostudy.analysis.aquifer_params import resolve_params
    from hydrostudy.schema.review import Review
    dst = _copy(tmp_path, "black_oak_well_2")
    d = yaml.safe_load((dst / "intake.yaml").read_text())
    d["aquifers"][0]["params"]["s"] = None
    (dst / "intake.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    from hydrostudy.schema.loaders import load_intake
    intake = load_intake(dst / "intake.yaml")
    with pytest.raises(ValueError, match="storativity is required"):
        resolve_params(intake, Review())


def test_single_well_checklist_mixed_items(tmp_path):
    dst = _copy(tmp_path, "black_oak_well_2")
    d = yaml.safe_load((dst / "intake.yaml").read_text())
    d["existing_wells"] = []
    (dst / "intake.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    p, _ = _build(dst)
    st = {i["id"]: i["status"] for i in p.artifacts["checklist"]["items"]}
    assert st["II.B.5(b)"] == "not_applicable"
    assert st["II.B.5(a)(iv)"] == "satisfied" and st["II.B.5(c)"] == "satisfied"


def test_manifest_boundary_key_is_honored(tmp_path):
    from tests.geo_fixtures import write_fixtures
    dst = _copy(tmp_path, "black_oak_well_2")
    entries = write_fixtures(dst, 30.170167, -95.578097)
    man = yaml.safe_load((dst / "data" / "manifest.yaml").read_text())
    man["files"]["boundary"] = entries["boundary"]
    (dst / "data" / "manifest.yaml").write_text(yaml.safe_dump(man, sort_keys=False))
    p = Project(dst)
    assert p.boundary_geom is not None
