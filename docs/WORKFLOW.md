# Workflow: from a well proposal to a sealed report

First time on a machine: follow `docs/RUNBOOK.md` section A (setup and `hydrostudy doctor`).

1. **Scaffold** `hydrostudy new projects/<slug>` (copies the example intake, review and manifest), or fill the web
   intake sheet and run `hydrostudy import-intake projects/<slug> <submission>.json` (see `docs/RUNBOOK.md` section H).
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
   - optional GeoJSON: `streams.geojson`, `parcels.geojson`, `boundary.geojson` (fills the nearest-boundary distance
     automatically), `county.geojson`; optional `springs.csv`; optional `gam_lookup.json` from `scripts/build_gam_lookup.py`
   - hydrography notes and the springs search result in the manifest
4. **Validate**: `hydrostudy validate projects/<slug>`.
4a. **Site the well, before the design is fixed**: `hydrostudy siting projects/<slug>` answers where on the tract the
   well may go and what it can produce there, rather than whether one chosen spot works. Needs the tract polygon
   (`site.boundary_geojson` or a manifest `boundary`) and `district_wells.csv`. See `docs/RUNBOOK.md` section I.
4b. **Or design the whole field**: `hydrostudy wellfield projects/<slug> --rate 700` decides how many
   wells, where and at what rate each to meet a demand, and prints the trade-off against well count. Write
   the chosen field into `proposed_wells` and carry on. See `docs/RUNBOOK.md` section K.
5. **Run**: `hydrostudy run projects/<slug>`. Read the console summary: scenario results, checklist, placeholders, flags.
5a. **Quantify the confidence** (optional, and worth it for a contested system):
   `hydrostudy uncertainty projects/<slug> --threshold-ft <the figure that matters>`. Needs a declared
   spread on the aquifer's parameters; see `docs/RUNBOOK.md` section L.
6. **Reviewer pass**: build the reviewer's sheet with `hydrostudy review-sheet projects/<slug>` and have Claude
   publish it, or let the P.G./P.E. fill `review.yaml` directly (`opinions`, any `decisions` overrides, reviewer
   identity). Import a sheet submission with `hydrostudy import-review projects/<slug> <submission>.json`,
   confirms aquifer identification and parameters with District staff, then re-runs. Set `reviewer.status: final`
   and bump `report.revision.number` for the sealed version.
7. **Submit** the sealed DOCX/PDF with the District application. After drilling, prepare the post-drilling
   submittal (Guidelines Section III) - a Phase 2 mode.

Solutions: the default is Theis with no boundaries, which is what the District's guidelines contemplate.
`analysis.solution: hantush` plus a cited leakance on the aquifer's `confinement` block runs the
Hantush-Jacob leaky solution; `analysis.boundaries` adds barrier or recharge boundaries by the method of
images. Both are opt-in, both change the methodology narrative to match, and both are documented in
`docs/RUNBOOK.md` section J.

Scenario logic (LSGCD): proposed well alone and all same-aquifer system wells, each at 24 hours and at
`annual_volume / (rate x 1440)` days ("maximum production"). Feasibility mode: fixed durations (e.g. 10 and 20 years)
with optional single-well sub-cases.

## Post-drilling submittal (Guidelines Section III)

After the well is drilled, logged and tested:
1. Copy the pre-drilling project (or scaffold a new one) and set `mode: lsgcd_post_drilling`.
2. Add an `as_built:` block (see `examples/black_oak_well_2_post/intake.yaml`): as-built construction (borehole,
   casing, blank liner, screen, cement, filter pack, packer), completion date and TDLR tracking number, static water
   level and date, permanent pump (diameter, setting, hp), geophysical log inventory with LAS files, aquifer tests
   (constant-rate with recovery, step test) with their CSV data files, field parameters, and a reference to the
   pre-drilling `build/analysis.json` for comparison.
3. Put the post-construction lab results in the water-quality CSV with `well_id` = the new well.
4. `hydrostudy run projects/<well>_post`. The pipeline fits Cooper-Jacob, Theis and recovery to the constant-rate
   test, Jacob's method to the step test, adopts a transmissivity, compares it with the pre-drilling value, re-runs
   the interference scenarios with the measured transmissivity (`rerun_interference: true`), and writes the Section III
   report with the log inventory, test summary, parameter table, field parameters and lab results.

Test CSV format: `elapsed_min` plus `drawdown_ft` or `water_level_ft` (ft bgl); optional `rate_gpm`, `phase`
(pumping|recovery) and `t_since_stop_min`. Storativity cannot be determined from a single-well test; it is held at the
pre-drilling value unless an observation well is recorded (`observation_well: {id, distance_ft}`).
