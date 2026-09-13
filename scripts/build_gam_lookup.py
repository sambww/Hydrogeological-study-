#!/usr/bin/env python
"""Sample a TWDB groundwater availability model at a site and write data/gam_lookup.json for hydrostudy.

NOT exercised in the sandbox where this was written (model files could not be downloaded); validate on a machine with
the model archives. Requires `pip install flopy` (optional extra: pip install -e .[gam]).

Supported models
  --engine mf6  : MODFLOW 6 (GULF-2023 / Northern Gulf Coast GAM v4.x). Point --model-dir at the folder with mfsim.nam.
  --engine mf2k : MODFLOW-2000/2005 (HAGM, Kasmarek 2013). Point --name-file at the .nam file and give the grid
                  georeference (--epsg, --xoff, --yoff, --angrot) if the name file does not carry it.

Layer names are given in model layer order with --layers (e.g. "Chicot,Evangeline,Burkeville,Jasper"). Units are
assumed feet and days as in the TWDB models; use --length-to-ft / --time-to-day to convert otherwise.

Usage:
  python scripts/build_gam_lookup.py --engine mf6 --model-dir /path/to/gam --lat 30.170 --lon -95.578 \
      --layers Chicot,Evangeline,Burkeville,Jasper --out projects/<slug>/data/gam_lookup.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import numpy as np


def _load_mf6(model_dir):
    import flopy
    sim = flopy.mf6.MFSimulation.load(sim_ws=model_dir, verbosity_level=0)
    gwf = sim.get_model(sim.model_names[0])
    grid = gwf.modelgrid
    npf = gwf.get_package("NPF")
    sto = gwf.get_package("STO")
    dis = gwf.get_package("DIS")
    k = np.asarray(npf.k.array, dtype=float)
    ss = np.asarray(sto.ss.array, dtype=float) if sto is not None else None
    sy_data = sto.sy.get_data() if sto is not None and getattr(sto, "sy", None) is not None else None
    sy = np.asarray(sy_data, dtype=float) if sy_data is not None else None
    top = np.asarray(dis.top.array, dtype=float)
    botm = np.asarray(dis.botm.array, dtype=float)
    return grid, k, ss, sy, top, botm


def _load_mf2k(name_file, model_dir, epsg, xoff, yoff, angrot):
    import flopy
    m = flopy.modflow.Modflow.load(name_file, model_ws=model_dir, check=False, verbose=False)
    grid = m.modelgrid
    if epsg or xoff or yoff:
        grid.set_coord_info(xoff=xoff or 0.0, yoff=yoff or 0.0, angrot=angrot or 0.0, crs=epsg)
    lpf = m.get_package("LPF") or m.get_package("UPW") or m.get_package("BCF6")
    k = np.asarray(lpf.hk.array, dtype=float)
    ss = np.asarray(lpf.ss.array, dtype=float) if hasattr(lpf, "ss") else None
    sy = np.asarray(lpf.sy.array, dtype=float) if hasattr(lpf, "sy") else None
    dis = m.get_package("DIS")
    top = np.asarray(dis.top.array, dtype=float)
    botm = np.asarray(dis.botm.array, dtype=float)
    return grid, k, ss, sy, top, botm


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mf6", "mf2k"], required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--name-file", default=None, help="mf2k only")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--layers", required=True, help="comma-separated layer names in model order")
    ap.add_argument("--model-name", default="Northern Gulf Coast GAM")
    ap.add_argument("--version", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--half-cells", type=int, default=5)
    ap.add_argument("--epsg", default=None)
    ap.add_argument("--xoff", type=float, default=None)
    ap.add_argument("--yoff", type=float, default=None)
    ap.add_argument("--angrot", type=float, default=None)
    ap.add_argument("--length-to-ft", type=float, default=1.0)
    ap.add_argument("--time-to-day", type=float, default=1.0)
    ap.add_argument("--ground-elev-ft", type=float, default=None, help="site ground elevation to convert layer elevations to depth bgl (default: model top)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        import flopy  # noqa: F401
        from pyproj import Transformer
    except ImportError as e:
        print(f"missing dependency: {e}. pip install flopy pyproj", file=sys.stderr)
        return 2
    if a.engine == "mf6":
        grid, k, ss, sy, top, botm = _load_mf6(a.model_dir)
    elif not a.name_file:
        print("--engine mf2k requires --name-file", file=sys.stderr)
        return 2
    else:
        grid, k, ss, sy, top, botm = _load_mf2k(a.name_file, a.model_dir, a.epsg, a.xoff, a.yoff, a.angrot)
    crs = grid.crs or a.epsg
    if crs is None:
        print("model grid has no CRS; pass --epsg", file=sys.stderr)
        return 2
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = tr.transform(a.lon, a.lat)
    row, col = grid.intersect(x, y)
    names = [n.strip() for n in a.layers.split(",")]
    L = min(len(names), k.shape[0])
    lf, tf = a.length_to_ft, a.time_to_day
    ground = a.ground_elev_ft if a.ground_elev_ft is not None else float(top[row, col]) * lf
    layers = []
    for i in range(L):
        ztop = (top[row, col] if i == 0 else botm[i - 1, row, col]) * lf
        zbot = botm[i, row, col] * lf
        thick = max(ztop - zbot, 0.0)
        kk = float(k[i, row, col]) * lf / tf
        s_val = None
        if ss is not None:
            s_val = float(ss[i, row, col]) / lf * thick
        layers.append({"name": names[i], "top_ft_bgl": round(ground - ztop, 1), "bottom_ft_bgl": round(ground - zbot, 1),
                       "thickness_ft": round(thick, 1), "k_ftd": kk, "t_ft2d": kk * thick, "s": s_val,
                       "ss_per_ft": float(ss[i, row, col]) / lf if ss is not None else None,
                       "sy": float(sy[i, row, col]) if sy is not None else None})
    h = a.half_cells
    r0, r1 = max(row - h, 0), min(row + h + 1, k.shape[1])
    c0, c1 = max(col - h, 0), min(col + h + 1, k.shape[2])
    dx = float(np.mean(grid.delr)) * lf
    dy = float(np.mean(grid.delc)) * lf
    values = {}
    for i in range(L):
        thick = np.maximum(((top if i == 0 else botm[i - 1]) - botm[i]) * lf, 0.0)[r0:r1, c0:c1]
        kk = k[i, r0:r1, c0:c1] * lf / tf
        # rows increase downward in MODFLOW; flip so the array is south-to-north for plotting
        values[names[i]] = {"t": np.flipud(kk * thick).tolist(), "k": np.flipud(kk).tolist(),
                            "s": np.flipud(ss[i, r0:r1, c0:c1] / lf * thick).tolist() if ss is not None else None}
    out = {"model": a.model_name, "version": a.version, "source": a.source or f"{a.model_name} {a.version}".strip(),
           "generated": dt.date.today().isoformat(), "engine": a.engine, "crs": str(crs),
           "site": {"lat": a.lat, "lon": a.lon, "row": int(row), "col": int(col)}, "cell_size_ft": dx,
           "layers": layers,
           "neighborhood": {"half_cells": h, "x0_ft": -(col - c0 + 0.5) * dx, "y0_ft": -(r1 - row - 0.5) * dy,
                            "dx_ft": dx, "dy_ft": dy, "values": values}}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"wrote {a.out}: site cell row {row} col {col}; " + "; ".join(f"{lyr['name']} T={lyr['t_ft2d']:,.0f}" for lyr in layers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
