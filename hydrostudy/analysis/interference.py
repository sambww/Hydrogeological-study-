"""System interference matrix and pumping-level checks."""

from __future__ import annotations


def system_interference_matrix(scenario: dict) -> dict:
    """For system scenarios: drawdown (ft) at each system well caused by each other system well."""
    matrix = {}
    for aq, res in scenario["results_by_aquifer"].items():
        ids = [p["id"] for p in res["pumped_wells"]]
        rows = {}
        for p in res["pumped_wells"]:
            row = {}
            for other in ids:
                row[other] = p["self_ft"] if other == p["id"] else p["contributions_ft"].get(other, 0.0)
            row["_total"] = p["total_ft"]
            rows[p["id"]] = row
        matrix[aq] = {"well_ids": ids, "rows": rows, "distances": {p["id"]: p["distances_ft"] for p in res["pumped_wells"]}}
    return matrix


def pumping_level_checks(intake, scenarios: list[dict]) -> list[dict]:
    """Static water level + predicted drawdown vs. top of screen and pump setting (proposed wells)."""
    out = []
    for w in intake.proposed_wells:
        if w.static_water_level_ft is None:
            out.append({"well_id": w.id, "available": False, "reason": "static water level not provided"})
            continue
        screen_top = min(s.top_ft for s in w.screen) if w.screen else None
        worst = None
        for sc in scenarios:
            for res in sc["results_by_aquifer"].values():
                for p in res["pumped_wells"]:
                    if p["id"] == w.id and (worst is None or p["total_ft"] > worst[1]):
                        worst = (sc["title"], p["total_ft"])
        if worst is None:
            continue
        pl = w.static_water_level_ft + worst[1]
        rec = {"well_id": w.id, "available": True, "static_water_level_ft": w.static_water_level_ft,
               "max_drawdown_ft": worst[1], "scenario": worst[0], "pumping_level_ft": pl,
               "screen_top_ft": screen_top, "pump_setting_ft": w.pump_setting_ft,
               "above_screen": (screen_top is None) or (pl < screen_top),
               "above_pump": (w.pump_setting_ft is None) or (pl < w.pump_setting_ft),
               "margin_to_screen_ft": (screen_top - pl) if screen_top is not None else None}
        out.append(rec)
    return out
