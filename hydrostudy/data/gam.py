"""GAM parameter lookup file (produced by scripts/build_gam_lookup.py on a machine with the model files).

Schema of data/gam_lookup.json:
{
  "model": "Northern Gulf Coast GAM", "version": "v4.1", "source": "...", "generated": "YYYY-MM-DD",
  "site": {"lat": .., "lon": .., "row": .., "col": ..}, "cell_size_ft": 5280,
  "layers": [{"name": "Evangeline", "top_ft_bgl": .., "bottom_ft_bgl": .., "thickness_ft": .., "k_ftd": .., "t_ft2d": .., "s": ..}],
  "neighborhood": {"half_cells": 5, "x0_ft": .., "y0_ft": .., "dx_ft": .., "dy_ft": ..,
                    "values": {"Evangeline": {"t": [[..]], "k": [[..]], "s": [[..]]}}}
}
Local coordinates in the neighborhood are relative to the site (project local CRS, feet, x east, y north)."""

from __future__ import annotations

import json

from hydrostudy.data.manifest import Manifest


def load_gam_lookup(manifest: Manifest) -> dict | None:
    f = manifest.get("gam_lookup")
    if f is None:
        return None
    with open(f.path, encoding="utf-8") as fh:
        d = json.load(fh)
    d["_source"] = f.source or f"{d.get('model', 'GAM')} {d.get('version', '')}".strip()
    d["_layers"] = {lyr["name"]: lyr for lyr in d.get("layers", [])}
    return d
