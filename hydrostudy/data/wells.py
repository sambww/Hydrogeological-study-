"""Nearby registered/permitted wells: load, normalize, locate, and rank."""

from __future__ import annotations

import math
import re

import pandas as pd

from hydrostudy.data.manifest import Manifest
from hydrostudy.geo.crs import LocalCRS, parse_coordinate
from hydrostudy.units import FT_PER_MILE

STANDARD_COLUMNS = ["registration_no", "permit_no", "owner", "address", "city", "total_depth_ft",
                    "screen_intervals", "aquifer", "status", "lat", "lon", "use", "source"]


def _norm_status(s) -> str:
    if s is None or (isinstance(s, float) and math.isnan(s)) or str(s).strip() == "":
        return "Unknown"
    return str(s).strip()


def _first_screen_top(text) -> float | None:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    m = re.findall(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", str(text))
    if not m:
        return None
    return float(m[0][0])


def _screen_midpoint(text) -> float | None:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    m = re.findall(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", str(text))
    if not m:
        return None
    tops = [float(a) for a, _ in m]
    bots = [float(b) for _, b in m]
    return (min(tops) + max(bots)) / 2


def infer_aquifer(depth_mid: float | None, aquifers: list) -> str | None:
    """Assign an aquifer from screen midpoint using the intake's top/bottom depths (labelled as inferred)."""
    if depth_mid is None:
        return None
    for a in aquifers:
        if a.top_ft_bgl is not None and a.bottom_ft_bgl is not None and a.top_ft_bgl <= depth_mid <= a.bottom_ft_bgl:
            return a.name
    return None


def load_district_wells(manifest: Manifest, key: str = "district_wells") -> pd.DataFrame:
    df_file = manifest.get(key)
    if df_file is None:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    df = pd.read_csv(df_file.path, dtype=str)
    if df_file.columns:
        df = df.rename(columns={v: k for k, v in df_file.columns.items()})
    for c in STANDARD_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["source"] = df["source"].fillna(df_file.source or key)
    return df


def build_nearby_wells(intake, district, crs: LocalCRS, manifest: Manifest, search_radius_ft: float,
                       spacing_radius_ft: float) -> list[dict]:
    df = load_district_wells(manifest)
    proposed = [(w.id, *crs.to_local(w.lon, w.lat)) for w in intake.proposed_wells]
    system_regs = {w.registration_no for w in intake.existing_wells if w.registration_no}
    map_radius_ft = float(district.get("wells_map_radius_mi", 1.0)) * FT_PER_MILE
    rows = []
    for _, r in df.iterrows():
        try:
            lat = parse_coordinate(r["lat"], "lat")
            lon = parse_coordinate(r["lon"], "lon")
        except Exception:
            continue
        x, y = crs.to_local(lon, lat)
        dists = {pid: math.hypot(x - px, y - py) for pid, px, py in proposed}
        dmin = min(dists.values())
        nearest = min(dists, key=dists.get)
        td = r.get("total_depth_ft")
        try:
            td = float(td) if td not in (None, "") and not (isinstance(td, float) and math.isnan(td)) else None
        except ValueError:
            td = None
        aquifer = r.get("aquifer")
        aquifer = None if aquifer in (None, "") or (isinstance(aquifer, float) and math.isnan(aquifer)) else str(aquifer).strip()
        inferred = False
        if not aquifer:
            mid = _screen_midpoint(r.get("screen_intervals")) or (td * 0.9 if td else None)
            aquifer = infer_aquifer(mid, intake.aquifers)
            inferred = aquifer is not None
        reg = str(r.get("registration_no") or "").strip()
        rows.append({
            "registration_no": reg,
            "permit_no": str(r.get("permit_no") or "").strip() or "N/A",
            "owner": str(r.get("owner") or "").strip(),
            "address": str(r.get("address") or "").strip(),
            "city": str(r.get("city") or "").strip(),
            "total_depth_ft": td,
            "screen_intervals": None if r.get("screen_intervals") in (None, "") or (isinstance(r.get("screen_intervals"), float) and math.isnan(r.get("screen_intervals"))) else str(r.get("screen_intervals")),
            "aquifer": aquifer,
            "aquifer_inferred": inferred,
            "status": _norm_status(r.get("status")),
            "lat": lat, "lon": lon, "x_ft": x, "y_ft": y,
            "distance_ft": dmin, "nearest_proposed_well": nearest, "distance_by_well": dists,
            "in_search_radius": dmin <= search_radius_ft,
            "in_spacing_radius": dmin <= spacing_radius_ft,
            "in_map_radius": dmin <= map_radius_ft,
            "is_system_well": reg in system_regs,
            "source": str(r.get("source") or ""),
        })
    rows.sort(key=lambda d: d["distance_ft"])
    for i, d in enumerate(rows, 1):
        d["map_id"] = i
    return rows
