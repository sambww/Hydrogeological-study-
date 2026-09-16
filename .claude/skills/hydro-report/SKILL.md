---
name: hydro-report
description: Walk a Ballard Water Well project from well proposal to a draft hydrogeological report (LSGCD pre-drilling format or feasibility study) using the hydrostudy pipeline in this repo. Use when the user wants to start, update or review a hydro report / hydrogeological study for a new well or well system.
---

# /hydro-report

You are helping a water-well contractor produce a DRAFT hydrogeological report that a Texas P.G./P.E. will seal.

## Guardrails
- You may create or edit only `projects/<slug>/intake.yaml`, `projects/<slug>/review.yaml` and files under
  `projects/<slug>/data/`. Never edit narrative templates or build outputs to change a number.
- Never invent wells, coordinates, depths, sample results, aquifer parameters or references. If an input is missing,
  ask for it or leave it null so the pipeline flags it.
- Do not write conclusions or opinions; those belong to the reviewer in `review.yaml`.
- A real project's intake and data files are committed, and they hold customer and site data. Confirm the
  repository is private before scaffolding one (`docs/RUNBOOK.md` section D).
- Do not change a district file's spacing `source`. `primary` requires the rules document itself;
  `operator_attested` requires a named person with standing in that district and the date they confirmed it. Anything
  else stays `derived`, and the report then asks the reviewer to confirm the distance instead of claiming compliance.

## Steps
0. If this is a new machine or something fails to import, run `hydrostudy doctor --network` and follow `docs/RUNBOOK.md`.
1. **Intake interview** (ask only for what is missing; the user is an experienced driller):
   applicant / PWS name and ID / county and district; each proposed well (coordinates, elevation, aquifer, max gpm,
   total depth, borehole-casing-screen-cement-filter pack intervals, packer, static water level, anticipated
   lithology, distance to nearest property line); existing system wells (registration/permit no., coordinates,
   aquifer, gpm, depth, screen); annual permit volume; aquifer top/bottom and T/S/K with their source.
2. Scaffold with `hydrostudy new projects/<slug>` and write the answers into `intake.yaml`.
3. Ask the user to place the District well export and TCEQ/TWDB water-quality export in `data/` following
   `docs/DATA_SOURCES.md`; fill `data/manifest.yaml` (sources, dates, hydrography notes, springs search).
4. `hydrostudy validate projects/<slug>` and fix schema errors with the user.
4a. If the location is not yet fixed, or the user asks where the well should go or how much a tract can support, run
   `hydrostudy siting projects/<slug>` (needs the tract polygon). Report the compliant acreage, the ranked locations
   with the rate each supports and what bound it, and the three cautions the command prints. Do not present the
   ranking as the decision: it knows distance, rate and drawdown, not access, power, easements or the septic field.
5. `hydrostudy run projects/<slug>`. Report back: drawdown results per scenario, spacing result, checklist counts,
   the list of `[P.G. TO PROVIDE]` placeholders and the flags. Open `build/figures/*.png` and sanity-check them.
6. Iterate on inputs until only reviewer items remain. Hand the DOCX/PDF to the sealing professional with the
   placeholder list. When they return `review.yaml`, re-run; for the sealed version set `reviewer.status: final`
   and bump `report.revision.number`.

## Post-drilling submittal
When the well has been drilled and tested, copy the project, set `mode: lsgcd_post_drilling`, and fill the `as_built:`
block (as-built construction, static level and date, pump, log inventory with LAS files, aquifer-test CSVs, field
parameters) following `examples/black_oak_well_2_post/intake.yaml` and `docs/WORKFLOW.md`. Never fabricate test data;
if a series is missing, leave the test out so the checklist flags it.

## Useful checks
- Spacing radius = multiplier x gpm (LSGCD: Chicot/Evangeline 2.0, Jasper 1.5, Catahoula 1.0 ft/gpm; verify).
- The rate spacing allows at a point = distance to the nearest counting well / multiplier. A plugged well and the
  applicant's own wells do not count.
- Max-production days = annual volume / (rate x 1440).
- Pumped-well drawdown depends on `r_w_ft`; state it and keep it consistent across the system wells.
