# Operator runbook: validating hydrostudy on your machine and running a real project

Audience: Samuel (or whoever runs reports). Assumes a Mac or Windows laptop with internet access. Commands are shown
for a Unix shell; on Windows PowerShell use `.venv\Scripts\` in place of `.venv/bin/`.

Everything in sections B and C exists in the repo but was written in a sandbox that blocks the public data hosts, so
those steps are the first real test. Report failures as described in each step.

## A. One-time setup

1. Install Python 3.11 or newer and git. Install LibreOffice (the full desktop package includes Writer; PDF export needs it).
2. Clone and set up:
   ```
   git clone https://github.com/sambww/Hydrogeological-study-.git
   cd Hydrogeological-study-
   python3 -m venv .venv
   .venv/bin/pip install -e ".[dev,connectors,gam]"
   .venv/bin/hydrostudy doctor --network
   .venv/bin/pytest
   ```
3. `doctor` must show no FAIL lines. WARN lines for `flopy` or LibreOffice only limit the GAM script or PDF export.
   Every `reach ...` line should be PASS on a normal internet connection; a WARN there means a firewall or proxy is in
   the way and the connectors will not work until it is cleared.
4. Expected test result: all tests pass (one PDF test is skipped if LibreOffice Writer is absent).
5. Smoke test the pipeline on a known example and open the PDF:
   ```
   .venv/bin/hydrostudy run examples/black_oak_well_2
   open examples/black_oak_well_2/build/report_v1_draft.pdf
   ```

## B. Validate the data connectors

Run against the Black Oak example so results can be judged against known values.

1. Find the Montgomery County parcel layer URL: open the county open-data portal (data-moco.opendata.arcgis.com),
   search "MCAD Tax Parcel View", open the dataset, and copy the FeatureServer layer URL from its API / "I want to use
   this" panel (it ends in `/FeatureServer/0`).
2. Run the fetch script (the TWDB archives are several hundred MB; add `--skip-twdb` the first time if bandwidth is limited):
   ```
   .venv/bin/python scripts/fetch_public_data.py examples/black_oak_well_2 --parcels-layer "<layer URL>"
   ```
3. Expected output and what to send back if a step fails (paste the printed line and the URL it names):
   - Elevations: Well No. 2 near 166 ft MSL (the report used a topo-map value of 166).
   - Hydrography: `data/streams.geojson` written; feature names should include Dry Creek and Spring Creek within
     the 1.5-mile radius. If the NHD layer ids have changed the count will be 0: open the service URL printed in
     `hydrostudy/connectors/hydrography.py` in a browser, note the current layer numbers for NHDFlowline and
     NHDWaterbody, and report them.
   - Parcels: a non-zero count and `data/parcels.geojson` written.
   - TWDB: two zip files cached under `data/cache/` and a table listing printed. Send the listing; the well and
     water-quality tables need a one-time column mapping (`hydrostudy/connectors/twdb.py::write_standard_wells_csv`).
4. Re-run the report and confirm the maps now show the stream and parcel layers:
   ```
   .venv/bin/hydrostudy run examples/black_oak_well_2
   ```
   Note: the manifest written by the script adds the `streams` and `parcels` entries; the location map gets a county
   outline only if you also add a `county` GeoJSON (TxDOT county boundaries, exported as WGS84 GeoJSON).

## C. Validate the GAM sampling script

Purpose: replace hand-typed aquifer parameters with values read from the model at the well's cell, and get the three
parameter maps the consultants include.

1. Get model files (either works; the District guidelines cite HAGM, GMA 14 adopted v4.1 in 2026):
   - HAGM (Kasmarek 2013): model archive linked from USGS SIR 2012-5154 (pubs.usgs.gov/sir/2012/5154). MODFLOW-2000.
   - Northern Gulf Coast GAM v4.1: TWDB GAM page for the northern Gulf Coast (glfc_n). MODFLOW 6.
2. Run for the Black Oak site (Evangeline Aquifer). Layer names must be given in model layer order:
   ```
   # MODFLOW 6 (GAM v4.x)
   .venv/bin/python scripts/build_gam_lookup.py --engine mf6 --model-dir /path/to/gam_v41 \
       --lat 30.170167 --lon -95.578097 --layers "Chicot,Evangeline,Burkeville,Jasper" \
       --model-name "Northern Gulf Coast GAM" --version v4.1 --out examples/black_oak_well_2/data/gam_lookup.json

   # MODFLOW-2000 (HAGM); supply the grid georeference if the name file lacks it
   .venv/bin/python scripts/build_gam_lookup.py --engine mf2k --model-dir /path/to/hagm --name-file hagm.nam \
       --epsg 32139 --xoff <x> --yoff <y> --angrot <deg> \
       --lat 30.170167 --lon -95.578097 --layers "Chicot,Evangeline,Burkeville,Jasper" \
       --model-name "Houston Area Groundwater Model" --version "v1.1" --out examples/black_oak_well_2/data/gam_lookup.json
   ```
   The HAGM grid is 137 rows by 245 columns of 1-mile cells; the model documentation states its projection and origin.
3. Acceptance check (HAGM, Evangeline layer at the Black Oak site, values the 2023 consultant report read from the same
   model): transmissivity about 1,231 ft2/day, hydraulic conductivity about 1.2 ft/day, storativity 3.36e-4, top about
   260 ft bgl, base about 944 ft bgl. Values within roughly 10 percent confirm the grid georeference and unit handling;
   a large miss usually means the wrong EPSG/offset (wrong cell) or the layer list is out of order. v4.1 values will
   differ from HAGM; sanity-check them against the report's GAM figures instead.
4. Attach the lookup to the project: add to `data/manifest.yaml`
   ```
   files:
     gam_lookup: {path: gam_lookup.json, source: "HAGM v1.1 sampled with scripts/build_gam_lookup.py", retrieved: "2026-09-20"}
   ```
   and re-run. Three new figures (T, K, S around the site) appear after the parameter table. If the intake states a
   transmissivity more than 25 percent from the model's, a `GAM_MISMATCH` review flag is printed.
5. If the script errors inside flopy, send the full traceback plus `pip show flopy` output and the model folder listing.

## D. Stand up a real LSGCD project

1. Scaffold: `.venv/bin/hydrostudy new projects/<system>_<well>`.
2. District well export (Guidelines II.B.3(h)): ask LSGCD permitting for the registered and permitted wells within one
   mile of the proposed well with registration and permit numbers, owner, address, total depth, screened interval,
   aquifer, status, latitude and longitude. Save as `data/district_wells.csv` with those column names (see
   `docs/DATA_SOURCES.md` for the exact headers; other headers can be mapped in the manifest).
3. Water quality: in the TCEQ Drinking Water Viewer, open the nearest public water systems (yours first), export the
   chemical sample results for their entry points, and reshape to the long format `well_id, well_name, source,
   sample_date, lat, lon, depth_ft, aquifer, constituent, value, units, qualifier` (constituent keys are listed in
   `docs/DATA_SOURCES.md`). Add TWDB Groundwater Database samples for nearby wells of similar depth when available.
4. Property and parcels: export your tract polygon and the surrounding parcels from the county portal as WGS84
   GeoJSON into `data/`; set `site.boundary_geojson: data/boundary.geojson` in `intake.yaml`. The nearest-boundary
   distance is then measured for you.
5. Fill `intake.yaml` from the well design. Field checklist (units in the file):
   - applicant name, PWS name and ID, county, district `lsgcd`
   - each proposed well: display name, latitude/longitude (decimal or DMS, west longitudes negative), ground elevation
     (ft MSL), aquifer, maximum rate (gpm), total depth, borehole / casing / screen / cement / filter-pack intervals
     (ft bgl, diameters in inches), packer depth, estimated static water level, anticipated lithology intervals
   - existing system wells: registration and permit numbers, coordinates, aquifer, maximum rate, depth, screen
   - permit: annual volume (gallons); spacing exception flag if needed
   - aquifers: top/bottom at the site, confinement, T and S with their source (GAM version, or a nearby pump test
     under `site_test`) or leave T/S/top/bottom blank and attach a GAM lookup
6. Fill `data/manifest.yaml` (sources and retrieval dates for every file, hydrography notes if no streams layer, the
   springs search result). Provenance goes into Appendix B of the report.
7. Run:
   ```
   .venv/bin/hydrostudy validate projects/<slug>
   .venv/bin/hydrostudy run projects/<slug>
   ```
   Read the console summary: drawdown per scenario, spacing result, checklist counts, `[P.G. TO PROVIDE]` placeholders
   and flags. Open `build/figures/*.png` and the PDF. Fix inputs and re-run until only reviewer items remain.

## E. Reviewer hand-off

1. Send the sealing P.G. or P.E. the DOCX, the PDF and the placeholder list. They edit `review.yaml`: their identity
   and license, `decisions` (T, S, effective radius, thresholds) and `opinions` (conclusion, aquifer identification,
   recharge features, confinement, water quality, parameter selection, spacing).
2. Re-run with their `review.yaml`. For the sealed version set `reviewer.status: final` and bump
   `report.revision.number`; the banner disappears and the review-log appendix is dropped. Final files are never
   overwritten.
3. Settle the issuing-entity question before the first submittal: a sealed geoscience report is generally issued by a
   TBPG-registered firm. `report.issuing_firm` switches the letterhead between Ballard and the reviewer's firm.
4. After drilling, copy the project, set `mode: lsgcd_post_drilling`, fill `as_built` (construction, static level,
   pump, logs with LAS files, test CSVs, field parameters) and run again for the Section III submittal. See
   `docs/WORKFLOW.md`.

## F. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "PDF not produced: LibreOffice ..." | Writer component missing | Install the full LibreOffice package; `hydrostudy doctor` |
| `LINT FAILURE: narrative contains numbers ...` | a template or opinion text carries a number the pipeline did not compute | Numbers in `review.yaml` opinions are allowed only if they appear in the results; otherwise cite them as words or put them in a table; `--no-strict-lint` writes the report anyway with the problem listed |
| `intake.yaml is invalid: ... longitudes ... must be negative` | west longitude entered positive | prefix with `-` or use DMS with `W` |
| well listed with `N/A` depth or aquifer `*` | District export lacks completion data | acceptable; the aquifer is inferred from depth and footnoted, or fill from the TWDB driller's report |
| `RATE_VARIATION` flag on a post-drilling test | pumping rate varied more than 5 percent | acceptable if noted; the reviewer judges validity |
| `reach ...` WARN in `doctor --network` | firewall/proxy | run from another network or supply the files manually per `docs/DATA_SOURCES.md` |
| `GAM_MISMATCH` flag | stated T differs from the model by more than 25 percent | keep the site-test value if you have one and let the reviewer justify it; otherwise adopt the model value |
| pydantic "not fully defined" error after editing the schema | a type name used before its class is defined | keep new models above `class Intake` in `hydrostudy/schema/intake.py` |
