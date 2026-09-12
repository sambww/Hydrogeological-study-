"""TWDB Groundwater Database (GWDB) and Submitted Drillers Reports (SDR) bulk downloads.

Both are zip archives of pipe-delimited text tables, refreshed nightly. Table and column names are read from the
archive at run time (see the ReadMe folder inside each zip) so this module does not hard-code them; the caller maps
the well table columns into the hydrostudy standard columns."""

from __future__ import annotations

import csv
import io
import math
import zipfile
from pathlib import Path

from hydrostudy.connectors.base import Cache

GWDB_ZIP = "https://www.twdb.texas.gov/groundwater/data/GWDBDownload.zip"
SDR_ZIP = "https://www.twdb.texas.gov/groundwater/data/SDRDownload.zip"


def download(url: str, cache: Cache) -> Path:
    return cache.get(url, suffix=".zip", timeout=1800, binary=True)


def list_tables(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as z:
        return [n for n in z.namelist() if n.lower().endswith(".txt")]


def read_table(zip_path: Path, member: str, delimiter: str = "|") -> list[dict]:
    with zipfile.ZipFile(zip_path) as z, z.open(member) as fh:
        text = io.TextIOWrapper(fh, encoding="latin-1", errors="replace")
        return list(csv.DictReader(text, delimiter=delimiter))


def filter_by_radius(rows: list[dict], lat_col: str, lon_col: str, lat: float, lon: float, radius_mi: float) -> list[dict]:
    out = []
    for r in rows:
        try:
            la, lo = float(r[lat_col]), float(r[lon_col])
        except (KeyError, TypeError, ValueError):
            continue
        d = math.hypot((la - lat) * 69.0, (lo - lon) * 69.0 * math.cos(math.radians(lat)))
        if d <= radius_mi:
            r["_distance_mi"] = d
            out.append(r)
    return out


def write_standard_wells_csv(rows: list[dict], colmap: dict, path: Path, source: str):
    """colmap: standard column -> source column name."""
    std = ["registration_no", "permit_no", "owner", "address", "city", "total_depth_ft", "screen_intervals", "aquifer",
           "status", "lat", "lon", "use", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=std)
        w.writeheader()
        for r in rows:
            w.writerow({k: (r.get(colmap.get(k, ""), "") if k != "source" else source) for k in std})
