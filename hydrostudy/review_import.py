"""Turn a review sheet submission into a project `review.yaml`.

Same contract as the intake sheet: JSON shaped like the YAML file, validated by constructing the schema model, written
as the reviewer's own input. A reviewer's prose is written back exactly as typed, because it is going into a document
someone seals.
"""

from __future__ import annotations

from pathlib import Path

from hydrostudy.schema.review import Review
from hydrostudy.submission import load_payload, split_payload, write_submission

__all__ = ["load_payload", "payload_to_review", "write_review"]


def payload_to_review(payload: dict) -> tuple[Review, dict, dict]:
    """Validate a submission. Raises pydantic's ValidationError, which names the offending field."""
    data, meta = split_payload(payload)
    return Review(**data), data, meta


def write_review(project_dir: str | Path, payload: dict, force: bool = False) -> Path:
    """Validate `payload` and write `<project_dir>/review.yaml`."""
    target, _, _ = write_submission(
        Path(project_dir) / "review.yaml", payload, Review,
        command="hydrostudy import-review",
        closing="Re-run the report so the opinions and any parameter decisions take effect.",
        force=force,
    )
    return target
