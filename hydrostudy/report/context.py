"""Build the report context: every number the narrative may cite, pre-formatted, plus table rows and numbering."""

from __future__ import annotations

from datetime import date

from hydrostudy import __version__
from hydrostudy.units import GPM_TO_CFD, fmt_ft, fmt_gal, fmt_int, fmt_miles, fmt_sci

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

#: Which numbered section carries the interference analysis, per report format. The uncertainty appendix
#: qualifies that section by name, and the two formats do not number it the same.
INTERFERENCE_SECTION = {"lsgcd_pre_drilling": "Section 6", "feasibility": "Section 6",
                        "lsgcd_post_drilling": "Section 5"}


def long_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
        return f"{MONTHS[d.month-1]} {d.day}, {d.year}"
    except Exception:
        return iso


def frac_in(d: float) -> str:
    whole = int(d)
    frac = d - whole
    table = {0.125: "1/8", 0.25: "1/4", 0.375: "3/8", 0.5: "1/2", 0.625: "5/8", 0.75: "3/4", 0.875: "7/8"}
    for k, v in table.items():
        if abs(frac - k) < 0.02:
            return f"{whole}-{v}"
    return f"{d:g}"


def _join(items):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def assign_numbers(project) -> tuple[dict, dict]:
    """Figure/table numbers in document order (the assembler inserts them in this same order)."""
    figs = project.artifacts["figures"]
    a = project.artifacts["analysis"]
    order = ["location", "wells", "property"] + [f"schematic_{w.id}" for w in project.intake.proposed_wells] + ["strat"]
    for aq in sorted({w.aquifer for w in project.intake.proposed_wells}):
        order += [f"gam_{prm}_{aq}" for prm in ("t", "k", "s") if f"gam_{prm}_{aq}" in figs]
    order += [k for k in ("wq_tds", "wq_fe", "wq_as", "wq_ra_combined") if k in figs]
    for sc in a["scenarios"]:
        for aq in sc["results_by_aquifer"]:
            order.append(f"dd_{sc['key']}_{aq}")
    order.append("distance_drawdown")
    fignum = {k: i + 1 for i, k in enumerate([k for k in order if k in figs])}
    tables = ["nearby", "construction", "parameters"]
    wq = project.artifacts["water_quality"]
    if wq["n_records"]:
        tables += ["wq_radionuclides", "wq_panel"]
    for g in scenario_groups(project):
        tables += [f"summary_{g['key']}", f"edges_{g['key']}", f"impacts_{g['key']}"]
        if g["key"] == "system":
            tables.append("matrix_system")
    tabnum = {k: i + 1 for i, k in enumerate(tables)}
    return fignum, tabnum


def scenario_groups(project) -> list[dict]:
    a = project.artifacts["analysis"]
    groups = []
    for w in project.intake.proposed_wells:
        scs = [s for s in a["scenarios"] if s["group"] == "proposed_only" and s["focus_well"] == w.id]
        if scs:
            groups.append({"key": f"proposed_{w.id}", "kind": "proposed_only", "well_id": w.id, "scenarios": scs})
    scs = [s for s in a["scenarios"] if s["group"] == "system"]
    if scs:
        groups.append({"key": "system", "kind": "system", "well_id": None, "scenarios": scs})
    subs = [s for s in a["scenarios"] if s["group"] == "single_well_subcase"]
    if subs:
        groups.append({"key": "single_subcases", "kind": "single_well_subcase", "well_id": None, "scenarios": subs})
    return groups


def _solution_context(an: dict, geo: dict, join) -> dict:
    """Which analytical solution the numbers came from, and what the narrative must say about it.

    Every figure here is formatted into a string so the anti-fabrication lint sees it: the methodology
    paragraph may state a leakance only because the leakance is in this block.
    """
    specs = an.get("solutions") or {}
    leaky = {aq: s for aq, s in specs.items() if s.get("kind") == "hantush"}
    per = []
    for aq, s in sorted(specs.items()):
        per.append({
            "aquifer": aq, "citation": s.get("citation", ""), "kind": s.get("kind", "theis"),
            # Plain-text scientific notation: a leakance is 1e-05 in code and "1.00 x 10^-5" in a
            # document a person reads and a District files.
            "leakance_text": (fmt_sci(s["leakance_per_day"]) if s.get("leakance_per_day") else None),
            "b_text": (fmt_int(s["leakage_factor_ft"]) if s.get("leakage_factor_ft") else None),
            "basis": s.get("basis"),
            "fell_back": bool(s.get("fell_back")),
        })
    leaky_sentence = ""
    if leaky:
        parts = []
        for p in per:
            if p["kind"] != "hantush":
                continue
            parts.append(f"for the {p['aquifer']} a leakance of {p['leakance_text']} per day "
                         f"({p['basis']}), giving a leakage factor B of {p['b_text']} ft")
        leaky_sentence = ("The leakage properties applied were " + join(parts) + ". "
                          "Because part of the withdrawal is supplied across the confining unit rather "
                          "than from storage, drawdown approaches a steady cone instead of continuing to "
                          "deepen with the logarithm of time.")
    bounds = geo.get("hydraulic_boundaries") or []
    bound_sentence = ""
    if bounds:
        described = join([f"a {b['kind']} boundary at {b['name']}"
                          + (f" ({b['source']})" if b.get("source") else "") for b in bounds])
        effect = ("A barrier boundary passes no water, so the cone deepens against it; a recharge "
                  "boundary holds the head fixed, so drawdown there is zero.")
        exact = ("This is the exact analytical solution for a single straight boundary."
                 if len(bounds) == 1 else
                 "With more than one boundary the image series is truncated, and the reviewer should "
                 "confirm that the truncation is acceptable for this geometry.")
        bound_sentence = (f"The analysis represents {described} by the method of images, in which an "
                          f"image well reflected across the boundary reproduces its effect exactly. "
                          f"{effect} {exact}")
    return {
        "is_leaky": bool(leaky), "per_aquifer": per,
        "citations": join(sorted({p["citation"] for p in per if p["citation"]})),
        "leaky_sentence": leaky_sentence,
        "has_boundaries": bool(bounds), "boundary_sentence": bound_sentence,
        "boundary_count_text": fmt_int(len(bounds)) if bounds else "0",
    }


def _uncertainty_context(unc: dict, join, section_ref: str = "Section 6") -> dict:
    """Appendix D: the declared spreads, and what they do to every drawdown the report states.

    Every figure here is formatted from the propagated result, never recomputed, so the appendix cannot
    disagree with `build/uncertainty.json`. The appendix carries its own D-n labels because it sits
    outside the body's figure and table sequence.

    `section_ref` is the interference section the appendix qualifies, and it is a parameter because the
    two report formats number it differently: 6 in the pre-drilling report, 5 in the post-drilling one.
    An appendix pointing at the wrong section is the kind of error that costs a reviewer's confidence in
    everything around it.
    """
    from hydrostudy.analysis.uncertainty import quantile_keys
    lo_k, mid_k, hi_k = quantile_keys(unc["quantiles"])

    def pct(k):
        return f"p{float(k) * 100:g}"

    def probability(f: float) -> str:
        """A probability as a reader should see it, never rounded to certainty.

        `f"{0.9997:.0%}"` is "100%", and a 100% probability is something no finite simulation can
        establish. In a document a District files that is not a rounding convention, it is a claim the
        method cannot support, so the extremes are reported as bounds instead.
        """
        if f >= 0.995:
            return ">99%"
        if 0 < f < 0.005:
            return "<1%"
        return f"{f:.0%}"

    par = unc["parameters"]
    param_rows, declared = [], []
    for key, label, fmt in (("t_ft2d", "Transmissivity (ft2/day)", fmt_int),
                            ("s", "Storativity", fmt_sci)):
        d = par[key]
        if d["declared"]:
            param_rows.append([label, d["kind"], fmt(d["declared_p10"]), fmt(d["declared_median"]),
                               fmt(d["declared_p90"]), fmt(d["intake_value"]), d["source"]])
            # p10 and p90 of the declaration itself, which is what `_param_summary` reports whatever
            # quantiles were asked of the drawdown - the two are separate and must not be conflated.
            declared.append(f"{label.split(' (')[0].lower()} as a {d['kind']} distribution with a p10 of "
                            f"{fmt(d['declared_p10'])} and a p90 of {fmt(d['declared_p90'])}, from "
                            f"{d['source']}")
        else:
            param_rows.append([label, "held at the intake value", "", fmt(d["intake_value"]), "",
                               fmt(d["intake_value"]), "no spread declared"])

    rec_header = (["Receptor", "Reported in this report (ft)", "Percentile of the reported value"]
                  + [f"{pct(k)} drawdown (ft)" for k in (lo_k, mid_k, hi_k)]
                  + ["Standard error of the " + pct(hi_k) + " (ft)"]
                  + [f"P(drawdown > {fmt_ft(t, 0)} ft)" for t in unc["thresholds_ft"]])
    rec_rows = []
    for r in unc["receptors"]:
        q = r["quantiles"]
        row = [r["label"],
               fmt_ft(r["deterministic_ft"]) if r["deterministic_ft"] is not None else "N/A",
               probability(r["deterministic_percentile"]) if r["deterministic_percentile"] is not None else "N/A",
               fmt_ft(q[lo_k]["ft"]), fmt_ft(q[mid_k]["ft"]), fmt_ft(q[hi_k]["ft"]),
               fmt_ft(q[hi_k]["standard_error_ft"], 2)]
        row += [probability(r["exceedance"][f"{t:g}"]) for t in unc["thresholds_ft"]]
        rec_rows.append(row)

    # The most exposed registered well is named in the propagated notes already, and those notes are
    # rendered in full below, so a sentence about it here would repeat one of them word for word.
    worst = max((r for r in unc["receptors"] if r["kind"] == "registered"),
                key=lambda r: r["quantiles"][hi_k]["ft"], default=None)
    exceed_sentence = ""
    if worst and unc["thresholds_ft"]:
        parts = [f"{probability(worst['exceedance'][f'{t:g}'])} of exceeding {fmt_ft(t, 0)} ft"
                 for t in unc["thresholds_ft"]]
        exceed_sentence = (f"Against the drawdown figures the District asked about, the simulation puts "
                           f"the probability at {worst['label']} at " + join(parts) + ".")
    return {
        "aquifer": unc["aquifer"], "scenario_title": unc["scenario_title"],
        "duration_label": unc["duration_label"], "rate": fmt_int(unc["total_rate_gpm"]),
        # The scenario title already names the duration, so the sentence states the rate and the
        # duration once between them rather than repeating the figure.
        "case_sentence": (f"{unc['scenario_title'][0].lower() + unc['scenario_title'][1:]} case, "
                          f"a total of {fmt_int(unc['total_rate_gpm'])} gpm"),
        "draws": fmt_int(unc["draws"]), "seed": f"{unc['seed']:d}",
        "citation": unc["solution"]["citation"],
        "declared_sentence": ("The spreads carried through this appendix are " + join(declared) + ".")
                             if declared else "",
        "low_pct": pct(lo_k), "mid_pct": pct(mid_k), "high_pct": pct(hi_k),
        "exceed_sentence": exceed_sentence, "section_ref": section_ref,
        "notes": unc["notes"],
        "param_header": ["Parameter", "Distribution", "p10 as declared", "Median as declared",
                         "p90 as declared", "Value used in the report", "Source"],
        "param_rows": param_rows,
        "receptor_header": rec_header, "receptor_rows": rec_rows,
        "figure_label": "Figure D-1", "param_table_label": "Table D-1", "receptor_table_label": "Table D-2",
    }


def build_context(project, numbering=None) -> dict:
    intake, review, district = project.intake, project.review, project.district
    A = project.artifacts
    an, geo, nearby, wq, hydro = A["analysis"], A["geo"], A["nearby_wells"], A["water_quality"], A["hydrography"]
    fignum, tabnum = numbering if numbering else assign_numbers(project)
    figs = A["figures"]
    names = {w.id: w.label for w in intake.all_wells}

    def wn(i):
        return names.get(str(i), "Well " + str(i))

    def fig(k):
        return f"Figure {fignum[k]}" if k in fignum else "[figure not available]"

    def tab(k):
        return f"Table {tabnum[k]}" if k in tabnum else "[table not available]"

    target_aqs = sorted({w.aquifer for w in intake.proposed_wells})
    target_text = _join([f"{a} Aquifer" for a in target_aqs])
    n_prop = len(intake.proposed_wells)
    count_text = "one new well" if n_prop == 1 else f"{fmt_int(n_prop)} new wells"
    prop_names = _join([f"{wn(w.id)}" for w in intake.proposed_wells])

    # ---- proposed wells
    pw_ctx = []
    for w in intake.proposed_wells:
        parts = []
        for b in w.borehole:
            parts.append(f"a {frac_in(b.diameter_in)}-inch diameter borehole from {fmt_int(b.top_ft)} to {fmt_int(b.bottom_ft)} ft bgl")
        bore = _join(parts)
        cas = _join([f"{frac_in(c.diameter_in)}-inch {c.material} casing set from {fmt_int(c.top_ft) if c.top_ft >= 0 else '+' + fmt_int(-c.top_ft)} to {fmt_int(c.bottom_ft)} ft bgl" for c in w.casing])
        cem = _join([f"{c.method} from {fmt_int(c.top_ft)} to {fmt_int(c.bottom_ft)} ft bgl" for c in w.cement])
        scr = _join([f"{frac_in(s.diameter_in)}-inch {s.material} screen from {fmt_int(s.top_ft)} to {fmt_int(s.bottom_ft)} ft bgl" for s in w.screen])
        fp = _join([f"filter pack from {fmt_int(f.top_ft)} to {fmt_int(f.bottom_ft)} ft bgl" for f in w.filter_pack])
        sent = (f"Proposed {wn(w.id)} will be drilled to an anticipated total depth of {fmt_int(w.total_depth_ft)} ft below ground level (ft bgl) with {bore}, "
                f"completed with {cas}{', ' + cem if cem else ''}, and {scr}{', with ' + fp if fp else ''}.")
        if w.packer_depth_ft is not None:
            sent += f" A packer will be set at approximately {fmt_int(w.packer_depth_ft)} ft bgl."
        swl = f"{fmt_int(w.static_water_level_ft)} ft bgl" if w.static_water_level_ft is not None else "N/A"
        target = f"The target production zone is the {w.aquifer} Aquifer, with a maximum allowable pumping rate of {fmt_int(w.max_rate_gpm)} gpm and an estimated static water level of about {swl}."
        pw_ctx.append({
            "id": w.id, "label": w.label, "aquifer": w.aquifer, "rate": fmt_int(w.max_rate_gpm), "depth": fmt_int(w.total_depth_ft),
            "construction_sentence": sent, "target_sentence": target,
            "coords": f"{_dms(w.lat, 'lat')}, {_dms(w.lon, 'lon')}",
            "elev": fmt_int(w.elevation_ft_msl) if w.elevation_ft_msl is not None else "N/A",
            "swl": fmt_int(w.static_water_level_ft) if w.static_water_level_ft is not None else "N/A",
            "borehole": "; ".join(f"{frac_in(b.diameter_in)}\" ({fmt_int(b.top_ft)}'-{fmt_int(b.bottom_ft)}')" for b in w.borehole) or "N/A",
            "casing": "; ".join(f"{frac_in(c.diameter_in)}\" {c.material} ({'+' + fmt_int(-c.top_ft) if c.top_ft < 0 else fmt_int(c.top_ft)}'-{fmt_int(c.bottom_ft)}')" for c in w.casing) or "N/A",
            "screen": "; ".join(f"{frac_in(s.diameter_in)}\" {s.material} ({fmt_int(s.top_ft)}'-{fmt_int(s.bottom_ft)}')" for s in w.screen) or "N/A",
            "cement": "; ".join(f"{fmt_int(c.top_ft)}'-{fmt_int(c.bottom_ft)}'" for c in w.cement) or "N/A",
            "filter_pack": "; ".join(f"{fmt_int(f.top_ft)}'-{fmt_int(f.bottom_ft)}'" for f in w.filter_pack) or "NA",
            "lithology_rows": [[f"{fmt_int(li.top_ft)} - {fmt_int(li.bottom_ft)}", li.description] for li in w.anticipated_lithology],
            "screen_top": fmt_int(min(s.top_ft for s in w.screen)) if w.screen else "N/A",
            "screen_length": fmt_int(sum(s.thickness_ft for s in w.screen)) if w.screen else "N/A",
        })
    prop_summary = _join([f"proposed {wn(w.id)} will be completed in the {w.aquifer} Aquifer and pumped at a maximum allowable rate of {fmt_int(w.max_rate_gpm)} gpm" for w in intake.proposed_wells])
    prop_summary = prop_summary[0].upper() + prop_summary[1:] + "."
    ex = [w for w in intake.existing_wells]
    if ex:
        ex_sentence = ("The system currently includes " + ("one existing well" if len(ex) == 1 else f"{fmt_int(len(ex))} existing wells") + ": " +
                       _join([f"{wn(w.id)}{' (LSGCD Well Registration No. ' + w.registration_no + ')' if w.registration_no else ''}, completed in the {w.aquifer} Aquifer with a maximum allowable pumping rate of {fmt_int(w.max_rate_gpm)} gpm" for w in ex]) + ".")
    else:
        ex_sentence = "The system has no existing wells."

    # ---- district / permit
    thr = district.get("report_threshold_gpm")
    if thr is not None:
        if intake.system_rate_gpm >= thr:
            thr_sentence = f"meets or exceeds the {fmt_int(thr)}-gpm threshold at which the District requires a hydrogeological report."
        else:
            thr_sentence = f"is below the {fmt_int(thr)}-gpm threshold at which the District requires a hydrogeological report; this report is provided in support of the application."
    else:
        thr_sentence = "is stated for the District's reference."

    # ---- spacing
    sp_ctx = []
    for w in an["spacing"]["wells"]:
        if w["rule_available"] and not w["provisional"]:
            rule = (f"District spacing rules for wells completed in the {w['aquifer']} Aquifer require a minimum distance to other non-exempt wells of "
                    f"{w['ft_per_gpm']:g} ft multiplied by the maximum allowable pumping rate; for the {fmt_int(w['max_rate_gpm'])}-gpm rate of proposed {wn(w['well_id'])} "
                    f"this is {fmt_int(w['required_spacing_ft'])} ft.")
        elif w["rule_available"]:
            # The multiplier was not read from the District's own rules document, so it is described as the distance
            # this analysis applied rather than as the District's requirement, and the reviewer is asked to confirm it.
            rule = (f"The spacing distance applied to proposed {wn(w['well_id'])}, completed in the {w['aquifer']} Aquifer, is "
                    f"{w['ft_per_gpm']:g} ft multiplied by the maximum allowable pumping rate, which for its "
                    f"{fmt_int(w['max_rate_gpm'])}-gpm rate gives {fmt_int(w['required_spacing_ft'])} ft. "
                    "[REVIEWER TO CONFIRM: the current District spacing multiplier for this aquifer; the value used here was "
                    "taken from previously accepted submittals rather than from the District Rules.]")
        elif district["id"] == "generic":
            rule = f"No groundwater-district spacing rule is configured for this site; the distances from proposed {wn(w['well_id'])} to the nearest known wells are listed in {tab('nearby')} for reference."
        else:
            rule = f"[REVIEWER TO PROVIDE: no spacing multiplier is configured for the {w['aquifer']} Aquifer; state the District rule and the required distance for {wn(w['well_id'])}.]"
        if w["rule_available"] and w["complies"] and not w["provisional"]:
            result = f"According to the District well database, no other registered or permitted wells are located within {fmt_int(w['required_spacing_ft'])} ft of proposed {wn(w['well_id'])}; the proposed location complies with the spacing rule."
        elif w["rule_available"] and w["complies"]:
            result = (f"According to the District well database, no other registered or permitted wells are located within "
                      f"{fmt_int(w['required_spacing_ft'])} ft of proposed {wn(w['well_id'])}. Subject to confirmation of the "
                      "multiplier above, the proposed location meets this spacing distance.")
        elif w["rule_available"]:
            conflict_names = _join([f"Map ID {c['map_id']} ({c['owner']}, {fmt_int(c['distance_ft'])} ft)" for c in w["conflicts"]])
            result = f"The following registered or permitted wells are located within {fmt_int(w['required_spacing_ft'])} ft of proposed {wn(w['well_id'])}: {conflict_names}. [REVIEWER TO PROVIDE: spacing exception request and supporting impact documentation.]"
        else:
            result = ""
        same = ""
        if w["same_system_inside"]:
            same = ("The Applicant's own " + _join([f"{wn(_reg_to_id(intake, c['registration_no']))} (Map ID {c['map_id']}, {fmt_int(c['distance_ft'])} ft)" for c in w["same_system_inside"]]) +
                    " lies inside this radius; wells of the same water system are not treated as conflicting wells for spacing purposes.")
        sp_ctx.append({"well_id": w["well_id"], "rule_sentence": rule, "result_sentence": result, "same_system_sentence": same,
                       "required": fmt_int(w["required_spacing_ft"]) if w["required_spacing_ft"] else "N/A"})

    # ---- radii and nearby wells
    n_in = sum(1 for n in nearby if n["in_search_radius"])
    nearby_rows = []
    for n in nearby:
        if not n["in_search_radius"]:
            continue
        nearby_rows.append([n["map_id"], n["registration_no"] or "N/A", n["permit_no"], n["owner"], f"{n['address']}, {n['city']}".strip(", "),
                            fmt_int(n["total_depth_ft"]) if n["total_depth_ft"] is not None else "N/A",
                            n["screen_intervals"] or "N/A", (n["aquifer"] or "N/A") + ("*" if n["aquifer_inferred"] else ""), n["status"],
                            f"{n['lat']:.6f}", f"{n['lon']:.6f}", fmt_int(n["distance_ft"])])
    aq_counts = {}
    for n in nearby:
        if n["in_search_radius"]:
            aq_counts[n["aquifer"] or "unknown"] = aq_counts.get(n["aquifer"] or "unknown", 0) + 1
    usage = (f"Of the {fmt_int(n_in)} District wells within the search radius, " +
             _join([f"{fmt_int(c)} are completed in the {a} Aquifer" if a != "unknown" else f"{fmt_int(c)} have no completion record" for a, c in sorted(aq_counts.items(), key=lambda kv: -kv[1])]) +
             "; most of the domestic wells in the area are completed at depths of " +
             (f"{fmt_int(min(n['total_depth_ft'] for n in nearby if n['total_depth_ft'] and not n['is_system_well']))} to {fmt_int(max(n['total_depth_ft'] for n in nearby if n['total_depth_ft'] and not n['is_system_well'] and n['total_depth_ft'] < 1000))} ft bgl" if any(n['total_depth_ft'] for n in nearby if not n['is_system_well']) else "unknown depth") + ".")

    # ---- hydrography
    feats = [f"{f['name']} ({f['type']})" for f in hydro["features"]] + [f"{n['name']} ({n.get('type','feature')})" for n in hydro["notes"]]
    if feats:
        streams_sentence = f"Surface-water features mapped within {fmt_int(hydro['radius_mi'])} mile of the proposed well include {_join(feats)} ({fig('wells')})."
    else:
        streams_sentence = f"[REVIEWER TO PROVIDE: streams or ponds within {fmt_int(hydro['radius_mi'])} mile of the proposed well (Guidelines II.B.3(i)); no hydrography data were supplied.]"
    if hydro["springs_searched"]:
        springs_sentence = ("No springs are recorded within the study area" + (f" ({hydro['springs_source']})" if hydro["springs_source"] else "") + "." if not hydro["springs_found"]
                            else "Springs recorded within the study area: " + _join([str(s) for s in hydro["springs_found"]]) + ".")
    else:
        springs_sentence = "[REVIEWER TO PROVIDE: result of the springs search within 1 mile of the proposed well.]"

    # ---- aquifers / parameters
    aq_ctx = []
    param_rows = []
    for name, p in an["aquifer_params"].items():
        if p["top_ft_bgl"] is not None and p["bottom_ft_bgl"] is not None:
            depth_sentence = (f"At the site, the top of the {name} Aquifer is estimated at approximately {fmt_int(p['top_ft_bgl'])} ft bgl and its base at approximately "
                              f"{fmt_int(p['bottom_ft_bgl'])} ft bgl{' (' + p['depth_source'] + ')' if p['depth_source'] else ''}.")
            thick_sentence = f"The aquifer is therefore about {fmt_int(p['thickness_ft'])} ft thick at the site; " + _join([f"proposed {wn(c['id'])} will screen {c['screen_length']} ft of it beginning at {c['screen_top']} ft bgl" for c in pw_ctx if c['aquifer'] == name]) + "."
        else:
            depth_sentence = f"[P.G. TO PROVIDE: top and base of the {name} Aquifer at the site from the GAM layer surfaces or nearby logs (Guidelines II.B.3(c) and (d)).]"
            thick_sentence = ""
        conf = p["confinement"]
        if conf["status"] != "unknown":
            conf_sentence = f"The target production zone is expected to be {conf['status']}" + (f", beneath the {conf['confining_unit']}" if conf.get("confining_unit") else "") + (f", which is estimated to be about {fmt_int(conf['thickness_ft'])} ft thick at the site" if conf.get("thickness_ft") else "") + "."
        else:
            conf_sentence = "[P.G. TO PROVIDE: whether the target zone is confined or unconfined and the estimated thickness of the confining layer (Guidelines II.B.3(e) and (f)).]"
        src = p["citation"] or ("the TWDB groundwater availability model" + (f" ({p['model_version']})" if p["model_version"] else ""))
        params_sentence = (f"The hydraulic parameters adopted for the {name} Aquifer are a transmissivity of {fmt_int(p['t_ft2d'])} ft2/day, "
                           f"a hydraulic conductivity of {p['k_ftd']:.1f} ft/day{' (derived as transmissivity divided by aquifer thickness)' if p['k_derived'] else ''} and a storativity of {fmt_sci(p['s'])}; source: {src}.")
        deriv = ""
        for d in p["derivations"]:
            deriv += (f" {wn(d['well_ref'])} was pumped at {fmt_int(d['q_gpm'])} gpm for {fmt_int(d['duration_hr'])} hours" + (f" (TDLR tracking no. {d['tracking_no']})" if d.get("tracking_no") else "") +
                      f"; the water level declined from {fmt_ft(d['swl_ft'])} to {fmt_ft(d['pwl_ft'])} ft bgl, a drawdown of {fmt_ft(d['drawdown_ft'])} ft and a specific capacity of {d['specific_capacity_gpm_ft']:.2f} gpm/ft. "
                      f"Solving the specific-capacity relation of Theis (1963) as applied by Mace (2001) with the model storativity and an effective well radius of {d['r_w_ft']:g} ft gives a transmissivity of {fmt_int(d['t_ft2d'])} ft2/day.")
            if d.get("mismatch_note"):
                deriv += f" [REVIEWER TO CONFIRM: {d['mismatch_note']}]"
        gam_note = ""
        gam_figs = [fig(k) for k in fignum if k.startswith("gam_") and k.endswith("_" + name)]
        if gam_figs:
            gam_note = f"{_join(gam_figs)} show the model's transmissivity, hydraulic conductivity and storativity in the cells surrounding the site. "
        if p.get("gam_note"):
            gam_note += p["gam_note"][0].upper() + p["gam_note"][1:] + ". "
        if district.get("gam", {}).get("current_adopted"):
            gam_note += (f"The District's guidelines reference the {district['gam']['cited_in_guidelines']}; the currently adopted regional model is the {district['gam']['current_adopted']}. "
                        "The model version used for the parameters is stated in the table, and the selection should be confirmed with District staff.")
        aq_ctx.append({"name": name, "depth_sentence": depth_sentence, "thickness_sentence": thick_sentence, "confinement_sentence": conf_sentence,
                       "params_sentence": params_sentence, "derivation_sentence": deriv.strip(), "gam_note": gam_note})
        for w in intake.all_wells:
            if w.aquifer == name:
                param_rows.append([w.label, name, fmt_int(p["t_ft2d"]), f"{p['k_ftd']:.1f}" + ("**" if p["k_derived"] else ""), fmt_sci(p["s"]),
                                   fmt_int(p["thickness_ft"]) if p["thickness_ft"] else "N/A",
                                   ("Site test / GAM" if p["source_kind"] == "site_test" else p["source_kind"].upper()) + (f" ({p['model_version']})" if p["model_version"] else "")])

    # ---- water quality
    wq_ctx = {"available": wq["n_records"] > 0, "limits_version_text": wq["limits_version"]}
    if wq["n_records"]:
        n_wells = len(wq["wells"])
        wq_ctx["records_sentence"] = f"Water-quality records were compiled for {fmt_int(n_wells)} sampled well{'s' if n_wells != 1 else ''} in the study area ({_join(sorted({w['source'] for w in wq['wells'] if w['source']}))})."
        wq_figs = [fig(k) for k in ("wq_tds", "wq_fe", "wq_as", "wq_ra_combined") if k in fignum]
        wq_ctx["figures_sentence"] = (f"{_join(wq_figs)} show the reported concentrations of TDS, iron, arsenic and combined radium at the sampled wells, labeled with well depth." if wq_figs else "")
        wq_ctx["tds_sentence"] = _wq_sentence(wq, "tds", "TDS")
        wq_ctx["fe_sentence"] = _wq_sentence(wq, "fe", "iron")
        wq_ctx["as_sentence"] = _wq_sentence(wq, "as", "arsenic")
        rad = [k for k in ("gross_alpha", "gross_beta", "ra_combined", "uranium") if k in wq["summaries"]]
        if rad:
            exc = [wq["summaries"][k]["label"] for k in rad if wq["summaries"][k]["n_exceed_mcl"]]
            wq_ctx["radionuclide_sentence"] = ("Radionuclide results are summarized in " + tab("wq_radionuclides") + "; " +
                                               ("no reported value exceeds its MCL." if not exc else f"reported {_join(exc)} values exceed the MCL."))
        else:
            wq_ctx["radionuclide_sentence"] = "[P.G. TO PROVIDE: radionuclide data (gross alpha, gross beta, combined radium, uranium) for nearby wells completed at similar depths.]"
        # representative well = deepest sampled well with the most constituents nearest the proposed well
        rep = _representative_well(project, wq)
        if rep:
            vals = rep["values"]
            exc_scl = [_lc(vals[k]["label"]) + f" ({vals[k]['value']:g} {vals[k]['units']})" for k in vals if vals[k]["exceeds_scl"]]
            exc_mcl = [_lc(vals[k]["label"]) + f" ({vals[k]['value']:g} {vals[k]['units']})" for k in vals if vals[k]["exceeds_mcl"]]
            wq_ctx["representative_sentence"] = (f"{tab('wq_panel')} summarizes the most recent sample from {rep['well_name'] or rep['well_id']}"
                                                 + (f" (completed to {fmt_int(rep['depth_ft'])} ft bgl in the {rep['aquifer']} Aquifer)" if rep.get("depth_ft") else "")
                                                 + f", sampled {rep['sample_date']}, which is the sampled well most representative of the proposed completion.")
            wq_ctx["exceedance_sentence"] = ("That sample met all TCEQ MCLs and SCLs." if not exc_scl and not exc_mcl else
                                             ("It exceeded the MCL for " + _join(exc_mcl) + ". " if exc_mcl else "") +
                                             ("It met all MCLs but exceeded the SCL for " + _join(exc_scl) + "." if exc_scl else ""))
            wq_ctx["representative"] = rep
        else:
            wq_ctx["representative_sentence"] = ""
            wq_ctx["exceedance_sentence"] = ""
        wq_ctx["radionuclide_rows"], wq_ctx["radionuclide_header"], wq_ctx["radionuclide_red"] = _rad_table(wq)
        wq_ctx["panel_rows"], wq_ctx["panel_header"], wq_ctx["panel_red"] = _panel_table(wq)

    # ---- scenarios
    groups_ctx = []
    all_r_w = sorted({f"{w['r_w_ft']:g} ft" for w in an["wells"]})
    thresholds = [f"{t:g} ft" for t in (review.decisions.cone_edge_thresholds_ft or intake.analysis.cone_edge_thresholds_ft)]
    dur_sentences = []
    for g in scenario_groups(project):
        gc = {"key": g["key"], "kind": g["kind"]}
        scs = g["scenarios"]
        aq = list(scs[0]["results_by_aquifer"].keys())[0]
        wells_in = _join([f"{wn(i)}" for i in scs[0]["well_ids"]])
        if g["kind"] == "proposed_only":
            gc["heading"] = f"Proposed {wn(g['well_id'])} pumping alone"
            gc["intro_sentence"] = f"The first case simulates proposed {wn(g['well_id'])} pumping alone at its maximum allowable rate."
        elif g["kind"] == "system":
            gc["heading"] = "All system wells pumping concurrently"
            gc["intro_sentence"] = f"The second case simulates {wells_in} pumping concurrently at their maximum allowable rates."
        else:
            gc["heading"] = "Single-well sub-cases"
            gc["intro_sentence"] = "Additional cases simulate each system well pumping alone for the fixed durations."
        bullets = []
        for s in scs[0]["results_by_aquifer"][aq]["wells_xy"]:
            bullets.append(f"{wn(s['id'])} production rate: {fmt_int(s['q_gpm'])} gpm (effective radius {s['r_w_ft']:g} ft)")
        p = an["aquifer_params"][aq]
        bullets.append(f"Transmissivity: {fmt_int(p['t_ft2d'])} ft2/day ({aq} Aquifer)")
        bullets.append(f"Storativity: {fmt_sci(p['s'])}")
        bullets.append(_join([f"{s['duration_label']} ({fmt_gal(s['volume_gal'])} gallons at {fmt_int(s['total_rate_gpm'])} gpm)" for s in scs]) + " simulated")
        gc["param_bullets"] = bullets
        # results sentences per scenario
        sents = []
        for s in scs:
            res = s["results_by_aquifer"][aq]
            pw = res["pumped_wells"]
            at_wells = _join([f"{fmt_ft(x['total_ft'])} ft at {wn(x['id'])}" for x in pw])
            bnd = _join([f"{fmt_ft(x['boundary_drawdown_ft'])} ft at the nearest property boundary {fmt_int(x['boundary_distance_ft'])} ft from {wn(x['id'])}" for x in pw if x["boundary_drawdown_ft"] is not None])
            e1 = next((e for e in res["cone_edges"] if abs(e["threshold_ft"] - 1.0) < 1e-6), res["cone_edges"][0])
            edge_txt = f"{fmt_int(e1['max_ft'])} ft" if e1["max_ft"] < 5280 else f"{fmt_miles(e1['max_ft'])} miles"
            idle_txt = ""
            if res["idle_wells"]:
                idle_txt = " and " + _join([f"{fmt_ft(z['total_ft'])} ft at the idle {wn(z['id'])}" for z in res["idle_wells"]])
            sents.append(f"After {s['duration_label']} of pumping{' from ' + wn(s['focus_well']) + ' alone' if g['kind'] == 'single_well_subcase' else ''}, the simulated drawdown is {at_wells}{idle_txt}{'; ' + bnd if bnd else ''}; drawdown declines to less than {e1['threshold_ft']:g} ft at a distance of approximately {edge_txt} from the pumping center.")
            if s["duration_kind"] == "max_production":
                dur_sentences.append(f"For {'proposed ' + wn(s['focus_well']) if s['focus_well'] else 'the system'} at {fmt_int(s['total_rate_gpm'])} gpm, the annual volume of {fmt_gal(intake.permit.annual_volume_gal)} gallons is reached after {s['duration_label']}.")
        gc["results_sentence_24h"] = sents[0] if sents else ""
        gc["results_sentence_max"] = " ".join(sents[1:])
        gc["figures_text"] = _join([fig(f"dd_{s['key']}_{aq}") for s in scs])
        # summary table
        thr_list = review.decisions.cone_edge_thresholds_ft or intake.analysis.cone_edge_thresholds_ft
        if g["kind"] == "single_well_subcase":
            header = ["Pumping well", "Duration", "Drawdown at pumping well (ft)", "Drawdown at idle system well(s) (ft)"]
            rows = []
            for s in scs:
                res = s["results_by_aquifer"][aq]
                pw0 = res["pumped_wells"][0]
                idle = "; ".join(f"{wn(z['id'])}: {fmt_ft(z['total_ft'])}" for z in res["idle_wells"]) or "N/A"
                rows.append([f"{wn(pw0['id'])}", s["duration_label"], fmt_ft(pw0["total_ft"]), idle])
            eh = ["Drawdown threshold"] + [f"{wn(s['focus_well'])} pumping, {s['duration_label']}" for s in scs]
        else:
            header = ["Well", "Boundary distance (ft)"]
            for s in scs:
                header += [f"Drawdown at pumped well, {s['duration_label']} (ft)", f"Drawdown at property boundary, {s['duration_label']} (ft)"]
            rows = []
            for x in scs[0]["results_by_aquifer"][aq]["pumped_wells"]:
                row = [wn(x["id"]), fmt_int(x["boundary_distance_ft"]) if x["boundary_distance_ft"] is not None else "N/A"]
                for s in scs:
                    y = next((z for z in s["results_by_aquifer"][aq]["pumped_wells"] if z["id"] == x["id"]), None)
                    if y is None:
                        row += ["N/A", "N/A"]
                    else:
                        row += [fmt_ft(y["total_ft"]), fmt_ft(y["boundary_drawdown_ft"]) if y["boundary_drawdown_ft"] is not None else "N/A"]
                rows.append(row)
            eh = ["Drawdown threshold"] + [f"Distance to outer edge of cone, {s['duration_label']}" for s in scs]
        gc["summary_header"], gc["summary_rows"] = header, rows
        er = []
        for th in thr_list:
            row = [f"{th:g} ft"]
            for s in scs:
                e = next((e for e in s["results_by_aquifer"][aq]["cone_edges"] if abs(e["threshold_ft"] - th) < 1e-6), None)
                row.append("N/A" if e is None else (f"{fmt_int(e['max_ft'])} ft" if e["max_ft"] < 5280 else f"{fmt_miles(e['max_ft'])} mi ({fmt_int(e['max_ft'])} ft)"))
            er.append(row)
        gc["edge_header"], gc["edge_rows"] = eh, er
        # impacts table
        ih = ["Map ID", "Registration No.", "Permit No.", "Owner", "Total depth (ft)", "Screen interval (ft bgl)", "Aquifer", "Status", "Distance (ft)"]
        ih += [(f"{wn(s['focus_well'])} pumping, {s['duration_label']} (ft)" if g["kind"] == "single_well_subcase" else f"Drawdown, {s['duration_label']} (ft)") for s in scs]
        ir = []
        note_flag = False
        beyond_flag = ""
        for imp in scs[0]["results_by_aquifer"][aq]["nearby_impacts"]:
            row = [imp["map_id"], imp["registration_no"] or "N/A", imp["permit_no"], imp["owner"],
                   fmt_int(imp["total_depth_ft"]) if imp["total_depth_ft"] is not None else "N/A", imp["screen_intervals"] or "N/A",
                   (imp["aquifer"] or "N/A") + ("*" if imp["aquifer_inferred"] else ""), imp["status"], fmt_int(imp["distance_ft"])]
            for s in scs:
                j = next(z for z in s["results_by_aquifer"][aq]["nearby_impacts"] if z["map_id"] == imp["map_id"])
                # Two different reasons produce a blank cell, and a reader has to be able to tell them
                # apart: a well in another aquifer, and a well outside the aquifer this solution
                # represents at all because it lies beyond a hydraulic boundary.
                if j.get("beyond_boundary"):
                    row.append("beyond boundary ‡")
                    beyond_flag = _join(j["beyond_boundary"])
                elif j["drawdown_ft"] is None:
                    row.append("N/A")
                else:
                    row.append(fmt_ft(j["drawdown_ft"]) + ("" if j["applicability"] == "same" else " †"))
                    if j["applicability"] != "same":
                        note_flag = True
            ir.append(row)
        gc["impacts_header"], gc["impacts_rows"] = ih, ir
        base = "Drawdown estimates apply to wells completed in the " + aq + " Aquifer. "
        if note_flag:
            base += ("† Well completed in a different or unknown aquifer; value shown for completeness "
                     "only and not applicable. ")
        if beyond_flag:
            base += (f"‡ Well lies beyond the {beyond_flag}, outside the area this solution represents; "
                     "drawdown there is governed by conditions on the far side of the boundary and is "
                     "not estimated. ")
        gc["impacts_note"] = base + "* Aquifer inferred from completion depth."
        gc["aquifer"] = aq
        gc["max_impact"] = None
        same_imps = [(j["drawdown_ft"], j) for s in scs for j in s["results_by_aquifer"][aq]["nearby_impacts"] if j["applicability"] == "same" and j["drawdown_ft"] is not None and not j["is_system_well"]]
        if same_imps:
            m = max(same_imps, key=lambda t: t[0])
            gc["max_impact"] = {"ft": fmt_ft(m[0]), "owner": m[1]["owner"], "map_id": m[1]["map_id"], "distance": fmt_int(m[1]["distance_ft"])}
        groups_ctx.append(gc)

    # system interference
    si_ctx = None
    if an["system_interference"]:
        key = [k for k in an["system_interference"] if k.startswith("system_max")] or list(an["system_interference"].keys())
        mat = an["system_interference"][key[-1]]
        sc_title = next(s for s in an["scenarios"] if s["key"] == key[-1])["duration_label"]
        aq = list(mat.keys())[0]
        m = mat[aq]
        ids = m["well_ids"]
        # With a boundary in effect the image wells contribute drawdown that has no column of its own.
        # It gets one, so the Total column is the sum of the columns printed beside it.
        bnd = m.get("has_boundary_effect")
        bnd_label = _join(m.get("boundary_labels") or []) or "hydraulic boundary"
        header = (["Drawdown at (rows) caused by (columns)"] + [wn(i) for i in ids]
                  + ([f"{bnd_label} (ft)"] if bnd else []) + ["Total (ft)"])
        rows = []
        pairs = []
        for i in ids:
            r = m["rows"][i]
            rows.append([f"{wn(i)}"] + [fmt_ft(r[j]) for j in ids]
                        + ([fmt_ft(r["_boundary"])] if bnd else []) + [fmt_ft(r["_total"])])
            for j in ids:
                if j != i:
                    pairs.append(f"{wn(j)} contributes {fmt_ft(r[j])} ft of the {fmt_ft(r['_total'])} ft of drawdown at {wn(i)} ({fmt_int(m['distances'][i][j])} ft apart)")
        si_ctx = {"header": header, "rows": rows, "duration_label": sc_title,
                  "has_boundary_effect": bool(bnd), "boundary_label": bnd_label,
                  "sentence": f"For the {sc_title} maximum-production case, " + _join(pairs) + "."
                              + (f" A further column reports the drawdown contributed by the image "
                                 f"wells representing the {bnd_label}, which is part of each total but "
                                 "is not caused by another system well." if bnd else "")}

    # pumping levels
    pl_ctx = []
    for p in an["pumping_levels"]:
        if not p.get("available"):
            pl_ctx.append({"sentence": f"[REVIEWER TO PROVIDE: static water level for {wn(p['well_id'])} so the pumping level can be checked against the screen setting.]"})
            continue
        s = (f"Adding the largest simulated drawdown at proposed {wn(p['well_id'])} ({fmt_ft(p['max_drawdown_ft'])} ft, {p['scenario'].lower()}) to the estimated static water level of "
             f"{fmt_int(p['static_water_level_ft'])} ft bgl gives a theoretical pumping level of about {fmt_int(p['pumping_level_ft'])} ft bgl, which is "
             + (f"{fmt_int(p['margin_to_screen_ft'])} ft above the top of the screen at {fmt_int(p['screen_top_ft'])} ft bgl." if p["above_screen"] and p["screen_top_ft"] is not None
                else (f"below the top of the screen at {fmt_int(p['screen_top_ft'])} ft bgl; the pump setting and rate should be reviewed." if p["screen_top_ft"] is not None else "noted for pump selection.")))
        pl_ctx.append({"sentence": s})

    # summary
    first = groups_ctx[0] if groups_ctx else None
    sys_g = next((g for g in groups_ctx if g["kind"] == "system"), None)
    summary = {
        "wells_sentence": f"{applicant_short(intake)} proposes {count_text} ({prop_names}) in the {target_text}" + (f" as part of the {intake.applicant.system_name}" if intake.applicant.system_name else "") + f", with a proposed annual permit volume of {fmt_gal(intake.permit.annual_volume_gal)} gallons.",
        "params_sentence": " ".join(f"The analysis used a transmissivity of {fmt_int(p['t_ft2d'])} ft2/day and a storativity of {fmt_sci(p['s'])} for the {n} Aquifer." for n, p in an["aquifer_params"].items()),
        "results_sentence": (first["results_sentence_24h"] + " " + first["results_sentence_max"]) if first else "",
        "impacts_sentence": "",
    }
    if sys_g and sys_g.get("max_impact"):
        mi = sys_g["max_impact"]
        summary["impacts_sentence"] = f"With all system wells pumping for the maximum-production period, the largest simulated drawdown at a registered well of another owner completed in the same aquifer is {mi['ft']} ft (Map ID {mi['map_id']}, {mi['owner']}, {mi['distance']} ft from the proposed well)."
    elif first and first.get("max_impact"):
        mi = first["max_impact"]
        summary["impacts_sentence"] = f"The largest simulated drawdown at a registered well of another owner completed in the same aquifer is {mi['ft']} ft (Map ID {mi['map_id']}, {mi['owner']}, {mi['distance']} ft from the proposed well)."

    addressee = intake.report.addressee or district.get("addressee", {})
    ctx = {
        "meta": {"version": __version__, "gpm_to_cfd": f"{GPM_TO_CFD:g}", "date": long_date(intake.report.date), "title": intake.report.title,
                 "revision": fmt_int(intake.report.revision.number), "status": review.reviewer.status,
                 "banner": None if review.reviewer.status == "final" else f"DRAFT - NOT SEALED - FOR REVIEW BY {review.reviewer.name or 'LICENSED PROFESSIONAL'}",
                 "mode": intake.mode},
        "district": {"name": district["name"], "short_name": district.get("short_name", district["id"].upper()),
                     "rules_citation": "Rules 2.6(b)(15), 2.12 and 3.4" if district["id"] == "lsgcd" else "rules",
                     "addressee": addressee, "county": intake.district.county},
        "applicant": intake.applicant.model_dump(),
        "site": {"location_text": (intake.site.description if intake.site.description and "county" in intake.site.description.lower()
                                   else ((intake.site.description + ", ") if intake.site.description else "") + f"{intake.district.county} County") + ", Texas"},
        "proposed": {"count_text": count_text, "names": prop_names, "summary_sentence": prop_summary, "wells": pw_ctx,
                     "plural": "s" if n_prop > 1 else "", "singular_s": "" if n_prop > 1 else "s"},
        "existing": {"summary_sentence": ex_sentence, "wells": [w.model_dump() for w in intake.existing_wells]},
        "permit": {"annual_volume": fmt_gal(intake.permit.annual_volume_gal), "system_rate": fmt_int(intake.system_rate_gpm), "threshold_sentence": thr_sentence},
        "target": {"aquifer_text": target_text, "aquifers": target_aqs},
        "spacing": {"wells": sp_ctx, "exception_requested": intake.permit.spacing_exception_requested},
        "radii": {"search_radius_text": f"{fmt_int(geo['search_radius_ft'])}-ft", "map_radius_text": f"{geo['map_radius_ft']/5280:g} mile",
                  "half_mile": fmt_int(geo["half_mile_ft"])},
        "nearby": {"count_in_search": fmt_int(n_in), "rows": nearby_rows, "usage_sentence": usage,
                   "header": ["Map ID", "Well Registration No.", "Permit No.", "Owner", "Address", "Total depth (ft)", "Screen interval (ft bgl)", "Aquifer", "Status", "Latitude", "Longitude", "Distance from proposed well (ft)"]},
        "hydrography": {"streams_sentence": streams_sentence, "springs_sentence": springs_sentence},
        "aquifers": aq_ctx,
        "parameters": {"rows": param_rows, "header": ["Well", "Aquifer", "Transmissivity (ft2/day)", "Hydraulic conductivity (ft/day)", "Storativity", "Aquifer thickness (ft)", "Source"]},
        "wq": wq_ctx,
        "scen": {"r_w_text": _join(all_r_w), "threshold_text": _join(thresholds), "duration_sentence": " ".join(dur_sentences)},
        "sol": _solution_context(an, geo, _join),
        # None unless the intake opted in, which is what keeps the appendix out of every other report.
        "unc": (_uncertainty_context(A["uncertainty"], _join, INTERFERENCE_SECTION[intake.mode])
                if A.get("uncertainty") else None),
        "groups": groups_ctx, "si": si_ctx, "pl": pl_ctx, "summary": summary,
        "opinions": review.opinions.model_dump(), "reviewer": review.reviewer.model_dump(),
        "fignum": fignum, "tabnum": tabnum, "figures": figs,
        "flags": A["flags"], "provenance": A["provenance"],
    }
    ctx["fig"] = {k: fig(k) for k in fignum}
    ctx["fig"]["schematics"] = _join([fig(f"schematic_{w.id}") for w in intake.proposed_wells])
    ctx["tab"] = {k: tab(k) for k in tabnum}
    ctx["tab"]["matrix"] = tab("matrix_system")
    return ctx


def applicant_short(intake):
    return intake.applicant.name


def _dms(v, kind):
    from hydrostudy.geo.crs import format_dms
    return format_dms(v, kind)


def _reg_to_id(intake, reg):
    for w in intake.existing_wells:
        if w.registration_no == reg:
            return w.id
    return reg


def _wq_sentence(wq, key, label):
    s = wq["summaries"].get(key)
    if not s:
        return f"[P.G. TO PROVIDE: {label} data for nearby wells.]"
    lim = s["mcl"] if s["mcl"] is not None else s["scl"]
    limname = "MCL" if s["mcl"] is not None else "SCL"
    if s["min"] is None:
        return f"Reported {label} concentrations at the sampled wells were below detection."
    n_ex = s["n_exceed_mcl"] if s["mcl"] is not None else s["n_exceed_scl"]
    if s["n_wells"] == 1 or s["min"] == s["max"]:
        head = f"The reported {label} concentration at the sampled well is {s['min']:g} {s['units']}, which "
        tail = f"is below the {limname} of {lim:g} {s['units']}." if not n_ex else f"exceeds the {limname} of {lim:g} {s['units']}."
        return head + tail
    tail = (f"all below the {limname} of {lim:g} {s['units']}." if not n_ex else
            f"of which {fmt_int(n_ex)} sample{'s' if n_ex != 1 else ''} exceed{'s' if n_ex == 1 else ''} the {limname} of {lim:g} {s['units']}.")
    return f"Reported {label} concentrations at the sampled wells range from {s['min']:g} to {s['max']:g} {s['units']}, {tail}"


def _representative_well(project, wq):
    if not wq["wells"]:
        return None
    pw = project.intake.proposed_wells[0]
    best = None
    for w in wq["wells"]:
        score = len(w["values"])
        if w.get("depth_ft") and pw.total_depth_ft:
            score += 5 * max(0.0, 1 - abs(w["depth_ft"] - pw.total_depth_ft) / pw.total_depth_ft)
        if best is None or score > best[0]:
            best = (score, w)
    return best[1]


def _rad_table(wq):
    keys = [k for k in ("gross_alpha", "gross_beta", "ra_combined", "uranium")]
    header = ["Well", "Sample date"] + [f"{wq['limits'][k]['label']} ({wq['limits'][k]['units']})" for k in keys]
    rows = [["TCEQ MCL", ""] + [f"{wq['limits'][k]['mcl']:g}" for k in keys]]
    red = set()
    for w in wq["wells"]:
        if not any(k in w["values"] for k in keys):
            continue
        row = [w["well_name"] or w["well_id"], w["sample_date"]]
        for j, k in enumerate(keys):
            v = w["values"].get(k)
            if v is None:
                row.append("NA")
            elif v["nd"]:
                row.append("ND")
            else:
                row.append(f"{v['value']:g}")
                if v["exceeds_mcl"]:
                    red.add((len(rows), 2 + j))
        rows.append(row)
    return rows, header, red


def _panel_table(wq):
    keys = [k for k in wq["constituent_order"] if k not in ("gross_alpha", "gross_beta", "ra_combined", "uranium", "hardness")]
    header = ["Well"] + [wq["limits"][k]["label"] for k in keys]
    lim_row = ["TCEQ MCL / SCL"]
    for k in keys:
        L = wq["limits"][k]
        parts = []
        if L.get("mcl") is not None:
            parts.append(f"{L['mcl']:g} (MCL)")
        if L.get("scl") is not None:
            parts.append(f"{L['scl']:g} (SCL)")
        if L.get("scl_min") is not None:
            parts.append(f">{L['scl_min']:g} (SCL)")
        if L.get("action_level") is not None:
            parts.append(f"{L['action_level']:g} (AL)")
        lim_row.append("; ".join(parts) or "NA")
    rows = [lim_row]
    red = set()
    for w in wq["wells"]:
        if not any(k in w["values"] for k in keys):
            continue
        row = [w["well_name"] or w["well_id"]]
        for j, k in enumerate(keys):
            v = w["values"].get(k)
            if v is None:
                row.append("NA")
            elif v["nd"]:
                row.append("ND")
            else:
                row.append(f"{v['value']:g}")
                if v["exceeds_mcl"] or v["exceeds_scl"] or v["exceeds_action"]:
                    red.add((len(rows), 1 + j))
        rows.append(row)
    return rows, header, red


def _lc(label: str) -> str:
    """Lower-case a constituent label unless it is an acronym/chemical symbol."""
    return label if label.isupper() or label in ("pH",) else label[0].lower() + label[1:]
