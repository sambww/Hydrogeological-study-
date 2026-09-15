"""Shared plumbing for the web sheets that feed this pipeline.

The intake sheet and the review sheet both submit JSON shaped like the YAML file they stand in for. Pruning, the form's
own metadata, the file header and the refuse-to-overwrite guard are identical for both; only the schema model differs.
They live here once so there is no second copy to drift.

The file written is the submitter's pruned input, not a dumped model: it keeps coordinates in the form the driller's
sheet used, leaves untouched optional fields absent instead of null, and keeps a reviewer's prose exactly as typed.
Validating and writing the same data is what makes that safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

#: Key the sheets add for their own bookkeeping. Stripped before validation, kept for the file header.
FORM_META_KEY = "_form"


def prune(value: Any) -> Any:
    """Drop what a sheet sends for an untouched optional field, and nothing else.

    Empty strings and nulls are removed so pydantic sees an absent field and applies its default, rather than being
    handed "" where it wants a float. `False` and `0` are real answers and always survive.
    """
    if isinstance(value, dict):
        out = {k: prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if not _empty(v)}
    if isinstance(value, list):
        return [v for v in (prune(v) for v in value) if not _empty(v)]
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == {} or value == []


def split_payload(payload: dict) -> tuple[dict, dict]:
    """Separate the submitted fields from the sheet's own metadata."""
    data = dict(payload)
    meta = data.pop(FORM_META_KEY, None) or {}
    return prune(data), meta


def load_payload(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("submission payload must be a JSON object")
    return payload


def header(meta: dict, command: str, closing: str) -> str:
    lines = [f"# Written by '{command}' from a web sheet submission."]
    for label, key in (("submission", "slug"), ("submitted", "submitted_at"), ("entered by", "entered_by"),
                       ("reviewer", "reviewer")):
        if meta.get(key):
            lines.append(f"# {label}: {meta[key]}")
    lines.append(f"# {closing}")
    return "\n".join(lines) + "\n"


def write_submission(target: str | Path, payload: dict, model, command: str, closing: str,
                     force: bool = False) -> tuple[Path, dict, dict]:
    """Validate `payload` against `model` and write it as YAML to `target`.

    Nothing touches the filesystem until validation passes, so a rejected submission never leaves a half-written file
    behind. Returns the path, the pruned data and the sheet metadata.
    """
    path = Path(target)
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass force to overwrite")

    data, meta = split_payload(payload)
    model(**data)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header(meta, command, closing) + yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                                                                    width=100), encoding="utf-8")
    return path, data, meta
