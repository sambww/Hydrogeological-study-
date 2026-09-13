import json
import shutil

import numpy as np
import pytest
import yaml
from docx import Document

from hydrostudy.pipeline import Project
from tests.conftest import ROOT


def _lookup():
    n = 7
    base = np.full((n, n), 1231.2)
    base[3, 3] = 1231.2
    base[0, :] = 900.0
    return {"model": "Houston Area Groundwater Model", "version": "HAGM v1.1", "source": "HAGM (Kasmarek, 2013), hand-made test lookup",
            "generated": "2026-01-01", "site": {"lat": 30.170167, "lon": -95.578097, "row": 50, "col": 80}, "cell_size_ft": 5280,
            "layers": [{"name": "Chicot", "top_ft_bgl": 0, "bottom_ft_bgl": 260, "thickness_ft": 260, "k_ftd": 6.0, "t_ft2d": 1560, "s": 2e-3},
                       {"name": "Evangeline", "top_ft_bgl": 260, "bottom_ft_bgl": 944, "thickness_ft": 684, "k_ftd": 1.8, "t_ft2d": 1231.2, "s": 3.36e-4}],
            "neighborhood": {"half_cells": 3, "x0_ft": -3.5 * 5280, "y0_ft": -3.5 * 5280, "dx_ft": 5280, "dy_ft": 5280,
                             "values": {"Evangeline": {"t": base.tolist(), "k": (base / 684).tolist(), "s": np.full((n, n), 3.36e-4).tolist()}}}}


@pytest.fixture(scope="module")
def gam_project(tmp_path_factory):
    dst = tmp_path_factory.mktemp("gam") / "black_oak_well_2"
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    (dst / "data" / "gam_lookup.json").write_text(json.dumps(_lookup()))
    man = yaml.safe_load((dst / "data" / "manifest.yaml").read_text())
    man["files"]["gam_lookup"] = {"path": "gam_lookup.json", "source": "HAGM (Kasmarek, 2013) sampled by scripts/build_gam_lookup.py (test)", "retrieved": "2026-01-01"}
    (dst / "data" / "manifest.yaml").write_text(yaml.safe_dump(man, sort_keys=False))
    intake = yaml.safe_load((dst / "intake.yaml").read_text())
    # rely on the lookup for everything except the site-test transmissivity
    aq = intake["aquifers"][0]
    aq["top_ft_bgl"] = None
    aq["bottom_ft_bgl"] = None
    aq["source"] = None
    aq["params"] = {"t_ft2d": None, "s": None, "k_ftd": None, "source": {"kind": "gam", "citation": "", "model_version": None}}
    aq["site_test"] = None
    (dst / "intake.yaml").write_text(yaml.safe_dump(intake, sort_keys=False))
    p = Project(dst)
    p.run_analysis()
    p.run_figures()
    p.artifacts["checklist"] = p.run_checklist()
    return p, p.run_report(pdf=False)


def test_params_from_lookup(gam_project):
    p, _ = gam_project
    ev = p.artifacts["analysis"]["aquifer_params"]["Evangeline"]
    assert ev["t_ft2d"] == pytest.approx(1231.2) and ev["s"] == pytest.approx(3.36e-4)
    assert ev["top_ft_bgl"] == 260 and ev["bottom_ft_bgl"] == 944 and ev["k_ftd"] == pytest.approx(1.8)
    assert "HAGM" in ev["citation"] and ev["gam_note"].startswith("transmissivity from")
    w = p.artifacts["analysis"]["scenarios"][0]["results_by_aquifer"]["Evangeline"]["pumped_wells"][0]
    assert w["total_ft"] < 98.7   # higher T than the site test -> less drawdown


def test_gam_figures_and_report(gam_project):
    p, result = gam_project
    figs = p.artifacts["figures"]
    assert {"gam_t_Evangeline", "gam_k_Evangeline", "gam_s_Evangeline"} <= set(figs)
    assert result["lint"]["ok"]
    doc = Document(result["docx"])
    caps = [par.text for par in doc.paragraphs if par.text.startswith("Figure ") and "transmissivity near" in par.text]
    assert caps and "HAGM" in caps[0]


def test_gam_mismatch_flag(tmp_path):
    dst = tmp_path / "black_oak_well_2"
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", dst, ignore=shutil.ignore_patterns("build"))
    lk = _lookup()
    lk["layers"][1]["t_ft2d"] = 3000.0
    (dst / "data" / "gam_lookup.json").write_text(json.dumps(lk))
    man = yaml.safe_load((dst / "data" / "manifest.yaml").read_text())
    man["files"]["gam_lookup"] = {"path": "gam_lookup.json", "source": "test"}
    (dst / "data" / "manifest.yaml").write_text(yaml.safe_dump(man, sort_keys=False))
    p = Project(dst)
    p.run_analysis()
    assert p.artifacts["analysis"]["aquifer_params"]["Evangeline"]["t_ft2d"] == 1023   # stated value wins
    assert "GAM_MISMATCH" in {f["code"] for f in p.artifacts["flags"]}
