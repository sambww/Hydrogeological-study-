from __future__ import annotations

from importlib import resources

import yaml


def load_reference(name: str) -> dict:
    text = resources.files("hydrostudy.reference").joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)
