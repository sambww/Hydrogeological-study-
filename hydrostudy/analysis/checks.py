"""Cross-checks that produce flags for the reviewer."""

from __future__ import annotations


def collect_flags(intake, review, aquifer_params, spacing, scenarios, pumping_levels, hydrography, wq, district_id="lsgcd") -> list[dict]:
    flags = []

    def add(level, code, text):
        flags.append({"level": level, "code": code, "text": text})

    for aq, p in aquifer_params.items():
        if p.get("gam_mismatch"):
            add("review", "GAM_MISMATCH", f"{aq}: {p['gam_note']}.")
        if p["k_derived"]:
            add("info", "K_DERIVED", f"{aq}: hydraulic conductivity derived as T/b = {p['k_ftd']:.2f} ft/day.")
        if p["top_ft_bgl"] is None or p["bottom_ft_bgl"] is None:
            add("warn", "AQUIFER_DEPTHS_MISSING", f"{aq}: aquifer top/bottom not provided; thickness statements omitted.")
        if p["confinement"]["status"] == "unknown":
            add("review", "CONFINEMENT_UNKNOWN", f"{aq}: confined/unconfined status must be stated by the reviewer.")
        if p["source_kind"] == "gam" and not p["model_version"]:
            add("review", "GAM_VERSION", f"{aq}: GAM version not cited for the parameters.")
    for w in spacing["wells"]:
        if not w["rule_available"]:
            add("info" if district_id == "generic" else "warn", "SPACING_RULE_MISSING", f"{w['well_id']}: no spacing multiplier configured for {w['aquifer']}.")
        if w["conflicts"]:
            add("review", "SPACING_CONFLICT", f"{w['well_id']}: {len(w['conflicts'])} well(s) inside the required "
                f"{w['required_spacing_ft']:,.0f}-ft spacing radius; exception documentation required.")
        if w["same_system_inside"]:
            add("info", "SAME_SYSTEM_INSIDE_RADIUS", f"{w['well_id']}: applicant's own well(s) inside the spacing radius "
                f"(map IDs {[x['map_id'] for x in w['same_system_inside']]}); confirm treatment with the District.")
    other_aq = False
    for sc in scenarios:
        for f in sc["duration_flags"]:
            add("warn", "DURATION", f"{sc['title']}: {f}")
        for res in sc["results_by_aquifer"].values():
            if any(i["applicability"] != "same" and i["drawdown_ft"] is not None for i in res["nearby_impacts"]):
                other_aq = True
    if other_aq:
        add("info", "OTHER_AQUIFER_WELLS", "Drawdown values reported at wells completed in other or unknown aquifers are not applicable and are footnoted in the impact tables.")
    for aq, p in aquifer_params.items():
        for d in p["derivations"]:
            if d.get("mismatch_note"):
                add("review", "T_MISMATCH", f"{aq}: {d['mismatch_note']}")
    for pl in pumping_levels:
        if pl.get("available") and not pl["above_screen"]:
            add("warn", "PUMPING_LEVEL_BELOW_SCREEN", f"{pl['well_id']}: predicted pumping level {pl['pumping_level_ft']:.0f} ft bgl "
                f"is below the top of screen ({pl['screen_top_ft']:.0f} ft bgl) in scenario '{pl['scenario']}'.")
        if pl.get("available") and not pl["above_pump"]:
            add("warn", "PUMPING_LEVEL_BELOW_PUMP", f"{pl['well_id']}: predicted pumping level is below the pump setting.")
    if not hydrography["has_geometry"] and not hydrography["notes"]:
        add("warn", "HYDROGRAPHY_MISSING", "No streams/ponds data supplied; guideline II.B.3(i) statement will be a placeholder.")
    if not hydrography["springs_searched"]:
        add("warn", "SPRINGS_NOT_SEARCHED", "Springs search not recorded in the manifest.")
    if wq["n_records"] == 0:
        add("warn", "WATER_QUALITY_MISSING", "No water-quality records supplied; section II.B.4 will be a placeholder.")
    for k, v in review.opinions.model_dump().items():
        if v is None:
            add("review", "OPINION_" + k.upper(), f"Reviewer opinion '{k}' not provided; placeholder inserted.")
    if review.reviewer.status != "final":
        add("info", "DRAFT", "Report status is not final; DRAFT banner applied.")
    if intake.report.issuing_firm == "ballard":
        add("review", "ISSUING_FIRM", "Report is on Ballard letterhead. Confirm with the sealing professional whether the "
            "issuing entity must hold a TBPG/TBPE firm registration.")
    return flags
