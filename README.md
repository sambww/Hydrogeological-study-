# hydrostudy

Generates a complete draft hydrogeological report for Texas groundwater-district permit applications (Lone Star GCD
pre-drilling and post-drilling report formats; feasibility-study variant) from a YAML intake and local public-data extracts. A licensed
Texas P.G. or P.E. reviews, completes the highlighted opinion placeholders and seals the document.

What it produces (per project, in `build/`):
- `report_v{n}_{status}.docx` and a PDF review copy (requires LibreOffice Writer): letter-style report in the District guideline order with
  numbered figures and tables, references, guideline cross-reference, data provenance and a Theis benchmark appendix.
- `figures/`: location, wells and surface water, property/spacing radius, well construction schematic, hydrogeologic
  column, water-quality maps, drawdown contour maps (proposed well alone and whole system), distance-drawdown curves.
- `analysis.json`, `nearby_wells.json`, `water_quality.json`, `hydrography.json`, `checklist.json`, `provenance.json`.

Quick start:
```
python -m venv .venv && .venv/bin/pip install -e .[dev]
.venv/bin/hydrostudy doctor --network               # environment and data-host checks
.venv/bin/hydrostudy new projects/my_well          # scaffold from the example
# or fill the web intake sheet (web/intake_form.html, published as an Artifact) and import its submission:
.venv/bin/hydrostudy import-intake projects/my_well submission.json
# edit projects/my_well/intake.yaml, review.yaml and data/*.csv (see docs/WORKFLOW.md and docs/DATA_SOURCES.md)
.venv/bin/hydrostudy validate projects/my_well
.venv/bin/hydrostudy siting projects/my_well       # where the well can go and what it can make there
.venv/bin/hydrostudy run projects/my_well
```

`siting` is the design side of the same engine: give it the tract and a target rate and it maps every location that
satisfies the District's spacing rule, ranks them by the drawdown they put on neighbouring wells, and reports the
maximum rate each one supports and which limit bound it. It answers "where can this well go?" before the report has
to answer "does this location comply?" (`docs/RUNBOOK.md` section I).

See `docs/RUNBOOK.md` (set up your machine, validate the connectors and GAM script, run a real project), `docs/WORKFLOW.md` (step by step), `docs/DATA_SOURCES.md` (where each input comes from and the expected columns),
and `docs/LSGCD_REQUIREMENTS_MATRIX.md` (guideline item -> report section -> code).

Verification: the analytical engine reproduces a District-accepted 2023 submittal to 0.1 ft (`tests/test_theis.py`).
