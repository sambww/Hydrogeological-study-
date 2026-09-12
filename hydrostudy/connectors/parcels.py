"""County parcel polygons (Montgomery County open data: MCAD Tax Parcel View on ArcGIS Hub)."""

from __future__ import annotations

from hydrostudy.connectors.base import Cache, arcgis_query_geojson, bbox_around

# Set to the FeatureServer layer URL shown on the dataset's API page (data-moco.opendata.arcgis.com, "MCAD Tax Parcel View").
MONTGOMERY_PARCELS_LAYER = None


def fetch_parcels_geojson(lat: float, lon: float, radius_mi: float = 0.5, layer_url: str | None = None,
                          cache: Cache | None = None) -> dict:
    url = layer_url or MONTGOMERY_PARCELS_LAYER
    if not url:
        raise ValueError("parcel layer URL not configured; copy it from the county open-data portal's API page")
    return arcgis_query_geojson(url, geometry_bbox=bbox_around(lat, lon, radius_mi), cache=cache)
