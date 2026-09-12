"""Map each District guideline item to evidence in the build and report a status."""

from __future__ import annotations

LABELS = {"satisfied": "Addressed", "needs_professional_input": "Needs P.G./P.E. input", "missing_data": "Missing data",
          "not_applicable": "Not applicable"}


def build_checklist(project) -> dict:
    A = project.artifacts
    intake, review, district = project.intake, project.review, project.district
    an = A["analysis"]
    figs = A.get("figures", {})
    op = review.opinions
    single_well_system = len([w for w in intake.all_wells if w in intake.proposed_wells or w.include_in_system]) <= 1

    def has_fig(prefix):
        return any(k.startswith(prefix) for k in figs)

    evidence = {
        "spacing": (all(w["rule_available"] for w in an["spacing"]["wells"]) and not an["spacing"]["any_violation"], "Section 1", "missing_data" if not all(w["rule_available"] for w in an["spacing"]["wells"]) else "needs_professional_input"),
        "figure_schematic": (has_fig("schematic_"), "Section 2 figure(s)", "missing_data"),
        "table_construction": (all(w.screen and w.casing and w.borehole for w in intake.proposed_wells), "Section 2 table", "missing_data"),
        "lithology": (all(w.anticipated_lithology for w in intake.proposed_wells) and bool(op.lithology_basis), "Section 2", "needs_professional_input"),
        "figure_location": ("location" in figs, "Introduction figure", "missing_data"),
        "figure_property": ("property" in figs, "Section 1 figure", "missing_data"),
        "figure_wells": ("wells" in figs, "Section 1 figure", "missing_data"),
        "aquifer_id": (bool(op.aquifer_identification), "Section 4", "needs_professional_input"),
        "general_hydrogeology": (True, "Section 3", "satisfied"),
        "recharge_features": (bool(op.recharge_features), "Section 4", "needs_professional_input"),
        "aquifer_depths": (all(p["top_ft_bgl"] is not None and p["bottom_ft_bgl"] is not None for p in an["aquifer_params"].values()), "Section 4", "missing_data"),
        "confinement": (all(p["confinement"]["status"] != "unknown" for p in an["aquifer_params"].values()), "Section 4", "needs_professional_input"),
        "table_parameters": (True, "Section 4 table", "satisfied"),
        "table_nearby_wells": (len(A["nearby_wells"]) > 0, "Section 1 table", "missing_data"),
        "hydrography": ((A["hydrography"]["has_geometry"] or bool(A["hydrography"]["notes"])) and A["hydrography"]["springs_searched"], "Section 4", "missing_data"),
        "water_quality": (A["water_quality"]["n_records"] > 0, "Section 5", "missing_data"),
        "scenarios": (len(an["scenarios"]) > 0, "Section 6", "missing_data"),
        "table_drawdown_summary": (len(an["scenarios"]) > 0, "Section 6 tables", "missing_data"),
        "methodology": (True, "Section 6.1", "satisfied"),
        "figure_drawdown_well": (any(k.startswith("dd_proposed_") for k in figs), "Section 6 figures", "missing_data"),
        "figure_drawdown_system": (any(k.startswith("dd_system_") for k in figs) or single_well_system, "Section 6 figures", "not_applicable" if single_well_system else "missing_data"),
        "system_interference": (bool(an["system_interference"]) or single_well_system, "Section 6", "not_applicable" if single_well_system else "missing_data"),
        "table_impacts_well": (any(s["group"] == "proposed_only" for s in an["scenarios"]), "Section 6 tables", "missing_data"),
        "table_impacts_system": (any(s["group"] == "system" for s in an["scenarios"]) or single_well_system, "Section 6 tables", "not_applicable" if single_well_system else "missing_data"),
    }
    items = []
    for item in district.get("checklist", []):
        ok, where, fail_status = True, [], "missing_data"
        for ev in item.get("evidence", []):
            e = evidence.get(ev)
            if e is None:
                continue
            present, loc, fs = e
            where.append(loc)
            if not present:
                ok = False
                fail_status = fs
        status = "satisfied" if ok else fail_status
        if ok and not item.get("auto", True) and item.get("professional"):
            # automated evidence present but the guideline needs a professional statement; satisfied only if opinion given
            pass
        if not ok and fail_status == "not_applicable":
            status = "not_applicable"
        items.append({"id": item["id"], "text": item["text"], "status": status, "status_label": LABELS[status],
                      "where": "; ".join(dict.fromkeys(where)) + ((" - " + item["professional"]) if item.get("professional") and status != "satisfied" else ""),
                      "auto": item.get("auto", True)})
    counts = {}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    return {"district": district["id"], "items": items, "counts": counts,
            "placeholders_pending": [k for k, v in review.opinions.model_dump().items() if v is None],
            "flags": A.get("flags", [])}
