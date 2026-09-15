"""Well spacing compliance (district rule: multiplier x maximum pumping rate)."""

from __future__ import annotations

from hydrostudy.districts.status import rule_status


def spacing_analysis(intake, district, nearby: list[dict], status: dict | None = None) -> dict:
    status = status or rule_status(district)
    out = {"rule_reference": district.get("spacing", {}).get("rule_reference"), "wells": [], "any_violation": False,
           "exception_requested": intake.permit.spacing_exception_requested, "rule_status": status}
    for w in intake.proposed_wells:
        mult = district.spacing_ft_per_gpm(w.aquifer)
        req = district.required_spacing_ft(w.aquifer, w.max_rate_gpm)
        inside = [n for n in nearby if req is not None and n["distance_by_well"].get(w.id, 1e12) <= req]
        conflicts = [n for n in inside if not n["is_system_well"] and n["status"].lower() not in ("plugged", "void", "void - application withdrawn")]
        same_system = [n for n in inside if n["is_system_well"]]
        rec = {
            "well_id": w.id, "aquifer": w.aquifer, "max_rate_gpm": w.max_rate_gpm,
            "ft_per_gpm": mult, "required_spacing_ft": req,
            "wells_inside_radius": [n["map_id"] for n in inside],
            "conflicts": [{"map_id": n["map_id"], "registration_no": n["registration_no"], "owner": n["owner"],
                           "distance_ft": n["distance_by_well"][w.id], "status": n["status"]} for n in conflicts],
            "same_system_inside": [{"map_id": n["map_id"], "registration_no": n["registration_no"],
                                    "distance_ft": n["distance_by_well"][w.id]} for n in same_system],
            "complies": (req is not None) and not conflicts,
            "rule_available": req is not None,
            # "provisional" means the distance was computed from a multiplier that was not read from the District's
            # own rules document (or whose reading is stale), so the conclusion is not yet a statement of compliance.
            "provisional": (req is not None) and not status["spacing_authoritative"],
        }
        out["wells"].append(rec)
        if conflicts:
            out["any_violation"] = True
    out["threshold_gpm"] = district.get("report_threshold_gpm")
    out["system_rate_gpm"] = intake.system_rate_gpm
    out["report_required"] = (district.get("report_threshold_gpm") is not None
                              and intake.system_rate_gpm >= district["report_threshold_gpm"])
    return out
