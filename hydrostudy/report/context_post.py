"""Context for the post-drilling report: as-built, logs, tests, comparison; reuses the pre-drilling context for
water quality and (optionally) the re-run interference scenarios."""

from __future__ import annotations

from hydrostudy.report.context import _join, build_context, frac_in, long_date, scenario_groups
from hydrostudy.units import fmt_ft, fmt_int, fmt_sci

LOG_LABELS = {"resistivity": "resistivity", "induction": "induction", "sp": "spontaneous potential", "gamma": "gamma ray",
              "spectral_gamma": "spectral gamma ray", "caliper": "caliper", "sonic": "sonic", "other": "other"}


def assign_numbers_post(project):
    figs = project.artifacts["figures"]
    a = project.artifacts["analysis"]
    ab = project.artifacts["as_built"]
    order = ["schematic_asbuilt"]
    for t in ab["tests"]:
        order += [f"cj_{t['id']}", f"theis_{t['id']}", f"recovery_{t['id']}", f"step_{t['id']}"]
    order += [k for k in ("wq_tds", "wq_fe", "wq_as", "wq_ra_combined") if k in figs]
    if ab["rerun_interference"]:
        for sc in a["scenarios"]:
            for aq in sc["results_by_aquifer"]:
                order.append(f"dd_{sc['key']}_{aq}")
        order.append("distance_drawdown")
    fignum = {k: i + 1 for i, k in enumerate([k for k in order if k in figs])}
    tables = ["asbuilt", "logs", "tests", "field"]
    wq = project.artifacts["water_quality"]
    if wq["n_records"]:
        tables += ["wq_radionuclides", "wq_panel"]
    if ab["rerun_interference"]:
        tables.append("comparison")
        for g in scenario_groups(project):
            tables += [f"summary_{g['key']}", f"edges_{g['key']}", f"impacts_{g['key']}"]
            if g["key"] == "system":
                tables.append("matrix_system")
    tabnum = {k: i + 1 for i, k in enumerate(tables)}
    return fignum, tabnum


def build_post_context(project) -> dict:
    fignum, tabnum = assign_numbers_post(project)
    ctx = build_context(project, numbering=(fignum, tabnum))
    intake = project.intake
    ab = project.artifacts["as_built"]
    abi = intake.as_built
    well = next(w for w in intake.proposed_wells if w.id == ab["well_id"])
    c = abi.construction
    tb = ab["table"]

    def fig(k):
        return f"Figure {fignum[k]}" if k in fignum else "[figure not available]"

    def tab(k):
        return f"Table {tabnum[k]}" if k in tabnum else "[table not available]"

    bore = _join([f"a {frac_in(b.diameter_in)}-inch borehole from {fmt_int(b.top_ft)} to {fmt_int(b.bottom_ft)} ft bgl" for b in c.borehole])
    cas = _join([f"{frac_in(x.diameter_in)}-inch {x.material} casing from {'+' + fmt_int(-x.top_ft) if x.top_ft < 0 else fmt_int(x.top_ft)} to {fmt_int(x.bottom_ft)} ft bgl" for x in c.casing])
    liner = _join([f"{frac_in(x.diameter_in)}-inch {x.material} blank liner from {fmt_int(x.top_ft)} to {fmt_int(x.bottom_ft)} ft bgl" for x in c.blank_liner])
    scr = _join([f"{frac_in(x.diameter_in)}-inch {x.material} screen{' (' + f'{x.slot_in:g}' + '-inch slot)' if x.slot_in else ''} from {fmt_int(x.top_ft)} to {fmt_int(x.bottom_ft)} ft bgl" for x in c.screen])
    cem = _join([f"{x.method} from {fmt_int(x.top_ft)} to {fmt_int(x.bottom_ft)} ft bgl" for x in c.cement])
    fp = _join([f"filter pack from {fmt_int(x.top_ft)} to {fmt_int(x.bottom_ft)} ft bgl" for x in c.filter_pack])
    construction_sentence = (f"{well.label} was drilled to a total depth of {fmt_int(c.total_depth_ft)} ft below ground level (ft bgl) with {bore} and completed with {cas}"
                             + (f", {liner}" if liner else "") + f", {scr}" + (f", {cem}" if cem else "") + (f", and {fp}" if fp else "") + ".")
    if c.packer_depth_ft is not None:
        construction_sentence += f" A packer was set at {fmt_int(c.packer_depth_ft)} ft bgl."
    swl_sentence = f"The static water level measured on {long_date(abi.swl_date) if abi.swl_date else '[DATE]'}, before testing, was {fmt_ft(abi.static_water_level_ft)} ft bgl."
    pump_sentence = (f"The permanent pump is a {frac_in(abi.pump.diameter_in)}-inch{' ' + fmt_int(abi.pump.hp) + '-hp' if abi.pump.hp else ''} {abi.pump.make_model or 'submersible pump'} set at {fmt_int(abi.pump.setting_ft)} ft bgl.")

    asbuilt_rows = [
        ["Static water level (prior to test)", f"{fmt_ft(tb['swl_ft'])} ft bgl"],
        ["Static water level measurement date", long_date(tb["swl_date"]) if tb["swl_date"] else "[DATE]"],
        ["Screen diameter(s)", _join([f"{frac_in(d)} in" for d in tb["screen_diameters_in"]]) or "N/A"],
        ["Blank liner diameter(s)", _join([f"{frac_in(d)} in" for d in tb["liner_diameters_in"]]) or "None"],
        ["Depth to top of screen", f"{fmt_int(tb['screen_top_ft'])} ft bgl" if tb["screen_top_ft"] is not None else "N/A"],
        ["Depth to top of blank liner", f"{fmt_int(tb['liner_top_ft'])} ft bgl" if tb["liner_top_ft"] is not None else "None"],
        ["Depth of top of first well screen", f"{fmt_int(tb['first_screen_top_ft'])} ft bgl" if tb["first_screen_top_ft"] is not None else "N/A"],
        ["Screen intervals", "; ".join(f"{fmt_int(a)}-{fmt_int(b)} ft ({frac_in(d)} in {m}{', ' + f'{sl:g}' + '-in slot' if sl else ''})" for a, b, d, m, sl in tb["screen_intervals"]) or "N/A"],
        ["Total depth of well", f"{fmt_int(tb['total_depth_ft'])} ft bgl"],
        ["Diameter of permanent pump", f"{frac_in(tb['pump_diameter_in'])} in"],
        ["Permanent pump setting", f"{fmt_int(tb['pump_setting_ft'])} ft bgl"],
        ["Pump motor", f"{fmt_int(tb['pump_hp'])} hp" if tb["pump_hp"] else "N/A"],
        ["Completion date", long_date(tb["completion_date"]) if tb["completion_date"] else "N/A"],
        ["TDLR tracking no.", tb["tdlr_tracking_no"] or "N/A"],
    ]

    # logs
    log_rows = []
    for r in ab["logs"]["records"]:
        las = r.get("las")
        curves = ", ".join(r["curves"]) if r["curves"] else (", ".join(cv["mnemonic"] for cv in las["curves"]) if las else "N/A")
        las_txt = ("present" if r["las_present"] else "missing") if r.get("las_file") else "not supplied"
        log_rows.append([LOG_LABELS.get(r["type"], r["type"]), curves, f"{fmt_int(r['top_ft'])} - {fmt_int(r['bottom_ft'])}",
                         r.get("date") or "N/A", "open hole" if r["open_hole"] else f"cased ({r['casing_at_log']})",
                         (r.get("las_file") or "N/A") + f" ({las_txt})"])
    n_logs = ab["logs"]["n_logs"]
    types = sorted({LOG_LABELS.get(r["type"], r["type"]) for r in ab["logs"]["records"]})
    logs_sentence = (f"{_join(types).capitalize()} logs were run in the open borehole" + (f" on {long_date(ab['logs']['records'][0]['date'])}" if ab["logs"]["records"] and ab["logs"]["records"][0].get("date") else "") + f" ({fmt_int(n_logs)} log runs)." if n_logs
                     else "[P.G. TO PROVIDE: geophysical logs were not supplied; Section III.1 requires resistivity or induction plus SP or gamma ray logs of the open borehole.]")
    comp = []
    L = ab["logs"]
    comp.append("The suite includes the resistivity or induction and the SP or gamma ray curves required by Section III.1(a)." if L["has_res_or_induction"] and L["has_sp_or_gamma"] else "[P.G. TO PROVIDE: the suite does not include the minimum resistivity/induction plus SP/gamma curves required by Section III.1(a); explain.]")
    comp.append("The logs were recorded in the initial open borehole." if L["has_open_hole"] else "[P.G. TO PROVIDE: no open-hole log is recorded; Section III.1(b) requires one.]")
    if not L["pvc_ok"]:
        comp.append("[P.G. TO PROVIDE: the well is cased with PVC, which requires induction and gamma ray logs (Section III.1(c)).]")
    comp.append("Digital LAS files accompany this report." if L["all_las_present"] else "[P.G. TO PROVIDE: LAS files for all logs (Section III.1(d)).]")

    # tests
    tests_ctx = []
    test_rows = []
    for t in ab["tests"]:
        parts = []
        if t["kind"] == "constant_rate":
            parts.append(f"Test {t['id']} pumped {well.label} at {fmt_int(t['rate_gpm'])} gpm for {fmt_int(t['duration_min'] / 60)} hours"
                         + (f" beginning {t['start']}" if t["start"] else "") + f"; drawdown at the end of the test was {fmt_ft(t['end_drawdown_ft'])} ft, a specific capacity of {t['specific_capacity']:.2f} gpm/ft.")
            cj = t["cooper_jacob"]
            if cj and cj["t_ft2d"]:
                parts.append(f"The Cooper-Jacob analysis of the {fmt_int(cj['n_used'])} late-time points ({fig('cj_' + t['id'])}) gives a slope of {cj['slope_ft_per_cycle']:.2f} ft per log cycle and a transmissivity of {fmt_int(cj['t_ft2d'])} ft2/day"
                             + (f" (coefficient of determination {cj['r2']:.3f})" if cj["r2"] is not None else "") + ".")
                if not cj["valid"]:
                    parts.append("[REVIEWER TO CONFIRM: the straight-line fit did not meet the validity criteria (" + "; ".join(cj["notes"]) + ").]")
            elif cj:
                parts.append("[REVIEWER TO CONFIRM: Cooper-Jacob analysis was not possible (" + "; ".join(cj["notes"]) + ").]")
            th = t["theis"]
            if th and th["t_ft2d"]:
                parts.append(f"A least-squares Theis match to the full record ({fig('theis_' + t['id'])}) gives {fmt_int(th['t_ft2d'])} ft2/day with storativity {'held at' if th['s_fixed'] else 'fitted as'} {fmt_sci(th['s'])}.")
            rc = t["recovery"]
            if rc and rc["t_ft2d"]:
                parts.append(f"Recovery measurements after shutdown ({fig('recovery_' + t['id'])}) give a transmissivity of {fmt_int(rc['t_ft2d'])} ft2/day by the Theis recovery method.")
            if t["rate_variation"] is not None:
                parts.append(f"The recorded pumping rate varied by up to {t['rate_variation'] * 100:.1f} percent during the test.")
            test_rows.append([t["id"], "Constant rate", fmt_int(t["rate_gpm"]), fmt_int(t["duration_min"]), fmt_ft(t["end_drawdown_ft"]), f"{t['specific_capacity']:.2f}",
                              fmt_int(cj["t_ft2d"]) if cj and cj["t_ft2d"] else "N/A", fmt_int(th["t_ft2d"]) if th and th["t_ft2d"] else "N/A",
                              fmt_int(rc["t_ft2d"]) if rc and rc["t_ft2d"] else "N/A", "N/A"])
        elif t["kind"] == "step":
            sf = t["step"]
            steps_txt = _join([f"{fmt_int(s['q_gpm'])} gpm ({fmt_ft(s['s_ft'])} ft, {s['sc_gpm_ft']:.2f} gpm/ft)" for s in sf["steps"]])
            parts.append(f"Step test {t['id']} pumped the well at {steps_txt}.")
            if sf["b_ft_per_gpm"] is not None:
                eff = sf.get("efficiency_at_design")
                parts.append(f"The Jacob step-drawdown analysis ({fig('step_' + t['id'])}) gives a formation-loss coefficient B of {sf['b_ft_per_gpm']:.4f} ft/gpm and a well-loss coefficient C of {sf['c_ft_per_gpm2']:.2e} ft/gpm2"
                             + (f", corresponding to a well efficiency of {eff * 100:.0f} percent at the design rate of {fmt_int(sf['design_rate_gpm'])} gpm" if eff is not None else "") + ".")
            test_rows.append([t["id"], "Step", "/".join(fmt_int(s["q_gpm"]) for s in sf["steps"]), fmt_int(sum(s.duration_min for s in next(x for x in abi.tests if x.id == t["id"]).steps)),
                              fmt_ft(sf["steps"][-1]["s_ft"]), f"{sf['steps'][-1]['sc_gpm_ft']:.2f}", "N/A", "N/A", "N/A",
                              f"{sf['efficiency_at_design'] * 100:.0f}%" if sf.get("efficiency_at_design") is not None else "N/A"])
        else:
            rc = t["recovery"]
            parts.append(f"Recovery test {t['id']} following pumping at {fmt_int(t['rate_gpm'])} gpm" + (f" gives a transmissivity of {fmt_int(rc['t_ft2d'])} ft2/day ({fig('recovery_' + t['id'])})." if rc and rc["t_ft2d"] else " could not be analyzed."))
            test_rows.append([t["id"], "Recovery", fmt_int(t["rate_gpm"]), "N/A", "N/A", "N/A", "N/A", "N/A", fmt_int(rc["t_ft2d"]) if rc and rc["t_ft2d"] else "N/A", "N/A"])
        tests_ctx.append({"id": t["id"], "sentence": " ".join(parts)})
    n_tests = len(ab["tests"])
    tests_intro = (f"{fmt_int(n_tests)} aquifer test{'s were' if n_tests != 1 else ' was'} performed on {well.label} after development." if n_tests
                   else "[P.G. TO PROVIDE: no aquifer-test data were supplied (Section III.3).]")
    ad = ab["adopted"]
    adopted_sentence = (f"The transmissivity adopted for the well is {fmt_int(ad['t_ft2d'])} ft2/day from the {ad['method']} of test {ad['test_id']}; storativity is taken as {fmt_sci(ad['s'])} ({ad['s_source']})."
                        if ad["t_ft2d"] else "")
    cp = ab["comparison"]
    if cp:
        diff_txt = "less than 1 percent" if abs(cp["percent_difference"]) < 0.5 else f"{cp['percent_difference']:+.0f} percent"
        comparison_sentence = f"This value is {cp['relation']} the {fmt_int(cp['t_pre_ft2d'])} ft2/day adopted in the pre-drilling analysis (a difference of {diff_txt})."
    else:
        comparison_sentence = ""

    # field params
    field_rows = [[f["time"], f"{f['sc_us_cm']:g}" if f.get("sc_us_cm") is not None else "N/A", f"{f['temp_c']:g}" if f.get("temp_c") is not None else "N/A",
                   f"{f['ph']:g}" if f.get("ph") is not None else "N/A", f.get("source") or ""] for f in ab["field_params"]]
    if field_rows:
        scs = [f["sc_us_cm"] for f in ab["field_params"] if f.get("sc_us_cm") is not None]
        phs = [f["ph"] for f in ab["field_params"] if f.get("ph") is not None]
        tcs = [f["temp_c"] for f in ab["field_params"] if f.get("temp_c") is not None]
        field_sentence = (f"Field parameters measured during the test and sampling ranged from {min(scs):g} to {max(scs):g} uS/cm specific conductance" if scs else "Field parameters were recorded")
        if tcs:
            field_sentence += f", {min(tcs):g} to {max(tcs):g} degrees C"
        if phs:
            field_sentence += f", and pH {min(phs):g} to {max(phs):g}"
        field_sentence += "."
    else:
        field_sentence = "[P.G. TO PROVIDE: field parameters (specific conductance, temperature, pH) measured during the test or sampling (Section III.5).]"

    # comparison with pre-drilling scenarios
    comp_rows = []
    pre = ab.get("pre_drilling")
    if ab["rerun_interference"]:
        an = project.artifacts["analysis"]
        for sc in an["scenarios"]:
            now = {q["id"]: q["total_ft"] for aq in sc["results_by_aquifer"].values() for q in aq["pumped_wells"]}
            before = None
            if pre:
                before = next((p["pumped"] for p in pre["scenarios"] if p["key"] == sc["key"]), None)
            for wid, val in now.items():
                nm = next((w.label for w in intake.all_wells if w.id == wid), wid)
                comp_rows.append([sc["title"], nm, fmt_ft(before[wid]) if before and wid in before else "N/A", fmt_ft(val)])
    rerun_summary = ""
    if ab["rerun_interference"] and comp_rows:
        rerun_summary = f"With the measured transmissivity, the re-run interference scenarios give the drawdowns listed in {tab('comparison')}."

    summary_sentence = f"{well.label} was completed on {long_date(abi.completion_date) if abi.completion_date else '[DATE]'} to {fmt_int(c.total_depth_ft)} ft bgl with screen set from {fmt_int(tb['screen_top_ft'])} ft bgl; the static water level was {fmt_ft(abi.static_water_level_ft)} ft bgl." if tb["screen_top_ft"] is not None else ""

    ctx["ab"] = {
        "well_label": well.label, "aquifer": well.aquifer, "completion_date": long_date(abi.completion_date) if abi.completion_date else "[DATE]",
        "driller": abi.driller, "tdlr_tracking_no": abi.tdlr_tracking_no,
        "pre_title": abi.pre_drilling_report.title if abi.pre_drilling_report else None,
        "pre_date": long_date(abi.pre_drilling_report.date) if abi.pre_drilling_report and abi.pre_drilling_report.date else None,
        "rerun": ab["rerun_interference"], "construction_sentence": construction_sentence, "swl_sentence": swl_sentence,
        "pump_sentence": pump_sentence, "has_lithology": bool(c.lithology), "asbuilt_rows": asbuilt_rows,
        "log_rows": log_rows, "logs_sentence": logs_sentence, "logs_compliance_sentence": " ".join(comp),
        "tests": tests_ctx, "tests_intro_sentence": tests_intro, "test_rows": test_rows,
        "test_header": ["Test", "Type", "Rate (gpm)", "Duration (min)", "End drawdown (ft)", "Specific capacity (gpm/ft)", "T, Cooper-Jacob (ft2/day)", "T, Theis match (ft2/day)", "T, recovery (ft2/day)", "Well efficiency at design rate"],
        "adopted_sentence": adopted_sentence, "comparison_sentence": comparison_sentence,
        "adopted_t": fmt_int(ad["t_ft2d"]) if ad["t_ft2d"] else "N/A", "pre_t": fmt_int(cp["t_pre_ft2d"]) if cp else "N/A",
        # The re-run narrative may only claim storativity is unchanged when it actually is: a test-derived value is
        # substituted into the scenarios alongside the measured transmissivity.
        "s_substituted": ad["s_source"] != "GAM (pre-drilling value)",
        "unchanged_inputs": ("rates, annual volume and well locations" if ad["s_source"] != "GAM (pre-drilling value)"
                             else "storativity, rates, annual volume and well locations"),
        "adopted_s": fmt_sci(ad["s"]) if ad["s"] is not None else "N/A",
        "field_rows": field_rows, "field_sentence": field_sentence, "field_header": ["Time", "Specific conductance (uS/cm)", "Temperature (C)", "pH", "Source"],
        "comparison_rows": comp_rows, "comparison_header": ["Scenario", "Well", "Pre-drilling drawdown (ft)", "As-built drawdown (ft)"],
        "rerun_summary_sentence": rerun_summary, "summary_sentence": summary_sentence,
        "data_tables": [{"id": t["id"], "rows": [[fmt_int(a), fmt_ft(b, 2), (fmt_int(r) if r is not None else ""), (ph or "")] for a, b, r, ph in
                                                 zip(t["series"]["elapsed_min"], t["series"]["drawdown_ft"],
                                                     t["series"]["rate_gpm"] or [None] * len(t["series"]["elapsed_min"]),
                                                     t["series"]["phase"] or [""] * len(t["series"]["elapsed_min"]), strict=True)]} for t in ab["tests"]],
    }
    ctx["tab"].update({"asbuilt": tab("asbuilt"), "logs": tab("logs"), "tests": tab("tests"), "field": tab("field"), "comparison": tab("comparison")})
    ctx["fig"]["schematic_asbuilt"] = fig("schematic_asbuilt")
    return ctx
