"""Synthetic GeoJSON fixtures built around a site (WGS84) using offsets in feet."""

from __future__ import annotations

import json
from pathlib import Path

from hydrostudy.geo.crs import LocalCRS


def _ring(crs: LocalCRS, pts_ft):
    ring = [list(crs.to_wgs84(x, y)) for x, y in pts_ft]
    return ring + [ring[0]]


def _feature(geom, props):
    return {"type": "Feature", "properties": props, "geometry": geom}


def write_tract(project_dir: Path, lat: float, lon: float, half_x_ft: float, half_y_ft: float,
                name: str = "tract.geojson") -> str:
    """A rectangular tract centered on the site, big enough that a well has somewhere to move to."""
    crs = LocalCRS(lat, lon)
    data = project_dir / "data"
    data.mkdir(exist_ok=True)
    poly = {"type": "Polygon", "coordinates": [_ring(crs, [
        (-half_x_ft, -half_y_ft), (half_x_ft, -half_y_ft), (half_x_ft, half_y_ft), (-half_x_ft, half_y_ft)])]}
    (data / name).write_text(json.dumps({"type": "FeatureCollection",
                                         "features": [_feature(poly, {"name": "Applicant tract"})]}))
    return f"data/{name}"


def write_fixtures(project_dir: Path, lat: float, lon: float) -> dict:
    """Write boundary, parcels, county, streams GeoJSON and springs CSV; return manifest file entries."""
    crs = LocalCRS(lat, lon)
    data = project_dir / "data"
    data.mkdir(exist_ok=True)
    # property: 400 x 400 ft square with the well 25 ft from its east edge
    prop = {"type": "Polygon", "coordinates": [_ring(crs, [(-375, -200), (25, -200), (25, 200), (-375, 200)])]}
    (data / "boundary.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [_feature(prop, {"name": "Applicant tract"})]}))
    parcels = []
    for i, (x0, y0) in enumerate([(25, -200), (25, 100), (-375, 200)]):
        poly = {"type": "Polygon", "coordinates": [_ring(crs, [(x0, y0), (x0 + 300, y0), (x0 + 300, y0 + 300), (x0, y0 + 300)])]}
        parcels.append(_feature(poly, {"parcel_id": f"P{i+1}"}))
    (data / "parcels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": parcels}))
    county = {"type": "Polygon", "coordinates": [_ring(crs, [(-105600, -105600), (105600, -105600), (105600, 105600), (-105600, 105600)])]}
    (data / "county.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [_feature(county, {"name": "Test County"})]}))
    stream = {"type": "LineString", "coordinates": [list(crs.to_wgs84(x, 1500)) for x in (-6000, -2000, 2000, 6000)]}
    pond = {"type": "Polygon", "coordinates": [_ring(crs, [(2500, -2500), (3100, -2500), (3100, -1900), (2500, -1900)])]}
    far = {"type": "LineString", "coordinates": [list(crs.to_wgs84(x, 9000)) for x in (-6000, 6000)]}
    (data / "streams.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        _feature(stream, {"name": "Test Creek", "type": "stream"}), _feature(pond, {"name": "Test Pond", "type": "pond"}),
        _feature(far, {"name": "Far Creek", "type": "stream"})]}))
    sx, sy = crs.to_wgs84(4000, 0)
    fx, fy = crs.to_wgs84(20000, 0)
    (data / "springs.csv").write_text(f"name,lat,lon,source\nTest Spring,{sy},{sx},fixture\nFar Spring,{fy},{fx},fixture\n")
    return {
        "boundary": {"path": "boundary.geojson", "source": "fixture", "retrieved": "2026-01-01", "crs": "EPSG:4326"},
        "parcels": {"path": "parcels.geojson", "source": "fixture", "retrieved": "2026-01-01", "crs": "EPSG:4326"},
        "county": {"path": "county.geojson", "source": "fixture", "retrieved": "2026-01-01", "crs": "EPSG:4326"},
        "streams": {"path": "streams.geojson", "source": "fixture", "retrieved": "2026-01-01", "crs": "EPSG:4326"},
        "springs_csv": {"path": "springs.csv", "source": "fixture", "retrieved": "2026-01-01"},
    }
