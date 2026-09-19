"""Assemble the DOCX report in the District guideline order, lint the narrative, and export a PDF review copy."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

from hydrostudy.analysis.theis import theis_drawdown
from hydrostudy.districts.status import spacing_basis_sentence
from hydrostudy.reference import load_reference
from hydrostudy.report.context import build_context, scenario_groups
from hydrostudy.report.docx_builder import PLACEHOLDER_RE, DocBuilder
from hydrostudy.report.equations import render_equations
from hydrostudy.report.lint import allowed_number_set, lint_sections, numbers_in
from hydrostudy.report.pdf import convert_to_pdf
from hydrostudy.units import fmt_ft

# Published benchmark (District-accepted 2023 submittal): inputs and reported values, used as a self-check in Appendix C.
BENCHMARK = {"q_gpm": 385, "t_ft2d": 1023, "s": 3.36e-4, "cases": [
    (0.5, 1.0, 98.7), (0.5, 52.31, 121.5), (25.0, 1.0, 53.6), (25.0, 52.31, 76.4), (1032.0, 1.0, 11.2), (1032.0, 52.31, 33.5)]}


class LintError(RuntimeError):
    pass


def _env():
    env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, autoescape=False)
    return env


def _template(name: str) -> str:
    return resources.files("hydrostudy.report.narrative").joinpath(name).read_text(encoding="utf-8")


def _static(name: str) -> str:
    text = resources.files("hydrostudy.report.static").joinpath(name).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->\s*", "", text, flags=re.DOTALL).strip()


def _letterhead(project) -> dict:
    lh = yaml.safe_load(resources.files("hydrostudy.report").joinpath("letterheads.yaml").read_text(encoding="utf-8"))
    kind = project.intake.report.issuing_firm
    if kind == "reviewer":
        r = project.review.reviewer
        return {"firm": r.firm or "[REVIEWER FIRM]", "lines": [],
                "registration_line": f"TBPG Firm Registration No. {r.firm_registration_no or '[____]'}"}
    return lh.get(kind, lh["generic"])


def build_report(project, pdf: bool = True, strict_lint: bool = True) -> dict:
    A = project.artifacts
    if "figures" not in A:
        raise RuntimeError("run figures before the report")
    ctx = build_context(project)
    env = _env()
    sections = {}
    feas = project.intake.mode == "feasibility"
    names = {"intro": "intro_feasibility.j2" if feas else "intro.j2", "spacing": "spacing.j2", "construction": "construction.j2",
             "site": "site.j2", "water_quality": "water_quality.j2", "method": "method.j2", "method_after": "method_after.j2",
             "system_interference": "system_interference.j2", "pumping_level": "pumping_level.j2",
             "summary": "summary_feasibility.j2" if feas else "summary.j2"}
    if ctx["unc"]:
        names["uncertainty"] = "uncertainty.j2"
    for name, fname in names.items():
        if name == "system_interference" and not ctx["si"]:
            continue
        sections[name] = env.from_string(_template(fname)).render(**ctx)
    for g in ctx["groups"]:
        sections[f"group_{g['key']}"] = env.from_string(_template("scenario_group.j2")).render(g=g, tab={"summary": ctx["tab"][f"summary_{g['key']}"], "edges": ctx["tab"][f"edges_{g['key']}"], "impacts": ctx["tab"][f"impacts_{g['key']}"]}, **{k: v for k, v in ctx.items() if k != "tab"})
    static_general = _static("gulf_coast_general.md")
    refs = load_reference("references")
    extra_allowed = set()
    for r in refs.values():
        extra_allowed |= numbers_in(r)
    extra_allowed |= numbers_in(static_general)
    lint = lint_sections(sections, ctx, extra_allowed)
    if strict_lint and not lint["ok"]:
        raise LintError(f"narrative contains numbers not present in the computed context: {lint['problems']}")
    # The same set the lint judges against, carried out with the artifacts so the review sheet can warn a reviewer
    # about a number the build would later reject, instead of letting them find out from a failed build.
    allowed_numbers = sorted(allowed_number_set(ctx, extra_allowed))

    intake, review = project.intake, project.review
    build_dir = project.build_dir
    eq = render_equations(build_dir / "figures")
    doc = DocBuilder(_letterhead(project), banner=ctx["meta"]["banner"],
                     footer_text=f"{intake.applicant.system_name or intake.applicant.name} - Hydrogeological Report (Rev. {ctx['meta']['revision']})")
    figs = ctx["figures"]
    fn, tn = ctx["fignum"], ctx["tabnum"]

    # ---- letter block
    doc.para(ctx["meta"]["date"], space_after=10)
    addr = ctx["district"]["addressee"] or {}
    for line in [addr.get("name"), addr.get("organization")] + list(addr.get("address_lines", [])):
        if line:
            doc.para(line, space_after=0)
    doc.para("", space_after=6)
    doc.para(f"RE: {intake.report.title}", bold=True, space_after=10)
    doc.para(intake.report.salutation or "Dear " + (addr.get("name") or "General Manager") + ":", space_after=8)
    doc.paragraphs(sections["intro"])
    doc.figure(fn["location"], figs["location"]["caption"], figs["location"]["path"], 6.0)

    # ---- 1 spacing
    doc.heading("1. Well Spacing" if not feas else "1. Wells and Surface Water in the Vicinity", 1)
    doc.paragraphs(sections["spacing"])
    doc.figure(fn["wells"], figs["wells"]["caption"], figs["wells"]["path"], 6.0)
    doc.figure(fn["property"], figs["property"]["caption"], figs["property"]["path"], 6.0)
    doc.landscape()
    doc.table(tn["nearby"], f"Registered and permitted wells within the {ctx['radii']['search_radius_text']} search radius of the proposed well",
              ctx["nearby"]["header"], ctx["nearby"]["rows"], font_pt=7,
              col_widths_in=[0.4, 0.85, 0.85, 1.5, 1.5, 0.55, 1.1, 0.7, 0.75, 0.65, 0.7, 0.65],
              note="ft = feet; bgl = below ground level; N/A = not available in the District record. * Aquifer inferred from completion depth. Distances measured from the nearest proposed well.")
    doc.portrait()

    # ---- 2 construction
    doc.heading("2. Well Construction Details", 1)
    doc.paragraphs(sections["construction"])
    doc.table(tn["construction"], "Anticipated well construction summary",
              ["Well", "Coordinates", "Elev. (ft MSL)", "Est. depth (ft bgl)", "Est. static water level (ft bgl)", "Borehole (dia.; ft bgl)", "Casing (dia.; material; ft bgl)", "Screen (dia.; material; ft bgl)", "Cemented interval (ft bgl)", "Filter pack (ft bgl)", "Aquifer"],
              [[w["label"], w["coords"], w["elev"], w["depth"], w["swl"], w["borehole"], w["casing"], w["screen"], w["cement"], w["filter_pack"], w["aquifer"]] for w in ctx["proposed"]["wells"]],
              font_pt=7, note="ft = feet; bgl = below ground level; MSL = mean sea level; NA = not applicable.")
    for w in intake.proposed_wells:
        doc.figure(fn[f"schematic_{w.id}"], figs[f"schematic_{w.id}"]["caption"], figs[f"schematic_{w.id}"]["path"], 5.6)

    # ---- 3 general hydrogeology
    doc.heading("3. General Hydrogeology", 1)
    doc.paragraphs(static_general)
    doc.figure(fn["strat"], figs["strat"]["caption"], figs["strat"]["path"], 6.0)

    # ---- 4 site-specific
    doc.heading("4. Site-Specific Hydrogeology", 1)
    doc.paragraphs(sections["site"])
    doc.table(tn["parameters"], "Aquifer parameters adopted for the interference simulations", ctx["parameters"]["header"], ctx["parameters"]["rows"], font_pt=8,
              note="** Hydraulic conductivity derived as transmissivity divided by aquifer thickness. GAM = TWDB groundwater availability model.")
    for k in sorted((k for k in fn if k.startswith("gam_")), key=lambda k: fn[k]):
        doc.figure(fn[k], figs[k]["caption"], figs[k]["path"], 5.8)

    # ---- 5 water quality
    doc.heading("5. Water Quality", 1)
    doc.paragraphs(sections["water_quality"])
    for k in ("wq_tds", "wq_fe", "wq_as", "wq_ra_combined"):
        if k in fn:
            doc.figure(fn[k], figs[k]["caption"], figs[k]["path"], 5.8)
    if ctx["wq"]["available"]:
        doc.table(tn["wq_radionuclides"], "Summary of radionuclide results", ctx["wq"]["radionuclide_header"], ctx["wq"]["radionuclide_rows"], font_pt=8,
                  red_cells=ctx["wq"]["radionuclide_red"], note="Values in red exceed the TCEQ MCL. ND = not detected; NA = not analyzed.")
        doc.landscape()
        doc.table(tn["wq_panel"], "Summary of the most recent water-quality sample from the representative well (units mg/L except pH)", ctx["wq"]["panel_header"], ctx["wq"]["panel_rows"], font_pt=7,
                  red_cells=ctx["wq"]["panel_red"], note="Values in red exceed the TCEQ MCL, SCL or action level (AL). ND = not detected; NA = not analyzed.")
        doc.portrait()

    # ---- 6 interference
    doc.heading("6. Interference Analysis" if not feas else "6. Production and Drawdown Analysis", 1)
    doc.heading("6.1 Methodology", 2)
    doc.paragraphs(sections["method"])
    # The equations shown must be the ones that were solved, or the methodology section contradicts
    # itself: Hantush-Jacob adds the leakage factor and replaces the exponential-integral well function.
    keys = ("hantush", "hantush_well_function", "u", "leakage_factor") if ctx["sol"]["is_leaky"] \
        else ("theis", "well_function", "u")
    for i, key in enumerate(keys, start=1):
        doc.equation(eq[key], f"Equation {i}")
    doc.paragraphs(sections["method_after"])
    sub = 2
    for g in ctx["groups"]:
        doc.heading(f"6.{sub} {g['heading']}", 2)
        sub += 1
        doc.paragraphs(sections[f"group_{g['key']}"])
        doc.table(tn[f"summary_{g['key']}"], f"Summary of distance-drawdown results: {g['heading'][0].lower() + g['heading'][1:]}", g["summary_header"], g["summary_rows"], font_pt=8)
        doc.table(tn[f"edges_{g['key']}"], f"Distance to the outer edge of the cone of depression: {g['heading'][0].lower() + g['heading'][1:]}", g["edge_header"], g["edge_rows"], font_pt=8,
                  note="Distances measured from the pumping center along the direction of greatest extent.")
        for s in g_scenarios(project, g["key"]):
            k = f"dd_{s['key']}_{g['aquifer']}"
            if k in fn:
                doc.figure(fn[k], figs[k]["caption"], figs[k]["path"], 6.0)
        doc.landscape()
        doc.table(tn[f"impacts_{g['key']}"], f"Estimated drawdown at registered and permitted wells within the search radius: {g['heading'][0].lower() + g['heading'][1:]}",
                  g["impacts_header"], g["impacts_rows"], font_pt=7, note=g["impacts_note"],
                  col_widths_in=[0.4, 0.85, 0.85, 1.6, 0.6, 1.2, 0.75, 0.75, 0.65] + [0.85] * (len(g["impacts_header"]) - 9))
        doc.portrait()
    if ctx["si"]:
        doc.heading(f"6.{sub} Interference among system wells", 2)
        sub += 1
        doc.paragraphs(sections["system_interference"])
        doc.table(tn["matrix_system"], f"Drawdown induced at each system well by each system well, {ctx['si']['duration_label']} maximum-production case (ft)",
                  ctx["si"]["header"], ctx["si"]["rows"], font_pt=8)
    if "distance_drawdown" in fn:
        doc.figure(fn["distance_drawdown"], figs["distance_drawdown"]["caption"], figs["distance_drawdown"]["path"], 6.0)
    if ctx["pl"]:
        doc.heading(f"6.{sub} Pumping-level check", 2)
        doc.paragraphs(sections["pumping_level"])

    # ---- 7 summary
    doc.heading("7. Summary and Professional Opinion", 1)
    doc.paragraphs(sections["summary"])
    doc.para("Respectfully submitted,", space_after=30)
    r = review.reviewer
    doc.para(r.name or "[SEALING PROFESSIONAL NAME], [P.G./P.E.]", bold=True, space_after=0)
    doc.para(r.title or "[Title]", space_after=0)
    doc.para(r.firm or _letterhead(project)["firm"], space_after=8)
    doc.para(f"The seal appearing on this document was authorized by {r.name or '[NAME]'}, {r.license_type or '[P.G./P.E.]'} License No. {r.license_no or '[____]'} on {r.authorization_date or '[DATE]'}.", italic=True, size=9)
    doc.para(f"{r.firm or _letterhead(project)['firm']} - TBPG Firm Registration No. {r.firm_registration_no or '[____]'}", italic=True, size=9)

    # ---- references
    doc.page_break()
    doc.heading("References", 1)
    for key in sorted(refs, key=lambda k: refs[k]):
        doc.para(refs[key], size=9, space_after=4)

    # ---- appendices
    doc.page_break()
    doc.heading("Appendix A. Guideline cross-reference", 1)
    cl = A.get("checklist") or {"items": []}
    doc.table("A-1", "Cross-reference of District guideline items to report sections", ["Guideline item", "Requirement", "Status", "Where addressed / note"],
              [[i["id"], i["text"], i["status_label"], i["where"]] for i in cl["items"]], font_pt=7.5)
    doc.heading("Appendix B. Data sources and provenance", 1)
    prov = A["provenance"]
    doc.para(f"Report generated with hydrostudy version {prov['hydrostudy_version']} on {prov['generated_at']}. District rules: {prov['district_rules']['version']} (verified {prov['district_rules']['verified_on']}). TCEQ limits: {prov['tceq_limits']['version']}.", size=9)
    basis = spacing_basis_sentence(prov["district_rules"])
    if basis:
        doc.para(basis, size=9)
    doc.table("B-1", "Input data files", ["Key", "File", "Source", "Retrieved", "Rows", "SHA-256 (first 12)"],
              [[f["key"], Path(f["path"]).name, f["source"], f["retrieved"], f["rows"] if f["rows"] is not None else "", (f["sha256"] or "")[:12]] for f in prov["files"]], font_pt=7.5)
    doc.heading("Appendix C. Verification of the analytical solution", 1)
    doc.para("The drawdown routine was checked against a District-accepted 2023 submittal that reported Theis distance-drawdown results for a 385-gpm Evangeline Aquifer well with a transmissivity of 1,023 ft2/day and a storativity of 3.36 x 10^-4.", size=9)
    if ctx["sol"]["is_leaky"]:
        # The benchmark below exercises the Theis routine. Saying so plainly is the difference between a
        # verification appendix and a misleading one.
        doc.para("The results in this report were computed with the Hantush-Jacob leaky-aquifer solution, "
                 "which the benchmark below does not exercise. That solution was verified separately "
                 "against its two analytical limits: it reproduces the Theis well function when the "
                 "leakance is zero, and the Hantush-Jacob steady-state expression as pumping time "
                 "becomes large. The benchmark is retained because both solutions share the same "
                 "superposition, unit conversion and geometry code.", size=9)
    rows = []
    for r_ft, t_days, reported in BENCHMARK["cases"]:
        calc = float(theis_drawdown(BENCHMARK["q_gpm"], BENCHMARK["t_ft2d"], BENCHMARK["s"], r_ft, t_days))
        rows.append([f"{r_ft:g}", f"{t_days:g}", fmt_ft(reported), fmt_ft(calc), fmt_ft(calc - reported)])
    doc.table("C-1", "Benchmark comparison", ["Distance (ft)", "Time (days)", "Reported drawdown (ft)", "Computed drawdown (ft)", "Difference (ft)"], rows, font_pt=8)
    if ctx["unc"]:
        append_uncertainty_appendix(doc, ctx, sections["uncertainty"], figs)
    placeholders = []
    for name, text in sections.items():
        placeholders += [(name, m) for m in PLACEHOLDER_RE.findall(text)]
    if review.reviewer.status != "final":
        doc.heading(f"Appendix {'E' if ctx['unc'] else 'D'}. Review log (draft only; removed from the final report)", 1)
        doc.para("Items requiring the sealing professional's input, and automated flags:", size=9)
        for sec, ph in placeholders:
            doc.bullet(f"{sec}: {ph}")
        for f in A["flags"]:
            doc.bullet(f"[{f['level']}] {f['code']}: {f['text']}")

    status = review.reviewer.status
    out_docx = build_dir / f"report_v{intake.report.revision.number}_{status}.docx"
    if out_docx.exists() and status == "final":
        raise FileExistsError(f"{out_docx} exists; bump report.revision.number instead of overwriting a final document")
    doc.save(out_docx)
    out_pdf = convert_to_pdf(out_docx) if pdf else None
    return {"docx": str(out_docx), "pdf": str(out_pdf) if out_pdf else None, "placeholders": placeholders,
            "lint": lint, "allowed_numbers": allowed_numbers, "figures": len(fn), "tables": len(tn),
            "sections": list(sections.keys())}


def append_uncertainty_appendix(doc, ctx, narrative: str, figs: dict):
    """Appendix D, shared by the pre- and post-drilling reports so the two cannot drift apart.

    The appendix is labelled D-n rather than taking numbers in the body's sequence: it is supporting
    material the applicant opted into, and inserting it into the figure numbering would renumber every
    figure in a report that had been reviewed without it.
    """
    u = ctx["unc"]
    doc.page_break()
    doc.heading("Appendix D. Parameter uncertainty", 1)
    doc.paragraphs(narrative)
    doc.table("D-1", f"Aquifer parameters as declared for the {u['aquifer']} Aquifer",
              u["param_header"], u["param_rows"], font_pt=8,
              note="Blank cells indicate a parameter held at the value adopted in the report rather than sampled.")
    doc.landscape()
    doc.table("D-2", f"Drawdown as a distribution: {u['scenario_title']}",
              u["receptor_header"], u["receptor_rows"], font_pt=7,
              note=f"ft = feet. The percentile column states where the drawdown reported in "
                   f"{u['section_ref']} falls in this distribution; it is not a correction to that value.")
    doc.portrait()
    if "uncertainty" in figs:
        doc.figure("D-1", figs["uncertainty"]["caption"], figs["uncertainty"]["path"], 6.5)


def g_scenarios(project, gkey):
    for g in scenario_groups(project):
        if g["key"] == gkey:
            return g["scenarios"]
    return []
