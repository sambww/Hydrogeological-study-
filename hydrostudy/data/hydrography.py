"""Streams, ponds and springs within the surface-water radius (GeoJSON when available, else manifest notes)."""

from __future__ import annotations

from hydrostudy.data.manifest import Manifest
from hydrostudy.geo.geometry import geojson_to_local
from hydrostudy.geo.io import read_geojson
from hydrostudy.units import FT_PER_MILE


def build_hydrography(manifest: Manifest, crs, site_xy: tuple, radius_mi: float) -> dict:
    radius_ft = radius_mi * FT_PER_MILE
    features = []
    geoms = []
    f = manifest.get("streams")
    if f is not None:
        for props, geom in geojson_to_local(read_geojson(f.path), crs):
            d = geom.distance(__import__("shapely.geometry", fromlist=["Point"]).Point(*site_xy))
            if d <= radius_ft:
                name = props.get("name") or props.get("GNIS_NAME") or props.get("gnis_name") or "unnamed"
                ftype = props.get("type") or props.get("FTYPE") or "stream"
                features.append({"name": str(name), "type": str(ftype), "distance_ft": float(d), "source": f.source})
                geoms.append((str(name), geom))
    notes = [dict(n) for n in manifest.hydrography_notes if n.get("within_1_mile", True)]
    springs = manifest.springs or {}
    return {
        "radius_mi": radius_mi,
        "features": features,               # from GeoJSON
        "notes": notes,                     # named features without geometry
        "springs_searched": bool(springs.get("searched", False)),
        "springs_found": springs.get("found") or [],
        "springs_source": springs.get("source"),
        "has_geometry": bool(geoms),
        "_geoms": geoms,
    }
