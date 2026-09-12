#!/usr/bin/env python
"""Populate a project's data/ folder from public sources (run on a machine with internet access).

Usage:
  python scripts/fetch_public_data.py projects/<slug> [--radius-mi 1.5] [--parcels-layer URL]

What it does (best effort, each step independent):
  1. Ground elevation for each proposed well (USGS EPQS) -> printed; copy into intake.yaml.
  2. Streams/ponds within the radius (USGS NHD) -> data/streams.geojson + manifest entry.
  3. Parcels within 0.5 mile (county ArcGIS layer, if a URL is given) -> data/parcels.geojson.
  4. TWDB GWDB and SDR bulk archives -> cached under data/cache/; tables listed so you can map columns and append
     well records to data/district_wells.csv (the District's own export remains the primary source).
The LSGCD well export and TCEQ Drinking Water Viewer sample exports are obtained manually (see docs/DATA_SOURCES.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrostudy.connectors import elevation, hydrography, parcels, twdb
from hydrostudy.connectors.base import Cache
from hydrostudy.schema.loaders import load_intake


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--radius-mi", type=float, default=1.5)
    ap.add_argument("--parcels-layer", default=None)
    ap.add_argument("--skip-twdb", action="store_true")
    a = ap.parse_args()
    pdir = Path(a.project_dir)
    intake = load_intake(pdir / "intake.yaml")
    data = pdir / "data"
    data.mkdir(exist_ok=True)
    cache = Cache(data / "cache")
    mpath = data / "manifest.yaml"
    manifest = yaml.safe_load(mpath.read_text()) if mpath.exists() else {"files": {}}
    manifest.setdefault("files", {})
    pw = intake.proposed_wells[0]

    print("== Elevations (USGS EPQS)")
    for w in intake.proposed_wells:
        try:
            print(f"  {w.id}: {elevation.ground_elevation_ft(w.lat, w.lon)} ft MSL  (set elevation_ft_msl in intake.yaml)")
        except Exception as e:
            print(f"  {w.id}: failed ({e})")

    print("== Hydrography (USGS NHD)")
    try:
        gj = hydrography.fetch_streams_geojson(pw.lat, pw.lon, a.radius_mi, cache)
        (data / "streams.geojson").write_text(json.dumps(gj))
        manifest["files"]["streams"] = {"path": "streams.geojson", "source": "USGS National Hydrography Dataset (ArcGIS REST)",
                                        "retrieved": __import__("datetime").date.today().isoformat(), "crs": "EPSG:4326"}
        print(f"  {len(gj['features'])} features written to data/streams.geojson")
    except Exception as e:
        print(f"  failed ({e})")

    if a.parcels_layer:
        print("== Parcels")
        try:
            gj = parcels.fetch_parcels_geojson(pw.lat, pw.lon, 0.5, a.parcels_layer, cache)
            (data / "parcels.geojson").write_text(json.dumps(gj))
            manifest["files"]["parcels"] = {"path": "parcels.geojson", "source": a.parcels_layer,
                                            "retrieved": __import__("datetime").date.today().isoformat(), "crs": "EPSG:4326"}
            print(f"  {len(gj['features'])} parcels written")
        except Exception as e:
            print(f"  failed ({e})")

    if not a.skip_twdb:
        print("== TWDB bulk archives (large downloads, cached)")
        for name, url in (("GWDB", twdb.GWDB_ZIP), ("SDR", twdb.SDR_ZIP)):
            try:
                z = twdb.download(url, cache)
                tables = twdb.list_tables(z)
                print(f"  {name}: {z} ({len(tables)} tables): {', '.join(tables[:12])}{' ...' if len(tables) > 12 else ''}")
            except Exception as e:
                print(f"  {name}: failed ({e})")
        print("  Next: pick the well table, map its columns with twdb.write_standard_wells_csv(), and append to data/district_wells.csv")

    mpath.write_text(yaml.safe_dump(manifest, sort_keys=False))
    print(f"manifest updated: {mpath}")


if __name__ == "__main__":
    main()
