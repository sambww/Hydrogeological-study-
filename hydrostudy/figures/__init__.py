"""Figure rendering. render_all(project) -> {key: {"path", "caption", "kind"}} in document order."""

from __future__ import annotations

from hydrostudy.figures import (
    distance_drawdown,
    drawdown_map,
    location_map,
    property_map,
    strat_column,
    water_quality_map,
    well_schematic,
    wells_map,
)


def render_all(project) -> dict:
    out_dir = project.build_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    figs: dict = {}
    a = project.artifacts
    intake = project.intake
    figs["location"] = location_map.render(project, out_dir / "fig_location.png")
    figs["wells"] = wells_map.render(project, out_dir / "fig_wells.png")
    figs["property"] = property_map.render(project, out_dir / "fig_property.png")
    for w in intake.proposed_wells:
        figs[f"schematic_{w.id}"] = well_schematic.render(project, w, out_dir / f"fig_schematic_{w.id}.png")
    figs["strat"] = strat_column.render(project, out_dir / "fig_strat_column.png")
    for key in ("tds", "fe", "as", "ra_combined"):
        r = water_quality_map.render(project, key, out_dir / f"fig_wq_{key}.png")
        if r:
            figs[f"wq_{key}"] = r
    for sc in a["analysis"]["scenarios"]:
        for aq in sc["results_by_aquifer"]:
            r = drawdown_map.render(project, sc, aq, out_dir / f"fig_dd_{sc['key']}_{aq}.png")
            figs[f"dd_{sc['key']}_{aq}"] = r
    figs["distance_drawdown"] = distance_drawdown.render(project, out_dir / "fig_distance_drawdown.png")
    return {k: v for k, v in figs.items() if v}
