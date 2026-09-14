"""Build a per-project review sheet for the sealing professional.

A sealed report is reviewed against one specific draft, so the sheet is generated from that draft's build artifacts and
carries its revision. It shows the reviewer what the pipeline computed, what it flagged, and which opinions are still
placeholders, then collects the same fields `review.yaml` holds.

The point of generating it rather than shipping one shared form is the number check. `report/lint.py` fails the build
when an opinion cites a number the pipeline did not compute, so a reviewer can write a sound paragraph and have the
report refuse to build after they have signed off. The sheet carries that draft's allowed-number set and warns them
while they are still at the keyboard.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

#: What each opinion answers and what the reviewer is being asked for. Domain metadata, not computed, so it is
#: written once here rather than inferred from placeholder prose.
OPINION_META = {
    "aquifer_identification": {
        "label": "Aquifer identification",
        "guideline": "II.B.3(a)",
        "prompt": "Confirm which aquifer the well is completed in, and that this was settled with District staff.",
    },
    "recharge_features": {
        "label": "Surface geology and recharge features",
        "guideline": "II.B.3(b)",
        "prompt": "State the surface geologic unit at the site and any outcrop, surface water or faulting that "
                  "bears on recharge within the study area.",
    },
    "confinement": {
        "label": "Confinement",
        "guideline": "II.B.3(e) and (f)",
        "prompt": "State whether the target zone is confined, semi-confined or unconfined, and the confining "
                  "thickness if applicable.",
    },
    "parameter_selection": {
        "label": "Aquifer parameter selection",
        "guideline": "II.B.3(g)",
        "prompt": "Justify the transmissivity and storativity adopted, and say why they were preferred over the "
                  "alternatives shown below.",
    },
    "lithology_basis": {
        "label": "Basis for the anticipated lithology",
        "guideline": "II.B.2(b)",
        "prompt": "Say what the anticipated lithology was interpreted from.",
    },
    "water_quality": {
        "label": "Water quality",
        "guideline": "II.B.4(a)",
        "prompt": "Interpret the water-quality data against the proposed completion interval, and note any "
                  "logging, sampling or treatment worth recommending.",
    },
    "spacing": {
        "label": "Spacing",
        "guideline": "II.B.1",
        "prompt": "Comment on the spacing result, including any exception being requested.",
    },
    "conclusion": {
        "label": "Conclusion and professional opinion",
        "guideline": "II.B.5",
        "prompt": "Give your opinion on the anticipated effect of the proposed production on nearby wells and on "
                  "the adequacy of the analysis, with any recommendations.",
    },
}

REQUIRED_ARTIFACTS = ("analysis.json", "report.json", "flags.json", "checklist.json", "provenance.json")


class SheetNotReady(RuntimeError):
    """The project has not been built, so there is no draft to review."""


def _load(build: Path, name: str) -> dict | list:
    return json.loads((build / name).read_text(encoding="utf-8"))


def build_sheet_context(project_dir: str | Path) -> dict:
    """Gather everything the reviewer needs from a project that has already been run."""
    d = Path(project_dir)
    build = d / "build"
    missing = [n for n in REQUIRED_ARTIFACTS if not (build / n).exists()]
    if missing:
        raise SheetNotReady(
            f"{d} has no draft to review (missing {', '.join(missing)}). Run 'hydrostudy run {d}' first."
        )

    analysis = _load(build, "analysis.json")
    report = _load(build, "report.json")
    flags = _load(build, "flags.json")
    checklist = _load(build, "checklist.json")
    prov = _load(build, "provenance.json")

    from hydrostudy.schema.loaders import load_intake, load_review
    intake = load_intake(d / "intake.yaml")
    review = load_review(d / "review.yaml")

    pending = set(checklist.get("placeholders_pending") or [])
    # Placeholder prose from the draft, so the reviewer sees the wording their answer replaces.
    by_section: dict[str, list[str]] = {}
    for section, text in report.get("placeholders") or []:
        by_section.setdefault(section, []).append(text)

    opinions = []
    for key, meta in OPINION_META.items():
        current = getattr(review.opinions, key, None)
        # A null opinion does not always leave a placeholder: some sentences fall back to the intake instead. Match
        # the draft wording by the guideline item it cites, and only guess when a section holds exactly one.
        section = by_section.get(_section_for(key), [])
        cited = [t for t in section if meta["guideline"] in t]
        if not cited and len(section) == 1:
            cited = list(section)
        opinions.append({
            "key": key, "label": meta["label"], "guideline": meta["guideline"], "prompt": meta["prompt"],
            "pending": key in pending, "current": current, "draft_text": cited,
        })

    aquifers = []
    for name, p in (analysis.get("aquifer_params") or {}).items():
        aquifers.append({
            "name": name, "t_ft2d": p.get("t_ft2d"), "s": p.get("s"), "k_ftd": p.get("k_ftd"),
            "source_kind": p.get("source_kind"), "model_version": p.get("model_version"),
            "citation": p.get("citation"), "gam_note": p.get("gam_note"),
            "derivations": [dv.get("label") or dv.get("method") for dv in (p.get("derivations") or [])],
            "confinement": (p.get("confinement") or {}).get("status"),
            "top_ft_bgl": p.get("top_ft_bgl"), "bottom_ft_bgl": p.get("bottom_ft_bgl"),
        })

    wells = [{"id": w["id"], "aquifer": w["aquifer"], "q_gpm": w["q_gpm"], "r_w_ft": w["r_w_ft"],
              "kind": w["kind"], "label": _label_for(intake, w["id"])}
             for w in (analysis.get("wells") or [])]

    scenarios = []
    for s in analysis.get("scenarios") or []:
        for aq, res in (s.get("results_by_aquifer") or {}).items():
            for pw in res.get("pumped_wells") or []:
                scenarios.append({"scenario": s["title"], "aquifer": aq, "well": pw.get("well_id"),
                                  "drawdown_ft": pw.get("total_ft")})

    return {
        "project": {
            "dir": str(d),
            "title": intake.report.title,
            "applicant": intake.applicant.name,
            "district": intake.district.id,
            "county": intake.district.county,
            "revision": intake.report.revision.number,
            "status": review.reviewer.status,
            "docx": Path(report.get("docx") or "").name,
            "generated_at": prov.get("generated_at"),
            "mode": intake.mode,
        },
        "reviewer": review.reviewer.model_dump(),
        "decisions": review.decisions.model_dump(),
        "notes": list(review.notes or []),
        "opinions": opinions,
        "aquifers": aquifers,
        "wells": wells,
        "scenarios": scenarios,
        "cone_thresholds": list(intake.analysis.cone_edge_thresholds_ft),
        "flags": [f for f in flags if f.get("level") in ("review", "warn")],
        "checklist": [i for i in checklist.get("items") or [] if i.get("status") != "satisfied"],
        "allowed_numbers": report.get("allowed_numbers") or [],
        "spacing_source": (prov.get("district_rules") or {}).get("spacing_source"),
    }


#: Which narrative section each opinion's placeholder is rendered into, so the draft wording can be matched to it.
_SECTIONS = {"aquifer_identification": "site", "recharge_features": "site", "confinement": "site",
             "parameter_selection": "site", "lithology_basis": "construction", "water_quality": "water_quality",
             "spacing": "spacing", "conclusion": "summary"}


def _section_for(key: str) -> str:
    return _SECTIONS.get(key, "summary")


def _label_for(intake, well_id: str) -> str:
    for w in intake.all_wells:
        if w.id == well_id:
            return w.label
    return well_id


def render_sheet(project_dir: str | Path, out: str | Path | None = None) -> Path:
    """Write `build/review_sheet.html` for this project."""
    ctx = build_sheet_context(project_dir)
    template = resources.files("hydrostudy.report.sheets").joinpath("review_sheet.html").read_text(encoding="utf-8")
    html = template.replace("__CONTEXT__", json.dumps(ctx, indent=1, ensure_ascii=False))
    target = Path(out) if out else Path(project_dir) / "build" / "review_sheet.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target
