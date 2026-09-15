"""Streams, ponds and springs within the surface-water radius (GeoJSON when available, else manifest notes)."""

from __future__ import annotations

import csv

from shapely.geometry import Point

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
            d = geom.distance(Point(*site_xy))
            if d <= radius_ft:
                name = props.get("name") or props.get("GNIS_NAME") or props.get("gnis_name") or "unnamed"
                ftype = props.get("type") or props.get("FTYPE") or "stream"
                features.append({"name": str(name), "type": str(ftype), "distance_ft": float(d), "source": f.source})
                geoms.append((str(name), geom))
    notes = [dict(n) for n in manifest.hydrography_notes if n.get("within_1_mile", True)]
    springs = dict(manifest.springs or {})
    sp_file = manifest.get("springs_csv")
    if sp_file is not None:
        found = list(springs.get("found") or [])
        with open(sp_file.path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    x, y = crs.to_local(float(row["lon"]), float(row["lat"]))
                except (KeyError, ValueError):
                    continue
                d = ((x - site_xy[0]) ** 2 + (y - site_xy[1]) ** 2) ** 0.5
                if d <= radius_ft:
                    found.append(f"{row.get('name') or 'unnamed spring'} ({d:,.0f} ft)")
        springs.update({"searched": True, "found": found, "source": springs.get("source") or sp_file.source})
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
