import math
import shutil

import numpy as np
import pytest
from docx import Document

from hydrostudy.analysis.pumptest import (
    cooper_jacob_fit,
    recovery_fit,
    specific_capacity,
    step_test_fit,
    theis_fit,
)
from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.data.las import read_las_header
from hydrostudy.data.pumptest import load_test_series
from tests.conftest import ROOT

T, S, RW, Q = 1023.0, 3.36e-4, 0.5, 385.0


def _synthetic(noise=0.0, c_loss=0.0, seed=1):
    rng = np.random.default_rng(seed)
    t = np.unique(np.concatenate([np.arange(1, 10), np.arange(10, 100, 10), np.arange(100, 2161, 60)]))
    s = theis_drawdown(Q, T, S, RW, t / 1440) + c_loss * Q**2 + rng.normal(0, noise, len(t))
    return t, s


def test_cooper_jacob_recovers_T():
    t, s = _synthetic(noise=0.15, c_loss=2e-5)
    fit = cooper_jacob_fit(t, s, Q, RW, S)
    assert fit.valid and abs(fit.t_ft2d - T) / T < 0.03
    assert fit.s is None and "not determinable" in fit.s_reason
    assert fit.u_max < 0.01 and fit.r2 > 0.99


def test_cooper_jacob_observation_well_gives_S():
    r_obs = 500.0
    t = np.arange(10, 10 * 1440, 30)   # 10 days so that u < 0.01 is reached
    s = theis_drawdown(Q, T, S, r_obs, t / 1440)
    fit = cooper_jacob_fit(t, s, Q, r_obs, S, observation_well=True)
    assert abs(fit.t_ft2d - T) / T < 0.02
    assert abs(fit.s - S) / S < 0.10


def test_cooper_jacob_rejects_bad_data():
    fit = cooper_jacob_fit([1, 2, 3], [1, 2, 3], Q, RW, S)
    assert not fit.valid and fit.t_ft2d is None


def test_theis_fit_recovers_T():
    t, s = _synthetic(noise=0.1)
    fit = theis_fit(t, s, Q, RW, fix_s=S)
    assert fit.valid and abs(fit.t_ft2d - T) / T < 0.02 and fit.s_fixed
    free = theis_fit(t, s, Q, RW)
    assert abs(free.t_ft2d - T) / T < 0.05


def test_recovery_fit_recovers_T():
    t_stop = 2160.0
    tp = np.arange(1, 721, 5.0)
    tt = t_stop + tp
    sp = theis_drawdown(Q, T, S, RW, tt / 1440) - theis_drawdown(Q, T, S, RW, tp / 1440)
    fit = recovery_fit(tt, tp, sp, Q)
    assert fit.valid and abs(fit.t_ft2d - T) / T < 0.05


def test_step_test_fit_recovers_B_and_C():
    B, C = 0.25, 2e-5
    steps = [(q, B * q + C * q * q) for q in (200, 300, 385)]
    fit = step_test_fit(steps)
    assert fit.b_ft_per_gpm == pytest.approx(B, rel=1e-6) and fit.c_ft_per_gpm2 == pytest.approx(C, rel=1e-6)
    eff = fit.efficiency_at(385)
    assert eff == pytest.approx(B * 385 / (B * 385 + C * 385**2))
    two = step_test_fit(steps[:2])
    assert two.valid and two.r2 is None


def test_specific_capacity():
    assert specific_capacity(270, 434.9 - 364) == pytest.approx(3.808, abs=0.01)
    with pytest.raises(ValueError):
        specific_capacity(100, 0)


def test_load_test_series_water_levels_and_phases(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("elapsed_min,water_level_ft,phase\n10,360,pumping\n5,358,pumping\n2200,356,recovery\n")
    ts = load_test_series(p, 352)
    assert ts.elapsed_min.tolist() == [5, 10, 2200] and ts.drawdown_ft.tolist() == [6, 8, 4]
    assert ts.pumping().n == 2 and ts.recovery().n == 1
    with pytest.raises(ValueError):
        load_test_series(p, None)


def test_las_header_parser(tmp_path):
    p = tmp_path / "x.las"
    p.write_text("~V\n VERS. 2.0 : v\n~W\n STRT.FT 0.0 : start\n STOP.FT 100.0 : stop\n~C\n DEPT.FT : depth\n GR.GAPI : gamma\n~A\n0 1\n0.5 2\n")
    h = read_las_header(p)
    assert h["ok"] and h["version"] == "2.0" and h["stop"] == 100.0
    assert [c["mnemonic"] for c in h["curves"]] == ["DEPT", "GR"] and h["n_data_rows"] == 2


@pytest.fixture(scope="module")
def post_built(tmp_path_factory):
    from hydrostudy.pipeline import Project
    root = tmp_path_factory.mktemp("post")
    shutil.copytree(ROOT / "examples" / "black_oak_well_2", root / "black_oak_well_2", ignore=shutil.ignore_patterns("build"))
    shutil.copytree(ROOT / "examples" / "black_oak_well_2_post", root / "black_oak_well_2_post", ignore=shutil.ignore_patterns("build"))
    pre = Project(root / "black_oak_well_2")
    pre.run_analysis()
    p = Project(root / "black_oak_well_2_post")
    p.run_analysis()
    p.run_figures()
    p.artifacts["checklist"] = p.run_checklist()
    result = p.run_report(pdf=False)
    return p, result


def test_post_analysis_and_report(post_built):
    p, result = post_built
    ab = p.artifacts["as_built"]
    assert abs(ab["adopted"]["t_ft2d"] - T) / T < 0.03 and ab["adopted"]["method"].startswith("Cooper")
    assert ab["comparison"]["relation"] == "consistent with"
    assert ab["logs"]["has_res_or_induction"] and ab["logs"]["has_sp_or_gamma"] and ab["logs"]["all_las_present"]
    assert ab["pre_drilling"] and ab["pre_drilling"]["t_ft2d"]["Evangeline"] == 1023
    assert "T" in p.artifacts["analysis"]["aquifer_params"]["Evangeline"]["review_overrides"]
    assert result["lint"]["ok"]
    doc = Document(result["docx"])
    heads = [par.text for par in doc.paragraphs if par.style.name.startswith("Heading 1")]
    expected = ["1. As-Built Well Construction", "2. Geophysical Logs", "3. Aquifer Testing", "4. Water Quality",
                "5. Updated Interference Analysis", "6. Summary and Professional Opinion", "References"]
    idx = [heads.index(h) for h in expected]
    assert idx == sorted(idx)
    cl = p.artifacts["checklist"]
    assert {i["id"] for i in cl["items"]} >= {"III.1(a)", "III.3", "III.4", "III.5", "III.6"}
    assert all(i["status"] == "satisfied" for i in cl["items"] if i["id"] != "III.2")
    assert math.isclose(p.artifacts["analysis"]["aquifer_params"]["Evangeline"]["t_ft2d"], ab["adopted"]["t_ft2d"])


def test_pre_drilling_reference_ignores_review_overrides(tmp_path_factory):
    """The as-built comparison must be against the pre-drilling intake value, not a reviewer override."""
    import shutil as _sh

    import yaml as _yaml

    from hydrostudy.pipeline import Project as _P
    root = tmp_path_factory.mktemp("post2")
    _sh.copytree(ROOT / "examples" / "black_oak_well_2_post", root / "p", ignore=_sh.ignore_patterns("build"))
    (root / "p" / "review.yaml").write_text(_yaml.safe_dump({"reviewer": {"status": "draft"}, "decisions": {"t_ft2d": {"Evangeline": 1500}}, "opinions": {}, "notes": []}))
    d = _yaml.safe_load((root / "p" / "intake.yaml").read_text())
    d["as_built"]["pre_drilling_report"]["analysis_json"] = None
    (root / "p" / "intake.yaml").write_text(_yaml.safe_dump(d, sort_keys=False))
    p = _P(root / "p")
    p.run_analysis()
    assert p.artifacts["as_built"]["comparison"]["t_pre_ft2d"] == 1023
