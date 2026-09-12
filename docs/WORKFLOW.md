# Workflow: from a well proposal to a sealed report

1. **Scaffold** `hydrostudy new projects/<slug>` (copies the example intake, review and manifest).
2. **Fill `intake.yaml`** (driller's inputs):
   - applicant, PWS name and ID, county, district (`lsgcd` or `generic`)
   - each proposed well: coordinates (decimal or DMS), ground elevation, aquifer, max rate (gpm), total depth,
     borehole / casing / screen / cement / filter-pack intervals, packer, estimated static water level, anticipated
     lithology intervals, nearest property-boundary distance, optional `r_w_ft`
   - existing system wells: registration and permit numbers, coordinates, aquifer, max rate, depth, screen
   - permit: annual volume (gal); spacing exception flag
   - aquifers: top/bottom at the site, confinement, T / S (and K) with the source (GAM version or site test)
3. **Drop data files** into `data/` and describe them in `data/manifest.yaml` (see DATA_SOURCES.md):
   - `district_wells.csv` (District export of registered/permitted wells; required)
   - `water_quality_samples.csv` (TCEQ / TWDB samples, long format; strongly recommended)
   - optional GeoJSON: `streams.geojson`, `parcels.geojson`, `boundary.geojson`, `county.geojson`
   - hydrography notes and the springs search result in the manifest
4. **Validate**: `hydrostudy validate projects/<slug>`.
5. **Run**: `hydrostudy run projects/<slug>`. Read the console summary: scenario results, checklist, placeholders, flags.
6. **Reviewer pass**: the P.G./P.E. fills `review.yaml` (`opinions`, any `decisions` overrides, reviewer identity),
   confirms aquifer identification and parameters with District staff, then re-runs. Set `reviewer.status: final`
   and bump `report.revision.number` for the sealed version.
7. **Submit** the sealed DOCX/PDF with the District application. After drilling, prepare the post-drilling
   submittal (Guidelines Section III) - a Phase 2 mode.

Scenario logic (LSGCD): proposed well alone and all same-aquifer system wells, each at 24 hours and at
`annual_volume / (rate x 1440)` days ("maximum production"). Feasibility mode: fixed durations (e.g. 10 and 20 years)
with optional single-well sub-cases.
