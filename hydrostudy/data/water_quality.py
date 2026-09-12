"""Water-quality records (long format) -> summaries with MCL/SCL flags."""

from __future__ import annotations

import math

import pandas as pd

from hydrostudy.data.manifest import Manifest
from hydrostudy.reference import load_reference

COLUMNS = ["well_id", "well_name", "source", "sample_date", "lat", "lon", "depth_ft", "aquifer",
           "constituent", "value", "units", "qualifier"]

_UNIT_FACTORS = {  # convert to the reference unit for each constituent when the CSV differs
    ("ug/l", "mg/l"): 1e-3, ("mg/l", "ug/l"): 1e3, ("ppm", "mg/l"): 1.0, ("ppb", "ug/l"): 1.0, ("ppb", "mg/l"): 1e-3,
}


def limits_table() -> dict:
    ref = load_reference("tceq_limits")
    return {c["key"]: c for c in ref["constituents"]}, ref


def _to_ref_units(value: float, units: str, ref_units: str) -> float:
    u, r = (units or "").strip().lower(), (ref_units or "").strip().lower()
    if not u or u == r or r in ("s.u.",):
        return value
    f = _UNIT_FACTORS.get((u, r))
    return value * f if f is not None else value


def load_samples(manifest: Manifest, key: str = "water_quality") -> pd.DataFrame:
    f = manifest.get(key)
    if f is None:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(f.path, dtype=str)
    if f.columns:
        df = df.rename(columns={v: k for k, v in f.columns.items()})
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df


def evaluate(value, qualifier, spec: dict) -> dict:
    """Flag a value against MCL/SCL. `qualifier` '<' or 'ND' means below detection."""
    q = (qualifier or "").strip().upper()
    nd = q in ("ND", "<", "U", "<DL")
    out = {"nd": nd, "exceeds_mcl": False, "exceeds_scl": False, "exceeds_action": False}
    if nd or value is None:
        return out
    if spec.get("mcl") is not None and value > spec["mcl"]:
        out["exceeds_mcl"] = True
    if spec.get("scl") is not None and value > spec["scl"]:
        out["exceeds_scl"] = True
    if spec.get("scl_min") is not None and value < spec["scl_min"]:
        out["exceeds_scl"] = True
    if spec.get("action_level") is not None and value > spec["action_level"]:
        out["exceeds_action"] = True
    return out


def build_water_quality(manifest: Manifest) -> dict:
    limits, ref = limits_table()
    df = load_samples(manifest)
    records = []
    for _, r in df.iterrows():
        key = str(r["constituent"] or "").strip().lower()
        spec = limits.get(key, {"key": key, "label": key, "units": r.get("units") or ""})
        raw = r.get("value")
        try:
            val = None if raw in (None, "") or (isinstance(raw, float) and math.isnan(raw)) else float(str(raw).replace("<", ""))
        except ValueError:
            val = None
        qual = r.get("qualifier")
        if isinstance(raw, str) and raw.strip().startswith("<"):
            qual = "<"
        if val is not None:
            val = _to_ref_units(val, r.get("units") or "", spec.get("units", ""))
        flags = evaluate(val, qual if isinstance(qual, str) else None, spec)
        try:
            depth = float(r["depth_ft"]) if r.get("depth_ft") not in (None, "") else None
        except (TypeError, ValueError):
            depth = None
        try:
            lat = float(r["lat"]) if r.get("lat") not in (None, "") else None
            lon = float(r["lon"]) if r.get("lon") not in (None, "") else None
        except (TypeError, ValueError):
            lat = lon = None
        records.append({
            "well_id": str(r.get("well_id") or ""), "well_name": str(r.get("well_name") or ""),
            "source": str(r.get("source") or ""), "sample_date": str(r.get("sample_date") or ""),
            "lat": lat, "lon": lon, "depth_ft": depth, "aquifer": str(r.get("aquifer") or ""),
            "constituent": key, "label": spec.get("label", key), "value": val,
            "units": spec.get("units", r.get("units") or ""), "nd": flags["nd"],
            "exceeds_mcl": flags["exceeds_mcl"], "exceeds_scl": flags["exceeds_scl"],
            "exceeds_action": flags["exceeds_action"],
            "mcl": spec.get("mcl"), "scl": spec.get("scl"), "scl_min": spec.get("scl_min"),
            "action_level": spec.get("action_level"),
        })
    # most recent sample per well and constituent
    latest = {}
    for rec in records:
        k = (rec["well_id"], rec["constituent"])
        if k not in latest or rec["sample_date"] > latest[k]["sample_date"]:
            latest[k] = rec
    by_constituent = {}
    for rec in latest.values():
        by_constituent.setdefault(rec["constituent"], []).append(rec)
    summaries = {}
    for key, recs in by_constituent.items():
        vals = [r["value"] for r in recs if r["value"] is not None and not r["nd"]]
        summaries[key] = {
            "label": recs[0]["label"], "units": recs[0]["units"], "n_wells": len(recs),
            "min": min(vals) if vals else None, "max": max(vals) if vals else None,
            "n_exceed_mcl": sum(r["exceeds_mcl"] for r in recs), "n_exceed_scl": sum(r["exceeds_scl"] for r in recs),
            "mcl": recs[0]["mcl"], "scl": recs[0]["scl"],
        }
    wells = {}
    for rec in latest.values():
        w = wells.setdefault(rec["well_id"], {"well_id": rec["well_id"], "well_name": rec["well_name"],
                                              "depth_ft": rec["depth_ft"], "aquifer": rec["aquifer"],
                                              "lat": rec["lat"], "lon": rec["lon"], "source": rec["source"],
                                              "sample_date": rec["sample_date"], "values": {}})
        w["values"][rec["constituent"]] = rec
        w["sample_date"] = max(w["sample_date"], rec["sample_date"])
    return {"limits_version": ref["version"], "limits_verify_on": ref["verify_on"], "limits_note": ref["note"],
            "n_records": len(records), "records": records, "summaries": summaries,
            "wells": list(wells.values()), "constituent_order": [c["key"] for c in ref["constituents"]],
            "limits": limits}
