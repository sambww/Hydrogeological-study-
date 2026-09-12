from __future__ import annotations

import hashlib
import json
from pathlib import Path


class OfflineError(RuntimeError):
    pass


def _requests():
    try:
        import requests  # optional dependency (pip install hydrostudy[connectors])
    except ImportError as e:
        raise OfflineError("install the 'connectors' extra: pip install -e .[connectors]") from e
    return requests


class Cache:
    """Simple on-disk cache keyed by URL (+ params) so repeated runs do not re-download large files."""

    def __init__(self, root: str | Path = "data/cache"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, url: str, params: dict | None = None, suffix: str = "") -> Path:
        key = hashlib.sha256((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()[:24]
        return self.root / f"{key}{suffix}"

    def get(self, url: str, params: dict | None = None, suffix: str = "", timeout: int = 120, binary: bool = False):
        p = self.path_for(url, params, suffix)
        if p.exists():
            return p
        r = _requests().get(url, params=params, timeout=timeout)
        r.raise_for_status()
        p.write_bytes(r.content if binary else r.content)
        return p


def arcgis_query_geojson(service_layer_url: str, where: str = "1=1", geometry_bbox=None, out_fields: str = "*",
                         cache: Cache | None = None, max_records: int = 2000) -> dict:
    """Query an ArcGIS REST FeatureServer/MapServer layer and return GeoJSON (WGS84).
    geometry_bbox = (min_lon, min_lat, max_lon, max_lat)."""
    params = {"where": where, "outFields": out_fields, "f": "geojson", "outSR": 4326, "resultRecordCount": max_records}
    if geometry_bbox:
        params.update({"geometry": ",".join(str(v) for v in geometry_bbox), "geometryType": "esriGeometryEnvelope",
                       "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"})
    url = service_layer_url.rstrip("/") + "/query"
    if cache:
        p = cache.get(url, params, ".geojson")
        return json.loads(p.read_text(encoding="utf-8"))
    r = _requests().get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def bbox_around(lat: float, lon: float, radius_mi: float):
    dlat = radius_mi / 69.0
    dlon = radius_mi / (69.0 * max(0.2, abs(__import__("math").cos(__import__("math").radians(lat)))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)
