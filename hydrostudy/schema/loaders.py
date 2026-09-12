from __future__ import annotations

from pathlib import Path

import yaml

from hydrostudy.schema.intake import Intake
from hydrostudy.schema.review import Review


def load_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_intake(path: str | Path) -> Intake:
    return Intake.model_validate(load_yaml(path))


def load_review(path: str | Path | None) -> Review:
    if path is None or not Path(path).exists():
        return Review()
    return Review.model_validate(load_yaml(path))
