from __future__ import annotations

import json
from pathlib import Path


def read_geojson(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
