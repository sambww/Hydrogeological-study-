"""USGS Elevation Point Query Service (3DEP)."""

from __future__ import annotations

from hydrostudy.connectors.base import _requests

EPQS = "https://epqs.nationalmap.gov/v1/json"


def ground_elevation_ft(lat: float, lon: float) -> float | None:
    r = _requests().get(EPQS, params={"x": lon, "y": lat, "units": "Feet", "wkid": 4326, "includeDate": "false"}, timeout=60)
    r.raise_for_status()
    v = r.json().get("value")
    return None if v in (None, "", "-1000000") else float(v)
