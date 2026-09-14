"""Turn a web intake form submission into a project `intake.yaml`.

The form emits JSON shaped like `intake.yaml` and nothing else. No YAML is written in the browser, so there is exactly
one serializer in the system and `hydrostudy.schema.intake.Intake` stays the only authority on what a valid intake is.

The payload is validated by constructing `Intake`, but the file written is the operator's pruned input rather than the
dumped model. That keeps the YAML close to what they typed (coordinates stay in the degrees-minutes-seconds form the
driller's sheet uses, and unset optional fields stay absent instead of appearing as nulls), which matters because the
file is meant to be read and edited afterwards. Validating and writing the same data is what makes that safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from hydrostudy.schema.intake import Intake

#: Keys the form adds for its own bookkeeping. Stripped before validation, kept for the file header.
FORM_META_KEY = "_form"

REVIEW_STUB = """# Filled in by the sealing P.G. or P.E. Until then the report shows highlighted placeholders.
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


def prune(value: Any) -> Any:
    """Drop what the form sends for an untouched optional field, and nothing else.

    Empty strings and nulls are removed so pydantic sees an absent field and applies its default, rather than being
    handed "" where it wants a float. `False` and `0` are real answers and always survive.
    """
    if isinstance(value, dict):
        out = {k: prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v is not None and v != "" and v != {} and v != []}
    if isinstance(value, list):
        items = [prune(v) for v in value]
        return [v for v in items if v is not None and v != "" and v != {} and v != []]
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def split_payload(payload: dict) -> tuple[dict, dict]:
    """Separate the intake fields from the form's own metadata."""
    data = dict(payload)
    meta = data.pop(FORM_META_KEY, None) or {}
    return prune(data), meta


def payload_to_intake(payload: dict) -> tuple[Intake, dict, dict]:
    """Validate a submission. Raises pydantic's ValidationError, which names the offending field."""
    data, meta = split_payload(payload)
    return Intake(**data), data, meta


def load_payload(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("submission payload must be a JSON object")
    return payload


def _header(meta: dict) -> str:
    bits = ["# Written by 'hydrostudy import-intake' from a web intake form submission."]
    for label, key in (("submission", "slug"), ("submitted", "submitted_at"), ("entered by", "entered_by")):
        if meta.get(key):
            bits.append(f"# {label}: {meta[key]}")
    bits.append("# Review it against the well design before running the report.")
    return "\n".join(bits) + "\n"


def write_intake(project_dir: str | Path, payload: dict, force: bool = False, scaffold: bool = True) -> Path:
    """Validate `payload` and write `<project_dir>/intake.yaml`, scaffolding the supporting files when absent."""
    d = Path(project_dir)
    target = d / "intake.yaml"
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass force to overwrite")

    _, data, meta = payload_to_intake(payload)   # validate before touching the filesystem

    d.mkdir(parents=True, exist_ok=True)
    target.write_text(_header(meta) + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
                      encoding="utf-8")
    if scaffold:
        (d / "data").mkdir(exist_ok=True)
        for path, text in ((d / "review.yaml", REVIEW_STUB),
                           (d / "data" / "manifest.yaml", MANIFEST_STUB),
                           (d / "data" / "district_wells.csv", WELLS_CSV_HEADER),
                           (d / "data" / "water_quality_samples.csv", WQ_CSV_HEADER)):
            if not path.exists():
                path.write_text(text, encoding="utf-8")
    return target
