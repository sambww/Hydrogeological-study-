from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml


class District(dict):
    """District rules as a dict with helpers."""

    @property
    def id(self) -> str:
        return self["id"]

    def spacing_ft_per_gpm(self, aquifer: str):
        for rule in self.get("spacing", {}).get("well_to_well", []):
            if aquifer in rule.get("aquifers", []):
                return float(rule["ft_per_gpm"])
        return None

    def required_spacing_ft(self, aquifer: str, rate_gpm: float):
        m = self.spacing_ft_per_gpm(aquifer)
        return None if m is None else m * rate_gpm


def load_district(district_id: str, path: str | Path | None = None) -> District:
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("hydrostudy.districts").joinpath(f"{district_id}.yaml").read_text(encoding="utf-8")
    return District(yaml.safe_load(text))
