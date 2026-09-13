import shutil

import pytest
import yaml

from hydrostudy.pipeline import Project
from tests.conftest import ROOT
from tests.geo_fixtures import write_fixtures


@pytest.fixture(scope="module")
def geo_project(tmp_path_factory):
    dst = tmp_path_factory.mktemp("geo") / "black_oak_well_2"
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    lat, lon = 30.170167, -95.578097
    entries = write_fixtures(dst, lat, lon)
    man = yaml.safe_load((dst / "data" / "manifest.yaml").read_text())
    man["files"].update(entries)
    man["hydrography_notes"] = []
    man["springs"] = {"searched": True, "source": "fixture list", "found": []}
    (dst / "data" / "manifest.yaml").write_text(yaml.safe_dump(man, sort_keys=False))
    intake["site"]["boundary_geojson"] = "data/boundary.geojson"
    intake["site"]["nearest_boundary_distance_ft"] = None
    intake["proposed_wells"][0]["nearest_property_boundary_ft"] = None
    intake["existing_wells"][0]["nearest_property_boundary_ft"] = 500   # deliberately wrong -> mismatch flag
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()
    p.run_figures()
    return p


def test_boundary_polygon_fills_distance(geo_project):
    p = geo_project
    assert p.boundary_geom is not None
    bd = p.artifacts["geo"]["boundary_distances"]
    assert bd["W2"]["source"] == "boundary polygon" and abs(bd["W2"]["ft"] - 25) < 1.5
    assert bd["W1"]["source"] == "intake" and "polygon_ft" in bd["W1"]
    codes = [f["code"] for f in p.artifacts["flags"]]
    assert "BOUNDARY_DISTANCE_MISMATCH" in codes
    sc = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]["pumped_wells"][0]
    assert abs(sc["boundary_distance_ft"] - 25) < 1.5 and sc["boundary_drawdown_ft"] == pytest.approx(53.6, abs=0.5)


def test_hydrography_features_and_springs(geo_project):
    h = geo_project.artifacts["hydrography"]
    names = {f["name"] for f in h["features"]}
    assert names == {"Test Creek", "Test Pond"}          # "Far Creek" is beyond 1 mile
    assert h["has_geometry"] and h["springs_searched"]
    assert any(s.startswith("Test Spring") for s in h["springs_found"]) and not any("Far" in s for s in h["springs_found"])


def test_maps_use_layers(geo_project):
    figs = geo_project.artifacts["figures"]
    assert figs["location"]["has_county"] and figs["property"]["has_parcels"]
    for k in ("wells", "property", "location", "dd_proposed_W2_24h_1_Evangeline"):
        assert figs[k]["path"].endswith(".png")


def test_geojson_report_builds(geo_project):
    p = geo_project
    p.artifacts["checklist"] = p.run_checklist()
    result = p.run_report(pdf=False)
    assert result["lint"]["ok"]
    assert all(i["status"] == "satisfied" for i in p.artifacts["checklist"]["items"] if i["id"] in ("II.B.2(c)", "II.B.3(i)"))
