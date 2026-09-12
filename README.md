# hydrostudy

Generates a complete draft hydrogeological report for Texas groundwater-district permit applications (Lone Star GCD
pre-drilling report format; feasibility-study variant) from a YAML intake and local public-data extracts. A licensed
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
.venv/bin/hydrostudy new projects/my_well          # scaffold from the example
# edit projects/my_well/intake.yaml, review.yaml and data/*.csv (see docs/WORKFLOW.md and docs/DATA_SOURCES.md)
.venv/bin/hydrostudy validate projects/my_well
.venv/bin/hydrostudy run projects/my_well
```

See `docs/WORKFLOW.md` (step by step), `docs/DATA_SOURCES.md` (where each input comes from and the expected columns),
and `docs/LSGCD_REQUIREMENTS_MATRIX.md` (guideline item -> report section -> code).

Verification: the analytical engine reproduces a District-accepted 2023 submittal to 0.1 ft (`tests/test_theis.py`).
