import pytest


def test_nearby_wells_and_spacing(black_oak_project):
    a = black_oak_project.artifacts
    nearby = a["nearby_wells"]
    assert len(nearby) == 15 and all(n["in_search_radius"] for n in nearby)
    by_owner = {n["owner"]: n for n in nearby}
    assert by_owner["Lilly"]["distance_ft"] == pytest.approx(1032, abs=15)
    assert nearby[0]["is_system_well"] and nearby[0]["map_id"] == 1
    sp = a["analysis"]["spacing"]
    assert sp["wells"][0]["required_spacing_ft"] == 770 and sp["wells"][0]["complies"]
    assert sp["wells"][0]["same_system_inside"][0]["map_id"] == 1
    assert sp["report_required"]
    assert a["geo"]["search_radius_ft"] == 2640


def test_scenarios_reproduce_report(black_oak_project):
    an = black_oak_project.artifacts["analysis"]
    res = {s["key"]: s for s in an["scenarios"]}
    w24 = res["proposed_W2_24h_1"]["results_by_aquifer"]["Evangeline"]
    assert w24["pumped_wells"][0]["total_ft"] == pytest.approx(98.7, abs=0.2)
    assert w24["pumped_wells"][0]["boundary_drawdown_ft"] == pytest.approx(53.6, abs=0.2)
    lilly = next(i for i in w24["nearby_impacts"] if i["owner"] == "Lilly")
    assert lilly["drawdown_ft"] == pytest.approx(11.2, abs=0.3)
    mx = next(s for k, s in res.items() if k.startswith("proposed_W2_max"))
    assert mx["duration_days"] == pytest.approx(52.31, abs=0.01)
    assert mx["results_by_aquifer"]["Evangeline"]["pumped_wells"][0]["total_ft"] == pytest.approx(121.5, abs=0.2)
    sysmax = next(s for k, s in res.items() if k.startswith("system_max"))
    assert sysmax["duration_days"] == pytest.approx(27.4, abs=0.01)
    pw = {p["id"]: p["total_ft"] for p in sysmax["results_by_aquifer"]["Evangeline"]["pumped_wells"]}
    assert pw["W2"] == pytest.approx(173.6, abs=1.0) and pw["W1"] == pytest.approx(168.9, abs=1.0)
    jasper = next(i for i in w24["nearby_impacts"] if i["aquifer"] == "Jasper")
    assert jasper["applicability"] == "different"
    assert an["system_interference"] and an["pumping_levels"][0]["above_screen"]


def test_water_quality_flags(black_oak_project):
    wq = black_oak_project.artifacts["water_quality"]
    assert wq["summaries"]["fe"]["n_exceed_scl"] == 1 and wq["summaries"]["al"]["n_exceed_scl"] == 1
    assert wq["summaries"]["as"]["n_exceed_mcl"] == 0
    rec = next(r for r in wq["records"] if r["constituent"] == "no2")
    assert rec["nd"] and not rec["exceeds_mcl"]


def test_aquifer_params_derivation(black_oak_project):
    p = black_oak_project.artifacts["analysis"]["aquifer_params"]["Evangeline"]
    assert p["t_ft2d"] == 1023 and p["derivations"][0]["t_ft2d"] == pytest.approx(1023, rel=0.01)
    assert p["k_ftd"] == 1.5 and not p["k_derived"]
