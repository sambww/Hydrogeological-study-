"""Post-drilling (as-built) analysis: log inventory, aquifer tests, adopted parameters, comparison to pre-drilling."""

from __future__ import annotations

import json

import numpy as np

from hydrostudy.analysis.pumptest import (
    compare_transmissivity,
    cooper_jacob_fit,
    recovery_fit,
    specific_capacity,
    step_test_fit,
    theis_fit,
)
from hydrostudy.data.las import read_las_header
from hydrostudy.data.pumptest import load_test_series


def _asdict(obj):
    if obj is None:
        return None
    d = dict(obj.__dict__)
    for k, v in d.items():
        if isinstance(v, np.ndarray):
            d[k] = v.tolist()
    return d


def analyze_as_built(project, pre_params: dict) -> dict:
    """`pre_params` are the pre-drilling aquifer parameters resolved WITHOUT review overrides (the values the
    pre-drilling report used), keyed by aquifer name."""
    intake = project.intake
    ab = intake.as_built
    well = next(w for w in intake.proposed_wells if w.id == ab.well_id)
    s_gam = pre_params[well.aquifer]["s"]
    t_pre = pre_params[well.aquifer]["t_ft2d"]
    flags = []

    # ---- logs
    logs = []
    for lg in ab.logs:
        rec = lg.model_dump()
        rec["las"] = None
        if lg.las_file:
            p = (project.dir / lg.las_file)
            rec["las_present"] = p.exists()
            if p.exists():
                rec["las"] = read_las_header(p)
        else:
            rec["las_present"] = False
        logs.append(rec)
    types = {lg.type for lg in ab.logs}
    log_summary = {
        "records": logs,
        "has_res_or_induction": bool(types & {"resistivity", "induction"}),
        "has_sp_or_gamma": bool(types & {"sp", "gamma", "spectral_gamma"}),
        "has_open_hole": any(lg.open_hole for lg in ab.logs),
        # Material is free text from the driller ("PVC SDR-17", "Sch 40 PVC"), so an exact match would let a
        # PVC-cased well past the Section III.1(c) induction-and-gamma requirement and report it as addressed.
        "pvc_ok": (not any("pvc" in (c.material or "").lower() for c in ab.construction.casing)) or ({"induction", "gamma"} <= types),
        "all_las_present": bool(ab.logs) and all(r["las_present"] for r in logs),
        "n_logs": len(ab.logs),
    }
    if not log_summary["has_res_or_induction"] or not log_summary["has_sp_or_gamma"]:
        flags.append({"level": "warn", "code": "LOGS_MINIMUM", "text": "Geophysical logs do not include the minimum resistivity/induction plus SP/gamma curves."})
    if not log_summary["all_las_present"]:
        flags.append({"level": "warn", "code": "LAS_MISSING", "text": "One or more LAS files are missing from the project folder."})

    # ---- tests
    tests = []
    for t in ab.tests:
        swl = t.swl_ft if t.swl_ft is not None else ab.static_water_level_ft
        series = load_test_series(project.dir / t.data_file, swl)
        rec = {"id": t.id, "kind": t.kind, "rate_gpm": t.rate_gpm, "r_w_ft": t.r_w_ft, "start": t.start, "notes": t.notes,
               "data_file": t.data_file, "observation_well": t.observation_well.model_dump() if t.observation_well else None,
               "swl_ft": swl, "n_rows": series.n, "cooper_jacob": None, "theis": None, "recovery": None, "step": None,
               "specific_capacity": None, "end_drawdown_ft": None, "duration_min": None, "rate_variation": series.pumping().rate_variation(),
               "series": {"elapsed_min": series.elapsed_min.tolist(), "drawdown_ft": series.drawdown_ft.tolist(),
                          "rate_gpm": None if series.rate_gpm is None else series.rate_gpm.tolist(),
                          "phase": series.phase}}
        pu = series.pumping()
        if t.kind in ("constant_rate", "recovery") and t.rate_gpm:
            r_eval = t.observation_well.distance_ft if t.observation_well else t.r_w_ft
            if t.kind == "constant_rate" and pu.n:
                rec["end_drawdown_ft"] = float(pu.drawdown_ft[-1])
                rec["duration_min"] = float(pu.elapsed_min[-1])
                rec["specific_capacity"] = specific_capacity(t.rate_gpm, float(pu.drawdown_ft[-1]))
                rec["cooper_jacob"] = _asdict(cooper_jacob_fit(pu.elapsed_min, pu.drawdown_ft, t.rate_gpm, r_eval, s_gam,
                                                               observation_well=t.observation_well is not None))
                rec["theis"] = _asdict(theis_fit(pu.elapsed_min, pu.drawdown_ft, t.rate_gpm, r_eval,
                                                 fix_s=None if t.observation_well else s_gam))
                if rec["rate_variation"] is not None and rec["rate_variation"] > 0.05:
                    flags.append({"level": "warn", "code": "RATE_VARIATION", "text": f"Test {t.id}: pumping rate varied by more than 5%; constant-rate analysis is approximate."})
            rc = series.recovery()
            if rc is not None and rc.n:
                if rc.t_since_stop_min is not None:
                    tss = rc.t_since_stop_min
                else:
                    # Without a stop time every t/t' would be identical and the fit meaningless, so say that rather
                    # than defaulting to zero and adopting whatever comes back.
                    t_stop = float(pu.elapsed_min[-1]) if pu.n else t.duration_min
                    tss = None if not t_stop else rc.elapsed_min - t_stop
                if tss is None:
                    flags.append({"level": "warn", "code": "RECOVERY_STOP_UNKNOWN",
                                  "text": f"Test {t.id}: recovery rows carry no t_since_stop_min and the pumping "
                                          "duration is not recorded, so the recovery analysis was skipped."})
                else:
                    rec["recovery"] = _asdict(recovery_fit(rc.elapsed_min, tss, rc.drawdown_ft, t.rate_gpm))
        if t.kind == "step":
            ends = []
            cum = 0.0
            for st in t.steps:
                cum += st.duration_min
                idx = int(np.argmin(np.abs(series.elapsed_min - cum)))
                ends.append((st.rate_gpm, float(series.drawdown_ft[idx])))
            rec["step"] = _asdict(step_test_fit(ends))
            rec["step"]["design_rate_gpm"] = well.max_rate_gpm
            sf = step_test_fit(ends)
            rec["step"]["efficiency_at_design"] = sf.efficiency_at(well.max_rate_gpm)
            rec["step"]["drawdown_at_design_ft"] = sf.drawdown_at(well.max_rate_gpm)
        tests.append(rec)

    # ---- adopted transmissivity
    adopted = {"t_ft2d": None, "method": None, "test_id": None, "s": s_gam, "s_source": "GAM (pre-drilling value)", "candidates": []}
    for rec in tests:
        for key, label in (("cooper_jacob", "Cooper-Jacob straight line"), ("theis", "Theis curve match"), ("recovery", "Theis recovery")):
            fit = rec.get(key)
            if fit and fit.get("t_ft2d"):
                adopted["candidates"].append({"test_id": rec["id"], "method": label, "t_ft2d": fit["t_ft2d"], "valid": fit["valid"]})
    for cand in adopted["candidates"]:
        if cand["valid"] and cand["method"].startswith("Cooper"):
            adopted.update({"t_ft2d": cand["t_ft2d"], "method": cand["method"], "test_id": cand["test_id"]})
            break
    if adopted["t_ft2d"] is None:
        for cand in adopted["candidates"]:
            if cand["valid"]:
                adopted.update({"t_ft2d": cand["t_ft2d"], "method": cand["method"], "test_id": cand["test_id"]})
                break
    if adopted["t_ft2d"] is None and adopted["candidates"]:
        c = adopted["candidates"][0]
        adopted.update({"t_ft2d": c["t_ft2d"], "method": c["method"] + " (fit flagged)", "test_id": c["test_id"]})
        flags.append({"level": "review", "code": "T_FIT_FLAGGED", "text": "No aquifer-test fit met the validity criteria; adopted value needs reviewer judgment."})
    if ab.s_source == "test":
        s_test = next((r["cooper_jacob"]["s"] for r in tests if r.get("cooper_jacob") and r["cooper_jacob"].get("s")), None)
        if s_test:
            adopted["s"], adopted["s_source"] = s_test, "observation-well Cooper-Jacob intercept"
        else:
            flags.append({"level": "warn", "code": "S_NOT_FROM_TEST", "text": "s_source is 'test' but no observation-well storativity is available; GAM value retained."})
    comparison = None
    if adopted["t_ft2d"] and t_pre:
        comparison = compare_transmissivity(adopted["t_ft2d"], t_pre) | {"t_pre_ft2d": t_pre, "t_measured_ft2d": adopted["t_ft2d"]}

    # ---- pre-drilling reference results
    pre = None
    if ab.pre_drilling_report and ab.pre_drilling_report.analysis_json:
        p = (project.dir / ab.pre_drilling_report.analysis_json)
        if p.exists():
            with open(p) as fh:
                pre_an = json.load(fh)
            pre = {"scenarios": [{"key": s["key"], "title": s["title"], "duration_label": s["duration_label"],
                                  "pumped": {q["id"]: q["total_ft"] for aq in s["results_by_aquifer"].values() for q in aq["pumped_wells"]}}
                                 for s in pre_an["scenarios"]],
                   "t_ft2d": {k: v["t_ft2d"] for k, v in pre_an["aquifer_params"].items()}}
        else:
            flags.append({"level": "info", "code": "PRE_DRILLING_JSON_MISSING", "text": f"Pre-drilling analysis file not found at {p}; comparison table omitted."})

    c = ab.construction
    table = {
        "well": well.label, "aquifer": well.aquifer, "completion_date": ab.completion_date, "tdlr_tracking_no": ab.tdlr_tracking_no,
        "swl_ft": ab.static_water_level_ft, "swl_date": ab.swl_date,
        "screen_diameters_in": sorted({s.diameter_in for s in c.screen}), "liner_diameters_in": sorted({b.diameter_in for b in c.blank_liner}),
        "screen_top_ft": min(s.top_ft for s in c.screen) if c.screen else None,
        "liner_top_ft": min(b.top_ft for b in c.blank_liner) if c.blank_liner else None,
        "first_screen_top_ft": min(s.top_ft for s in c.screen) if c.screen else None,
        "total_depth_ft": c.total_depth_ft, "pump_diameter_in": ab.pump.diameter_in, "pump_setting_ft": ab.pump.setting_ft,
        "pump_hp": ab.pump.hp, "pump_model": ab.pump.make_model,
        "screen_intervals": [(s.top_ft, s.bottom_ft, s.diameter_in, s.material, s.slot_in) for s in c.screen],
        "liner_intervals": [(b.top_ft, b.bottom_ft, b.diameter_in, b.material) for b in c.blank_liner],
        "casing_intervals": [(x.top_ft, x.bottom_ft, x.diameter_in, x.material) for x in c.casing],
        "cement_intervals": [(x.top_ft, x.bottom_ft, x.method) for x in c.cement],
        "borehole_intervals": [(x.top_ft, x.bottom_ft, x.diameter_in) for x in c.borehole],
        "packer_depth_ft": c.packer_depth_ft,
    }
    return {"well_id": ab.well_id, "aquifer": well.aquifer, "table": table, "logs": log_summary, "tests": tests,
            "adopted": adopted, "comparison": comparison, "pre_drilling": pre,
            "field_params": [f.model_dump() for f in ab.field_params], "rerun_interference": ab.rerun_interference,
            "flags": flags, "driller": ab.driller, "pre_drilling_report": ab.pre_drilling_report.model_dump() if ab.pre_drilling_report else None}
