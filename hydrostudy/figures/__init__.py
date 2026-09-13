"""Figure rendering. render_all(project) -> {key: {"path", "caption", "kind"}} in document order."""

from __future__ import annotations

from hydrostudy.figures import (
    distance_drawdown,
    drawdown_map,
    gam_maps,
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
    for aq in sorted({w.aquifer for w in intake.proposed_wells}):
        for param in ("t", "k", "s"):
            r = gam_maps.render(project, aq, param, out_dir / f"fig_gam_{param}_{aq}.png")
            if r:
                figs[f"gam_{param}_{aq}"] = r
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


def render_all_post(project) -> dict:
    """Post-drilling figures: as-built schematic, aquifer-test plots, water-quality maps, and (if re-run) drawdown maps."""
    from types import SimpleNamespace

    from hydrostudy.figures import pumptest
    out_dir = project.build_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    a = project.artifacts
    intake = project.intake
    ab = intake.as_built
    well = next(w for w in intake.proposed_wells if w.id == ab.well_id)
    c = ab.construction
    view = SimpleNamespace(id=well.id, label=well.label, aquifer=well.aquifer, total_depth_ft=c.total_depth_ft, borehole=c.borehole,
                           casing=c.casing, blank_liner=c.blank_liner, screen=c.screen, cement=c.cement, filter_pack=c.filter_pack,
                           packer_depth_ft=c.packer_depth_ft, static_water_level_ft=ab.static_water_level_ft,
                           pump_setting_ft=ab.pump.setting_ft, pump_diameter_in=ab.pump.diameter_in,
                           anticipated_lithology=c.lithology or well.anticipated_lithology, elevation_ft_msl=well.elevation_ft_msl,
                           title_prefix="As-built", caption=f"As-built well profile and logged lithology, {well.label}")
    figs: dict = {"schematic_asbuilt": well_schematic.render(project, view, out_dir / "fig_schematic_asbuilt.png")}
    for t in a["as_built"]["tests"]:
        if t["kind"] == "constant_rate":
            figs[f"cj_{t['id']}"] = pumptest.render_cooper_jacob(t, out_dir / f"fig_cj_{t['id']}.png")
            figs[f"theis_{t['id']}"] = pumptest.render_theis_match(t, out_dir / f"fig_theis_{t['id']}.png")
        if t.get("recovery"):
            figs[f"recovery_{t['id']}"] = pumptest.render_recovery(t, out_dir / f"fig_recovery_{t['id']}.png")
        if t["kind"] == "step":
            figs[f"step_{t['id']}"] = pumptest.render_step_test(t, out_dir / f"fig_step_{t['id']}.png")
    for key in ("tds", "fe", "as", "ra_combined"):
        r = water_quality_map.render(project, key, out_dir / f"fig_wq_{key}.png")
        if r:
            figs[f"wq_{key}"] = r
    if a["as_built"]["rerun_interference"]:
        for sc in a["analysis"]["scenarios"]:
            for aq in sc["results_by_aquifer"]:
                figs[f"dd_{sc['key']}_{aq}"] = drawdown_map.render(project, sc, aq, out_dir / f"fig_dd_{sc['key']}_{aq}.png")
        figs["distance_drawdown"] = distance_drawdown.render(project, out_dir / "fig_distance_drawdown.png")
    return {k: v for k, v in figs.items() if v}
