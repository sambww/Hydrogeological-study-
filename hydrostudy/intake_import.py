"""Turn a web intake sheet submission into a project `intake.yaml`.

The sheet emits JSON shaped like `intake.yaml` and nothing else. No YAML is written in the browser, so there is
exactly one serializer in the system and `hydrostudy.schema.intake.Intake` stays the only authority on what a valid
intake is. The shared pruning, metadata and write plumbing lives in `hydrostudy.submission`.
"""

from __future__ import annotations

from pathlib import Path

from hydrostudy.schema.intake import Intake
from hydrostudy.submission import (
    FORM_META_KEY,
    load_payload,
    prune,
    split_payload,
    write_submission,
)

__all__ = ["FORM_META_KEY", "load_payload", "payload_to_intake", "prune", "split_payload", "write_intake"]

REVIEW_STUB = """# Filled in by the sealing P.G. or P.E. Until then the report shows highlighted placeholders.
# 'hydrostudy review-sheet <project>' builds a sheet they can fill instead of editing this by hand.
reviewer:
  name: null
  license_type: null
  license_no: null
  firm: null
  firm_registration_no: null
  status: draft
decisions: {}
opinions:
  conclusion: null
  lithology_basis: null
  recharge_features: null
  confinement: null
  water_quality: null
  aquifer_identification: null
  parameter_selection: null
  spacing: null
notes: []
"""

MANIFEST_STUB = """# Where every data file came from and when. This becomes Appendix B of the report.
files:
  district_wells:
    path: district_wells.csv
    source: null          # e.g. "LSGCD registered and permitted well database export"
    retrieved: null       # e.g. "2026-09"
    crs: EPSG:4326
  water_quality:
    path: water_quality_samples.csv
    source: null
    retrieved: null
hydrography_notes: []     # one entry per stream/pond within the search radius, or leave empty and supply streams.geojson
springs:
  searched: false
  source: null
  found: []
"""

WELLS_CSV_HEADER = ("registration_no,permit_no,owner,address,city,total_depth_ft,screen_intervals,aquifer,status,"
                    "lat,lon\n")
WQ_CSV_HEADER = ("well_id,well_name,source,sample_date,lat,lon,depth_ft,aquifer,constituent,value,units,"
                 "qualifier\n")


def payload_to_intake(payload: dict) -> tuple[Intake, dict, dict]:
    """Validate a submission. Raises pydantic's ValidationError, which names the offending field."""
    data, meta = split_payload(payload)
    return Intake(**data), data, meta


def write_intake(project_dir: str | Path, payload: dict, force: bool = False, scaffold: bool = True) -> Path:
    """Validate `payload` and write `<project_dir>/intake.yaml`, scaffolding the supporting files when absent."""
    d = Path(project_dir)
    target, _, _ = write_submission(
        d / "intake.yaml", payload, Intake,
        command="hydrostudy import-intake",
        closing="Review it against the well design before running the report.",
        force=force,
    )
    if scaffold:
        (d / "data").mkdir(exist_ok=True)
        for path, text in ((d / "review.yaml", REVIEW_STUB),
                           (d / "data" / "manifest.yaml", MANIFEST_STUB),
                           (d / "data" / "district_wells.csv", WELLS_CSV_HEADER),
                           (d / "data" / "water_quality_samples.csv", WQ_CSV_HEADER)):
            if not path.exists():
                path.write_text(text, encoding="utf-8")
    return target
