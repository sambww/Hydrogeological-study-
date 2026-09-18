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
- Alternative solutions are opt-in and resolved in ONE place: `analysis/solution.py::resolve_solution`,
  once per aquifer, returning an object whose `drawdown` has the same signature as `theis_drawdown` so it
  can be injected (`superposed_drawdown`, `drawdown_at_well`, `radius_at_drawdown`, `drawdown_grid` all
  take `fn=`). Defaults: `analysis.solution: theis`, no boundaries - so every existing number is
  unchanged. `analysis/leaky.py` is Hantush-Jacob; `analysis/boundaries.py` is barrier/recharge image
  wells; `analysis/schedule.py` is variable rates (tested, not yet on the report path).
  Rules that must not be broken: (1) a leakance is NEVER defaulted or estimated - without a cited one the
  pipeline falls back to Theis and flags it; (2) whatever ran must be what the report says ran, so the
  methodology narrative, its equations and the figures are all conditional on the resolved solution;
  (3) a receptor beyond a boundary gets NO drawdown, because past a recharge boundary the superposition
  is negative and past a barrier it grows with distance; (4) image wells never appear in a table of
  wells - their share of the drawdown is reported as `boundary_effect_ft` so interference rows still add
  up. See `docs/RUNBOOK.md` section J.
- `hydrostudy siting <project>` (`analysis/siting.py`, `figures/siting_map.py`) answers where on the tract the well may
  go and what it can produce there, and writes `build/siting.json`. It is a design tool, not a report section: it does
  not touch the report. Its spacing test is `analysis/spacing.py::counts_against_spacing`, the same predicate the
  compliance analysis uses - never inline that test in one of them, or the envelope one draws stops being the envelope
  the other accepts. The spacing limit is closed-form (distance / multiplier); the drawdown limits are NOT, because
  max-production duration is `volume / (rate x 1440)`, so a lower rate pumps for longer - rate and duration are solved
  together, iterating down from the spacing limit. Never invert a drawdown budget at the target rate's duration.
  See `docs/RUNBOOK.md` section I.
- `hydrostudy wellfield <project> --rate N` (`analysis/wellfield.py`, `figures/wellfield_map.py`) designs a
  field for a demand: how many wells, where, at what rate each, writing `build/wellfield.json`. Also a
  design tool that does not touch the report. For fixed positions the rate split is an LP (scipy linprog)
  because every constraint is linear in the rates - never replace that with a heuristic. Positions are
  greedy + coordinate descent on `siting.candidate_grid`, so the field is good, not provably optimal, and
  the output must keep saying so. The search evaluates layouts at a common duration (`_evaluate(fast=True)`)
  and re-solves the winner exactly; that is 20,000 LPs down to a few hundred. Costs are only ever the
  operator's own inputs. Shares `candidate_grid`, `production_days` and `fixed_system_wells` with
  `siting.py` - keep them shared so both search the same points. See `docs/RUNBOOK.md` section K.
- Any "largest rate this distance allows" goes through `spacing.max_rate_for_distance`, never
  `distance / multiplier`: `spacing_analysis` counts `distance <= required` as a CONFLICT, so a cap
  computed to the last float does not comply, and a designed location round-trips through lat/lon before
  the pipeline re-measures it. `SPACING_ROUNDTRIP_FT` covers that; the operator's `--spacing-safety-ft`
  is a separate margin on top for the accuracy of the District's coordinates.
- `hydrostudy uncertainty <project>` (`analysis/uncertainty.py`, `figures/uncertainty_plot.py`) propagates
  declared parameter spreads by Monte Carlo into `build/uncertainty.json`; a third design tool that does
  not touch the report. Rules: (1) a spread is NEVER defaulted - without an `uncertainty` block carrying a
  `source` it refuses, because this analysis is about how much to trust the other numbers and a guessed
  interval is worse than none; (2) draws and seed are inputs and are recorded, so an interval is
  reproducible; (3) every quantile is reported with its standard error; (4) it reports where the
  deterministic value falls as a percentile, so nobody mistakes the median for a correction to a sealed
  number. `theis_drawdown` and `leaky_drawdown` accept ARRAYS for T and S so all draws evaluate in one
  call - keep those guards array-aware (`np.any`).
  The command does not touch the report. The REPORT path is separate and opt-in:
  `analysis.uncertainty_appendix` in the intake makes `pipeline.run_uncertainty` propagate during the
  build and both assemblers add Appendix D (`report/assemble.py::append_uncertainty_appendix`, shared
  so the two formats cannot drift). Rules there: (1) no declared spread, or a post-drilling report with
  no interference section, means NO appendix plus a review flag - never a guessed spread and never a
  silently missing section the operator asked for; (2) appendix figures and tables are lettered (D-1,
  D-2) and the figure is deliberately absent from `context.assign_numbers`' order, so adding the
  appendix renumbers nothing in a report already reviewed without it; (3) the section the appendix
  qualifies comes from `context.INTERFERENCE_SECTION`, never typed into the template, because the
  pre- and post-drilling formats number it 6 and 5; (4) a probability is NEVER printed as 100% or 0%
  (`context._uncertainty_context::probability`) - no finite simulation establishes a certainty, and in
  a filed document that is a claim the method cannot support. See `docs/RUNBOOK.md` section L.
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
