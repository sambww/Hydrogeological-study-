"""USGS National Hydrography Dataset flowlines and waterbodies via the National Map ArcGIS REST service."""

from __future__ import annotations

from hydrostudy.connectors.base import Cache, arcgis_query_geojson, bbox_around

NHD_BASE = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
FLOWLINE_LAYER = 6   # NHDFlowline (verify layer ids against the service's layer list)
WATERBODY_LAYER = 10  # NHDWaterbody


def fetch_streams_geojson(lat: float, lon: float, radius_mi: float = 1.5, cache: Cache | None = None) -> dict:
    bbox = bbox_around(lat, lon, radius_mi)
    feats = []
    for layer, ftype in ((FLOWLINE_LAYER, "stream"), (WATERBODY_LAYER, "pond")):
        gj = arcgis_query_geojson(f"{NHD_BASE}/{layer}", geometry_bbox=bbox, out_fields="gnis_name,ftype,fcode", cache=cache)
        for f in gj.get("features", []):
            props = f.get("properties") or {}
            props["name"] = props.get("gnis_name") or props.get("GNIS_NAME") or "unnamed"
            props["type"] = ftype
            f["properties"] = props
            feats.append(f)
    return {"type": "FeatureCollection", "features": feats}
