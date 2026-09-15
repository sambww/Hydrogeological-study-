"""Resolve the aquifer parameters used in the simulation (review override > site test > intake value)."""

from __future__ import annotations

from hydrostudy.analysis.theis import specific_capacity, transmissivity_from_specific_capacity
from hydrostudy.units import hours_to_days


def resolve_params(intake, review, gam: dict | None = None, apply_review: bool = True) -> dict:
    out = {}
    for a in intake.aquifers:
        p = a.params
        t, s, k = p.t_ft2d, p.s, p.k_ftd
        derivation = []
        source_kind = p.source.kind
        gam_layer = (gam or {}).get("_layers", {}).get(a.name) if gam else None
        gam_note = None
        gam_mismatch = None
        top, bottom = a.top_ft_bgl, a.bottom_ft_bgl
        if gam_layer:
            if t is None and source_kind == "gam" and gam_layer.get("t_ft2d"):
                t = gam_layer["t_ft2d"]
                gam_note = f"transmissivity from {gam['_source']} at the site cell"
            elif t is not None and gam_layer.get("t_ft2d") and abs(gam_layer["t_ft2d"] - t) / t > 0.25:
                gam_mismatch = {"stated_t_ft2d": t, "gam_t_ft2d": gam_layer["t_ft2d"]}
                gam_note = (f"stated transmissivity {t:,.0f} ft2/day differs from the {gam['_source']} value at the site cell "
                            f"({gam_layer['t_ft2d']:,.0f} ft2/day) by more than 25%")
            if s is None and gam_layer.get("s"):
                s = gam_layer["s"]
            if k is None and gam_layer.get("k_ftd"):
                k = gam_layer["k_ftd"]
            if top is None and gam_layer.get("top_ft_bgl") is not None:
                top = gam_layer["top_ft_bgl"]
            if bottom is None and gam_layer.get("bottom_ft_bgl") is not None:
                bottom = gam_layer["bottom_ft_bgl"]
        if apply_review and review.decisions.s and a.name in review.decisions.s:
            s = review.decisions.s[a.name]
        if s is None:
            raise ValueError(f"{a.name}: storativity is required (state s or supply a GAM lookup)")
        if a.site_test is not None:
            st = a.site_test
            sc = specific_capacity(st.q_gpm, st.pwl_ft - st.swl_ft)
            t_sc = transmissivity_from_specific_capacity(sc, hours_to_days(st.duration_hr), st.r_w_ft, s)
            derivation.append({
                "method": "specific capacity (Theis 1963; Mace 2001)", "well_ref": st.well_ref,
                "q_gpm": st.q_gpm, "duration_hr": st.duration_hr, "swl_ft": st.swl_ft, "pwl_ft": st.pwl_ft,
                "drawdown_ft": st.pwl_ft - st.swl_ft, "specific_capacity_gpm_ft": sc, "r_w_ft": st.r_w_ft,
                "s_used": s, "t_ft2d": t_sc, "tracking_no": st.tracking_no,
            })
            if source_kind == "site_test":
                if p.t_ft2d is None:
                    t = t_sc
                elif abs(t_sc - p.t_ft2d) / p.t_ft2d > 0.02:
                    derivation[-1]["mismatch_note"] = (
                        f"Derived T = {t_sc:,.0f} ft2/day differs from the stated T = {p.t_ft2d:,.0f} ft2/day by more than 2%.")
        if t is None:
            raise ValueError(f"{a.name}: transmissivity is required (state t_ft2d or provide a site_test)")
        overrides = []
        if apply_review and review.decisions.t_ft2d and a.name in review.decisions.t_ft2d:
            t = review.decisions.t_ft2d[a.name]
            overrides.append("T")
        if apply_review and review.decisions.s and a.name in review.decisions.s:
            overrides.append("S")
        b = (bottom - top) if (top is not None and bottom is not None) else None
        k_derived = False
        if k is None and b:
            k = t / b
            k_derived = True
        out[a.name] = {
            "aquifer": a.name, "t_ft2d": t, "s": s, "k_ftd": k, "k_derived": k_derived,
            "thickness_ft": b, "top_ft_bgl": top, "bottom_ft_bgl": bottom,
            "depth_source": a.source or (gam["_source"] if gam_layer and (a.top_ft_bgl is None) else None),
            "source_kind": source_kind,
            "citation": p.source.citation or (gam["_source"] if gam_layer else ""),
            "model_version": p.source.model_version or (f"{gam.get('model', '')} {gam.get('version', '')}".strip() if gam_layer else None),
            "notes": p.source.notes, "gam_note": gam_note, "gam_mismatch": gam_mismatch, "gam_layer": gam_layer,
            "derivations": derivation, "review_overrides": overrides,
            "confinement": a.confinement.model_dump(),
        }
    return out
