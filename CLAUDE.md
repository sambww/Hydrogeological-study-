# hydrostudy - draft hydrogeological report generator

Purpose: turn a filled `intake.yaml` plus local public-data extracts into a complete DRAFT hydrogeological report in the
order of the Lone Star GCD Hydrogeological Report Guidelines (11-11-2022), ready for review and sealing by a Texas P.G. or P.E.

## Run
```
python -m venv .venv && .venv/bin/pip install -e .[dev]
.venv/bin/hydrostudy validate examples/black_oak_well_2
.venv/bin/hydrostudy run examples/black_oak_well_2        # -> build/report_v1_draft.docx (+ .pdf when libreoffice-writer is installed)
.venv/bin/pytest
.venv/bin/hydrostudy doctor --network                     # environment + data-host reachability
```
Use the `/hydro-report` skill (`.claude/skills/hydro-report/SKILL.md`) to walk a new project from intake to report.

## Conventions (do not break)
- Numbers never get typed into narrative templates or code that writes prose. Every number in the report comes from
  `build/analysis.json` and friends through `hydrostudy/report/context.py`; `report/lint.py` fails the build otherwise.
- Units: rates in gpm at the API boundary, T in ft2/day, K in ft/day, distances in feet, time in days. All conversions in `units.py`.
- Coordinates: WGS84/NAD83 lat/lon in intake; all geometry in a local azimuthal-equidistant CRS in US feet (`geo/crs.py`).
- Theis superposition per aquifer (`analysis/theis.py`, `analysis/scenarios.py`); wells in other aquifers get "not applicable".
- Pumped-well drawdown is evaluated at `r_w_ft` (default: borehole radius across the screen). Consultants have used 0.5 and 1.0 ft.
- Opinions and conclusions live in `review.yaml`; when null the report shows highlighted `[P.G. TO PROVIDE: ...]` placeholders.
  `hydrostudy review-sheet <project>` generates `build/review_sheet.html` from that project's build for the reviewer to
  fill, and `hydrostudy import-review` writes their submission back (`review_sheet.py`, `review_import.py`).
- Reviewer prose is untrusted input to the numbers lint: `report/lint.py` excludes `opinions` and `reviewer` from the
  allowed set (`UNTRUSTED_CONTEXT_KEYS`), so a hand-typed figure in an opinion cannot whitelist itself. Never add those
  keys back, and never widen the allowed set to make a reviewer's paragraph build.
- District rules live in `hydrostudy/districts/*.yaml` with a `source` in three tiers: `primary` (read from a
  District-published document), `operator_attested` (confirmed current by a named person, with `attested_by` and
  `attested_on`) and `derived`/`unknown` (reconstructed). The first two let the narrative state a spacing distance as
  the District's rule and put the basis in the provenance note; the third makes it state the distance applied and ask
  the reviewer to confirm. Every tier expires after `recheck_after_days`, on a per-scope date
  (`districts/status.py`). Re-verify before each submittal; see `docs/RUNBOOK.md` section G.
- `hydrostudy siting <project>` (`analysis/siting.py`, `figures/siting_map.py`) answers where on the tract the well may
  go and what it can produce there, and writes `build/siting.json`. It is a design tool, not a report section: it does
  not touch the report. Its spacing test is `analysis/spacing.py::counts_against_spacing`, the same predicate the
  compliance analysis uses - never inline that test in one of them, or the envelope one draws stops being the envelope
  the other accepts. The spacing limit is closed-form (distance / multiplier); the drawdown limits are NOT, because
  max-production duration is `volume / (rate x 1440)`, so a lower rate pumps for longer - rate and duration are solved
  together, iterating down from the spacing limit. Never invert a drawdown budget at the target rate's duration.
  See `docs/RUNBOOK.md` section I.
- Never overwrite a final report: bump `report.revision.number`.
- Everything under `projects/<slug>` except `build/` is tracked on purpose: the intake is the record of what
  went into a sealed report. It therefore carries customer names, addresses, well coordinates and water-quality
  results, so this repository must stay private. See `docs/RUNBOOK.md` section D before scaffolding a real project.
- The three pre-drilling `examples/` are transcriptions of public submittals and are the regression baseline (`tests/`);
  `examples/black_oak_well_2_post` uses SYNTHETIC test data (see its manifest) to exercise the post-drilling mode.
- Post-drilling mode (`lsgcd_post_drilling`): `analysis/asbuilt.py`, `analysis/pumptest.py`, `report/assemble_post.py`.
- Web sheets share their plumbing in `hydrostudy/submission.py` (pruning, form metadata, header, overwrite guard);
  both importers validate by constructing the schema model and write the submitter's own input, never a dumped model.
- The web intake sheet (`web/intake_form.html`, published as an Artifact) renders from its own `field-spec` JSON block;
  `tests/test_intake_form.py` reads that block and fails if a required schema field has no control. Submissions are
  JSON in the shape of intake.yaml and become a project via `hydrostudy import-intake` (`intake_import.py`), which is
  the only YAML serializer - never add a second one in the page.
- A SessionStart hook (`.claude/settings.json` -> `scripts/session_start.sh`) creates `.venv` and installs the package.
- No network access is required to run. Live data connectors (Phase 2) are documented in `docs/DATA_SOURCES.md`.
