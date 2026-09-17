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

1. Find the Montgomery County parcel layer URL: open the county's ArcGIS Hub open-data site (search "Montgomery County
   Texas open data" or "MCAD tax parcels" if the address has changed), open the tax-parcel dataset, and copy the
   FeatureServer layer URL from its API panel. It ends in `/FeatureServer/0`. Any county's parcel FeatureServer works
   the same way; only this URL changes between counties.
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
       --lat 30.170167 --lon -95.578097 --ground-elev-ft 166 --layers "Chicot,Evangeline,Burkeville,Jasper" \
       --model-name "Northern Gulf Coast GAM" --version v4.1 --out examples/black_oak_well_2/data/gam_lookup.json

   # MODFLOW-2000 (HAGM); supply the grid georeference if the name file lacks it
   .venv/bin/python scripts/build_gam_lookup.py --engine mf2k --model-dir /path/to/hagm --name-file hagm.nam \
       --epsg 32139 --xoff <x> --yoff <y> --angrot <deg> \
       --lat 30.170167 --lon -95.578097 --ground-elev-ft 166 --layers "Chicot,Evangeline,Burkeville,Jasper" \
       --model-name "Houston Area Groundwater Model" --version "v1.1" --out examples/black_oak_well_2/data/gam_lookup.json
   ```
   The HAGM grid is 137 rows by 245 columns of 1-mile cells; the model documentation states its projection and origin.
   `--ground-elev-ft` is the datum the layer depths are measured from (166 ft MSL is the Black Oak ground elevation);
   leave it off for a real project only if you want depths measured from the model's own land surface at that cell.
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

**Before the first real project, check that this repository is private.** Everything under `projects/<slug>` except
the `build/` output is tracked by git: the intake file, the District well export, and the water-quality samples. That
is deliberate, because the intake is the record of exactly which numbers went into a report a professional sealed, and
that record is worth keeping under version control. It also means a real project commits a customer's name, their
water system, the site address, the well coordinates and their water-quality results. Those belong in a private
repository.

If the repository has to stay public, add `projects/` to `.gitignore` before scaffolding anything, and keep the
project folders and their audit trail somewhere else. Do not leave it to be noticed later; by then the data is in the
history, and removing it means rewriting history.

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
5. Fill `intake.yaml` from the well design, either by hand as below or with the web intake sheet (section H), which
   validates as you type and writes the file for you. Field checklist (units in the file):
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

1. Build the reviewer's sheet and send it with the DOCX and the PDF:
   ```
   .venv/bin/hydrostudy review-sheet projects/<slug>     # -> build/review_sheet.html
   ```
   Ask Claude to publish it, then send the reviewer that link. The sheet is generated from the draft they are holding,
   so it shows each placeholder with the guideline item it answers and the draft wording it replaces, the parameters a
   decision would override, what the pipeline flagged, and the simulated drawdowns. It collects everything
   `review.yaml` holds: identity and licence, `decisions` (T, S, evaluation radius, thresholds) and the eight
   `opinions`. A reviewer who would rather edit YAML still can; the sheet is an alternative, not a gate.
2. **The sheet checks their figures as they type.** The report rejects any number it cannot trace to its own
   calculations, so an opinion citing an invented figure fails the build. The sheet carries that draft's allowed
   numbers and names any figure that is not among them, while the reviewer is still at the keyboard. If they set a
   parameter override the sheet says so too, because the drawdowns it shows were computed before that override and
   must be re-checked against the rebuilt report.
3. Import what they send back and re-run:
   ```
   .venv/bin/hydrostudy import-review projects/<slug> <submission>.json
   .venv/bin/hydrostudy run projects/<slug>
   ```
   For the sealed version set `reviewer.status: final` and bump `report.revision.number`; the banner disappears and the
   review-log appendix is dropped. Final files are never overwritten.
4. Confirm the spacing multiplier. Until someone reads it out of the District Rules, the report asks the reviewer to
   confirm it rather than stating that the well complies. See section G.
5. Settle the issuing-entity question before the first submittal: a sealed geoscience report is generally issued by a
   TBPG-registered firm. `report.issuing_firm` switches the letterhead between Ballard and the reviewer's firm.
6. After drilling, copy the project, set `mode: lsgcd_post_drilling`, fill `as_built` (construction, static level,
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
| `LINT FAILURE ... number` naming a figure from an opinion | the reviewer cited a number the report does not compute, or quoted a figure from before their own parameter override | take the figure from the tables in the review sheet, write it in words, or rebuild first and re-check; the review sheet warns about both before submission |
| review sheet says "no draft to review" | the project has not been built yet | run `hydrostudy run <project>` first; the sheet is generated from the draft |
| `SPACING_RULE_UNVERIFIED` flag | the spacing multiplier was never read from the District Rules | expected today; see section G to clear it permanently |
| `DISTRICT_RULES_STALE` flag | the rule file has not been re-verified inside its re-check window | re-read the District Rules and update `verified_on`, per section G |
| `GAM_MISMATCH` flag | stated T differs from the model by more than 25 percent | keep the site-test value if you have one and let the reviewer justify it; otherwise adopt the model value |
| pydantic "not fully defined" error after editing the schema | a type name used before its class is defined | keep new models above `class Intake` in `hydrostudy/schema/intake.py` |

## G. District rules: what is verified and what is not

The spacing multipliers in `hydrostudy/districts/lsgcd.yaml` were read back out of hydrogeological reports the District
accepted in 2023. Nobody on this project has read Rule 3.3. Samuel, who drills and permits in this district, confirms
the rule is unchanged, and that is what the rule file now records.

Each district file declares where its numbers came from, in three tiers:

| `source` | What it means | How the report states a spacing distance |
|---|---|---|
| `primary` | read from a document the District published | as the District's requirement |
| `operator_attested` | confirmed current by a named person with standing in the district, on a date | as the District's requirement, with the attestation named in the provenance note |
| `derived` or `unknown` | reconstructed from something else, or unknown | as the distance applied, with the reviewer asked to confirm the multiplier |

Supporting fields:

| Field | Meaning |
|---|---|
| `rules.verified_on` | when someone last checked the rule file against its source |
| `spacing.verified_on` | same, for the spacing multipliers alone; overrides the above for that scope |
| `spacing.attested_by` / `attested_on` | who attested and when, required for `operator_attested` |
| `rules.recheck_after_days` | how long any of that stays good (default 180) |

Two things follow. **Every tier expires.** An attestation and a reading of the guidelines age on separate clocks, and
when the spacing scope ages past the window the qualifier comes back on its own, along with a flag saying it expired
rather than that the source is missing. **The arithmetic never changes.** Only the strength of the claim does, and a
conflicting well inside the radius is a conflict under every tier.

### Recording an attestation

Use it when someone who actually works in the district confirms a rule, and name them. `attested_by` should be a person
and their role, not a company alone, because the sealing professional may need to ask them. Never record an attestation
from a summary, a search result, or a recollection you cannot attribute.

### Promoting to primary

1. Get the current District Rules from LSGCD and read the well spacing rule.
2. If the multipliers still match, set `spacing.source: primary`, set `spacing.verified_on` to today, and put the rule
   number and adoption date in `rules.version`. Drop `attested_by` and `attested_on`, which no longer carry the claim.
   If they do not match, correct the `ft_per_gpm` values first and tell Samuel, because reports already issued used the
   old numbers.
3. Run `.venv/bin/pytest`. Tests assert the attestation appears in the report's provenance note, so they will fail once
   the source is primary. That failure is the reminder to update the expected wording, not a defect.
4. Re-run the affected projects. The provenance sentence and the informational flag disappear.

Do the same for any new district. A district whose spacing rule nobody has read and nobody can attest to should stay
`derived`, so every report it produces carries the qualifier.

## H. The web intake sheet

`web/intake_form.html` is published as an Artifact: a form covering everything in `intake.yaml` for a pre-drilling or
feasibility project, so the well design can be entered by whoever has the driller's sheet in front of them rather than
edited as YAML. Ask Claude for the link, or find it in your artifact gallery.

It checks as you type: required fields, west longitudes entered positive, interval tops and bottoms the wrong way
round, casing reaching past the first screen, cement below the cased interval, anything deeper than total depth,
duplicate well ids, a well completed in an aquifer that was never defined. It also draws the well as entered beside
the construction section, which catches geometry mistakes faster than reading the numbers back. None of that replaces
the generator: `Intake` in `hydrostudy/schema/intake.py` validates every submission again on import and has the final
say.

Two ways to get a submission into a project:

```
# 1. Send to Claude  -> stored in the artifact's database; ask Claude to import it, which runs:
.venv/bin/hydrostudy import-intake projects/<slug> <submission>.json

# 2. Save file       -> the JSON lands in your downloads; pass it to the same command
.venv/bin/hydrostudy import-intake projects/<slug> ~/Downloads/<slug>.intake.json
```

`import-intake` validates the submission, writes `intake.yaml` with a header recording which submission it came from,
and scaffolds `review.yaml`, `data/manifest.yaml` and the two CSV headers if they are absent. It refuses to overwrite
an existing `intake.yaml` without `--force`. Data files and manifest sources are still yours to supply; the form
collects the well design, not the District export or the water-quality records.

"Load Black Oak example" fills the sheet with the published figures from the 2023 Black Oak submittal so a new user can
see a completed sheet. It is training material, not a well: a banner says so, the submission is stamped as example
data, and the sheet must be cleared before real entry.

To change what the form collects, edit the `field-spec` JSON block inside `web/intake_form.html`. The page renders from
that block and `tests/test_intake_form.py` reads the same block, so a required field added to the schema without a
control fails the test rather than failing silently on the next submission. Post-drilling `as_built` capture is
deliberately excluded: it is LAS logs and test CSVs, which belong with the file drop.

## I. Siting a well: where it can go and what it can make

`hydrostudy siting` answers a different question from the rest of the tool. A report asks "does this location
comply?" The siting search asks "where on this tract may the well go, and how much can it produce there?" Run it
before the design is fixed, when the answer can still change where the rig sets up.

```
.venv/bin/hydrostudy siting projects/<slug>                       # the well's own rate, 100-ft grid
.venv/bin/hydrostudy siting projects/<slug> --rate 700 --grid-ft 50
.venv/bin/hydrostudy siting projects/<slug> --setback-ft 50 --available-drawdown-ft 250 --top 3
```

It needs two things beyond a valid intake:

- **The tract**, as `site.boundary_geojson` in `intake.yaml` or a `boundary` entry in `data/manifest.yaml`. Without a
  polygon there is no area to search and the command says so rather than guessing one.
- **`data/district_wells.csv`**, because the spacing limit at any point is set by the nearest well in that file.

### What it computes

| Limit | How it inverts into a rate |
|---|---|
| Spacing | Closed-form. The required distance is `ft_per_gpm x gpm`, so the largest rate a point allows is the distance to the nearest counting well divided by the multiplier |
| `--max-interference-ft` | Solved. A drawdown budget at a neighbouring well |
| `--available-drawdown-ft` | Solved. The same budget applied at the proposed well's own radius: static level to pump intake is a rate limit like any other |

The rate reported at a point is the smallest of whichever limits you asked for, and `binding_constraint` names which
one bound it.

The two drawdown limits are solved rather than divided out, and the reason matters if you ever check the arithmetic
by hand. Theis drawdown is linear in Q at a fixed duration, so a budget looks like it should divide straight into a
rate. But these scenarios run for the time the permitted annual volume takes to produce, `volume / (rate x 1440)`, so
a lower rate pumps for longer and draws the level down further. Invert the budget at the duration the *target* rate
implies and the rate that comes back is too high, by around 6% on the Black Oak example. So the rate and the duration
are solved together, iterating down from the spacing limit until the rate stops moving. Every drawdown in the output
is therefore reported twice: `_at_target_ft` at the target rate over the target's duration, and `_at_max_rate_ft` at
the rate the location supports over the longer duration that rate implies, with `days_at_max_rate` alongside it. "Counting well" means the same test the compliance analysis applies
(`analysis/spacing.py::counts_against_spacing`): not the applicant's own well, and not plugged or void. Both call the
same function on purpose, so a location this search ranks is a location `hydrostudy run` reports as compliant.
`tests/test_siting.py` proves that end to end by moving the well to the top-ranked point and re-running the project.

### Reading the output

`build/siting.json` and `build/figures/fig_siting_<well>.png`. Locations are ranked by the drawdown they put on
somebody else's well, least first, and are forced at least `--min-separation-ft` apart so the list is options rather
than one spot quoted five times. Each drawdown is quoted twice, at the target rate and at the rate the location can
actually support, and the share coming from the existing system wells is called out separately: on a system with a
well already pumping, most of the impact at a neighbour is usually already there before the new well starts.

Three cautions the command prints and you should not skip:

1. **Spacing headroom is only as good as the well database.** The search reports how far your export reaches. A rate
   it allows at a point assumes no unrecorded well nearer than the nearest one in that file.
2. **The envelope is only as firm as the multiplier.** When the district's spacing source is not authoritative
   (section G), the whole envelope is reported as provisional: it is the area that complies with the multiplier
   applied, not a statement of District compliance.
3. **No location on the tract may support the rate.** That is an answer, not a failure. The command then reports the
   best point, what it tops out at, and which limit bound it. Fewer wells at higher rates is not always available;
   the alternative is usually more wells at lower rates, further apart, which is a design change and not a siting one.

A well outside any spacing conflict can still be a bad well. The search knows about distance, rate and drawdown. It
knows nothing about access, power, the septic field, the pipeline easement, the flood plain or where the customer will
let you park a rig. Treat the ranking as the shortlist to walk, not the answer.

## J. Beyond Theis: leaky aquifers and hydraulic boundaries

Theis assumes a confining unit that passes no water and an aquifer that never ends. Both assumptions are
conservative, both are sometimes wrong, and a reviewing geoscientist on a larger municipal system will
ask about them. Two opt-in solutions are available. **Both default to off.** A project that says nothing
gets Theis with no boundaries, which is what the District's guidelines contemplate and what every
example in this repository still uses.

### Leaky (semi-confined) aquifers

Where the confining clay leaks, part of the withdrawal comes across it rather than out of storage, so
drawdown flattens towards a steady cone instead of deepening with the logarithm of time. Theis
overstates it.

```yaml
analysis:
  solution: hantush          # default: theis
aquifers:
  - name: Evangeline
    confinement:
      status: semi-confined
      confining_unit: Burkeville
      thickness_ft: 100          # b'
      k_prime_ftd: 0.01          # K'  -> leakance = K'/b' = 1e-4 per day
      # or state the leakance directly:
      # leakance_per_day: 1.0e-4
      leakance_source: "Aquifer test at Well No. 1, 2023; K' fitted with Hantush-Jacob"
```

**The leakance is never defaulted, estimated or inferred.** It is a property of one specific clay at one
specific site, every reported drawdown depends on it, and a plausible-looking guess is exactly the kind
of number that survives review and should not. If `solution: hantush` is set without a leakance, the
pipeline uses Theis, says so in the methodology section, and raises `LEAKANCE_MISSING`. If a leakance is
given with no `leakance_source`, it raises `LEAKANCE_UNCITED` and the report states plainly that the
source was not given.

Choosing the leaky solution changes the methodology section, its equations, its assumption list and its
citations, not just the numbers. It is also the *less* conservative choice at late time, and the report
says so: the Hantush-Jacob assumptions require that the bed feeding the confining unit does not itself
draw down and that the clay releases none of its own water. Where either fails, real drawdown exceeds
what this reports.

### Hydraulic boundaries

A barrier (the sand pinches out, a fault throws it out of contact) deepens the cone against it. A
recharge boundary (a fully penetrating river or lake in good hydraulic contact) holds the head fixed and
shallows it. Each is represented by an image well reflected across the line, which is the exact
analytical solution for one straight boundary.

```yaml
analysis:
  boundaries:
    - kind: barrier            # or: recharge
      name: Conroe fault
      aquifer: Evangeline      # omit to apply it to every aquifer, which is rarely what you mean
      lat1: 30.1735            # two points anywhere on the line
      lon1: -95.5725
      lat2: 30.1760
      lon2: -95.5700
      source: "Interpreted from the 2023 seismic section; confirm with District staff"
```

Four things to know before using one:

1. **It is an interpretation, so it carries a `source`.** It changes every reported drawdown, and a
   reviewer has to be able to challenge it. The narrative names the source.
2. **A receptor beyond a boundary gets no drawdown estimate at all.** The image solution represents the
   aquifer on the pumping side only. Past a recharge boundary the arithmetic returns negative drawdown;
   past a barrier it returns drawdown that *grows* with distance. Those wells are reported as "beyond
   boundary" with a footnote, not as a number. Cone-of-depression distances are cut off at the boundary
   for the same reason, and the count of truncated directions is recorded.
3. **One boundary is exact; two or more are truncated.** Images reflect between multiple boundaries
   indefinitely. The series stops at `analysis.image_max_order` (default 6) and the report says it was
   truncated. The residual grows as boundaries get closer and more nearly parallel.
4. **`hydrostudy siting` refuses to run.** Each candidate location would carry its own image wells, and
   points beyond a boundary have no drawdown, so an envelope computed without them would disagree with
   the report. Comment the boundaries out to explore siting, then restore them.

### What to check in the output

- `build/analysis.json` -> `solutions` names the solution per aquifer, its leakance and leakage factor,
  and whether it `fell_back` to Theis.
- The interference table gains a column for the boundary's contribution, so the printed row still adds
  to the printed total. Image wells appear in `image_wells` and in no table of wells.
- Flags to read before sealing: `LEAKANCE_MISSING`, `LEAKANCE_UNCITED`, `LEAKY_BUT_CONFINED` (a leaky
  solution on an aquifer the intake calls confined), `LEAKAGE_REACH` (leakage too distant to matter, or
  so close the result is insensitive to duration) and `HYDRAULIC_BOUNDARIES` (the truncation note).
