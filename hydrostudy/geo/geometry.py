"""Shapely helpers in local feet."""

from __future__ import annotations

from shapely.geometry import Point, Polygon, shape
from shapely.ops import transform as shp_transform

from hydrostudy.geo.crs import LocalCRS


def circle(x_ft: float, y_ft: float, radius_ft: float, resolution: int = 128) -> Polygon:
    return Point(x_ft, y_ft).buffer(radius_ft, resolution=resolution)


def reproject_geometry(geom, crs: LocalCRS):
    """WGS84 geometry -> local feet."""
    return shp_transform(lambda x, y, z=None: crs.to_local(x, y), geom)


def geojson_to_local(geojson: dict, crs: LocalCRS) -> list:
    """Return list of (properties, local geometry) from a GeoJSON FeatureCollection/Feature/Geometry."""
    out = []
    t = geojson.get("type")
    if t == "FeatureCollection":
        feats = geojson.get("features", [])
    elif t == "Feature":
        feats = [geojson]
    else:
        feats = [{"type": "Feature", "properties": {}, "geometry": geojson}]
    for f in feats:
        g = f.get("geometry")
        if not g:
            continue
        out.append((f.get("properties") or {}, reproject_geometry(shape(g), crs)))
    return out


def distance_to_boundary_ft(x_ft: float, y_ft: float, boundary: Polygon) -> float:
    """Distance from a point to the nearest edge of a property polygon (0 if on the edge)."""
    return float(boundary.exterior.distance(Point(x_ft, y_ft)))
