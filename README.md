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

`wellfield` goes one step further: give it a demand in gpm and it designs the field, deciding how many
wells, where, and at what rate each, subject to spacing, the drawdown the pumps can lift and a cap on the
impact at a neighbour's well. The rate split is a linear program, so when a limit binds it binds exactly;
the placement is a search, so the answer is a good field rather than a proven optimum, and it says so
(`docs/RUNBOOK.md` section K).

`uncertainty` answers the question a reviewer asks next: how sure is that number? Declare how well T and
S are known, with a source, and it propagates the spread into every drawdown the report quotes, reporting
the probability that drawdown at a given well exceeds a given figure. It will not run on a guessed spread
(`docs/RUNBOOK.md` section L).

Beyond Theis, two solutions are available and both default to off: the Hantush-Jacob leaky-aquifer
solution for a confining unit that passes water, and barrier or recharge boundaries by the method of
images. Each changes the methodology section, its equations and its citations as well as the numbers,
and neither will run on an uncited leakance. `docs/RUNBOOK.md` section J.

See `docs/RUNBOOK.md` (set up your machine, validate the connectors and GAM script, run a real project), `docs/WORKFLOW.md` (step by step), `docs/DATA_SOURCES.md` (where each input comes from and the expected columns),
and `docs/LSGCD_REQUIREMENTS_MATRIX.md` (guideline item -> report section -> code).

Verification: the analytical engine reproduces a District-accepted 2023 submittal to 0.1 ft (`tests/test_theis.py`).
