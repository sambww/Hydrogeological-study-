"""Assemble the post-drilling (Section III) report."""

from __future__ import annotations

from pathlib import Path

from hydrostudy.districts.status import spacing_basis_sentence
from hydrostudy.reference import load_reference
from hydrostudy.report.assemble import LintError, _env, _letterhead, _template
from hydrostudy.report.context import scenario_groups
from hydrostudy.report.context_post import build_post_context
from hydrostudy.report.docx_builder import PLACEHOLDER_RE, DocBuilder
from hydrostudy.report.equations import render_equations
from hydrostudy.report.lint import allowed_number_set, lint_sections, numbers_in
from hydrostudy.report.pdf import convert_to_pdf


def build_post_report(project, pdf: bool = True, strict_lint: bool = True) -> dict:
    A = project.artifacts
    ctx = build_post_context(project)
    env = _env()
    sections = {}
    for name in ("post_intro", "post_construction", "post_logs", "post_testing", "post_wq", "post_summary"):
        sections[name] = env.from_string(_template(f"{name}.j2")).render(**ctx)
    if ctx["ab"]["rerun"]:
        sections["post_interference"] = env.from_string(_template("post_interference.j2")).render(**ctx)
        sections["method"] = env.from_string(_template("method.j2")).render(**ctx)
        sections["method_after"] = env.from_string(_template("method_after.j2")).render(**ctx)
        for g in ctx["groups"]:
            sections[f"group_{g['key']}"] = env.from_string(_template("scenario_group.j2")).render(
                g=g, tab={"summary": ctx["tab"][f"summary_{g['key']}"], "edges": ctx["tab"][f"edges_{g['key']}"], "impacts": ctx["tab"][f"impacts_{g['key']}"]},
                **{k: v for k, v in ctx.items() if k != "tab"})
    refs = load_reference("references")
    extra = set()
    for r in refs.values():
        extra |= numbers_in(r)
    lint = lint_sections(sections, ctx, extra)
    if strict_lint and not lint["ok"]:
        raise LintError(f"narrative contains numbers not present in the computed context: {lint['problems']}")
    # Carried out with the artifacts for the review sheet, exactly as the pre-drilling assembler does. Without it the
    # sheet loads an empty allowed set and flags every figure a reviewer types on a post-drilling report.
    allowed_numbers = sorted(allowed_number_set(ctx, extra))

    intake, review = project.intake, project.review
    figs, fn, tn = ctx["figures"], ctx["fignum"], ctx["tabnum"]
    ab = ctx["ab"]
    doc = DocBuilder(_letterhead(project), banner=ctx["meta"]["banner"],
                     footer_text=f"{intake.applicant.system_name or intake.applicant.name} - Post-Drilling Report (Rev. {ctx['meta']['revision']})")
    doc.para(ctx["meta"]["date"], space_after=10)
    addr = ctx["district"]["addressee"] or {}
    for line in [addr.get("name"), addr.get("organization")] + list(addr.get("address_lines", [])):
        if line:
            doc.para(line, space_after=0)
    doc.para("", space_after=6)
    doc.para(f"RE: {intake.report.title}", bold=True, space_after=10)
    doc.para(intake.report.salutation or "Dear " + (addr.get("name") or "General Manager") + ":", space_after=8)
    doc.paragraphs(sections["post_intro"])

    doc.heading("1. As-Built Well Construction", 1)
    doc.paragraphs(sections["post_construction"])
    doc.table(tn["asbuilt"], f"Aquifer conditions and well and pump parameters, {ab['well_label']} (Guidelines III.4)", ["Parameter", "Value"], ab["asbuilt_rows"], font_pt=9, col_widths_in=[3.0, 3.3])
    doc.figure(fn["schematic_asbuilt"], figs["schematic_asbuilt"]["caption"], figs["schematic_asbuilt"]["path"], 5.6)

    doc.heading("2. Geophysical Logs", 1)
    doc.paragraphs(sections["post_logs"])
    doc.table(tn["logs"], "Geophysical log inventory", ["Log", "Curves", "Interval (ft bgl)", "Date", "Hole condition", "Digital file"], ab["log_rows"], font_pt=8)

    doc.heading("3. Aquifer Testing", 1)
    doc.paragraphs(sections["post_testing"])
    doc.landscape()
    doc.table(tn["tests"], "Aquifer-test summary and derived parameters", ab["test_header"], ab["test_rows"], font_pt=7.5,
              note="N/A = not applicable to the test type. Storativity is not determinable from a single-well test and was held at the pre-drilling value.")
    doc.portrait()
    for t in A["as_built"]["tests"]:
        for k in (f"cj_{t['id']}", f"theis_{t['id']}", f"recovery_{t['id']}", f"step_{t['id']}"):
            if k in fn:
                doc.figure(fn[k], figs[k]["caption"], figs[k]["path"], 6.0)

    doc.heading("4. Water Quality", 1)
    doc.paragraphs(sections["post_wq"])
    doc.table(tn["field"], "Field parameters measured during testing and sampling (Guidelines III.5)", ab["field_header"], ab["field_rows"], font_pt=8)
    for k in ("wq_tds", "wq_fe", "wq_as", "wq_ra_combined"):
        if k in fn:
            doc.figure(fn[k], figs[k]["caption"], figs[k]["path"], 5.6)
    if ctx["wq"]["available"]:
        doc.table(tn["wq_radionuclides"], "Radionuclide results", ctx["wq"]["radionuclide_header"], ctx["wq"]["radionuclide_rows"], font_pt=8,
                  red_cells=ctx["wq"]["radionuclide_red"], note="Values in red exceed the TCEQ MCL. ND = not detected; NA = not analyzed.")
        doc.landscape()
        doc.table(tn["wq_panel"], "Post-construction laboratory results (units mg/L except pH)", ctx["wq"]["panel_header"], ctx["wq"]["panel_rows"], font_pt=7,
                  red_cells=ctx["wq"]["panel_red"], note="Values in red exceed the TCEQ MCL, SCL or action level (AL). ND = not detected; NA = not analyzed.")
        doc.portrait()

    sec = 5
    if ab["rerun"]:
        doc.heading(f"{sec}. Updated Interference Analysis", 1)
        doc.paragraphs(sections["post_interference"])
        doc.table(tn["comparison"], "Simulated drawdown at the pumped wells: pre-drilling parameters versus as-built transmissivity", ab["comparison_header"], ab["comparison_rows"], font_pt=8)
        doc.heading(f"{sec}.1 Methodology", 2)
        doc.paragraphs(sections["method"])
        eq = render_equations(project.build_dir / "figures")
        # Same rule as the pre-drilling report: show the equations that were solved. The re-run uses
        # whatever solution the intake selected, so this cannot be hard-coded to Theis.
        keys = (("hantush", "hantush_well_function", "u", "leakage_factor") if ctx["sol"]["is_leaky"]
                else ("theis", "well_function", "u"))
        for i, key in enumerate(keys, start=1):
            doc.equation(eq[key], f"Equation {i}")
        doc.paragraphs(sections["method_after"])
        sub = 2
        for g in ctx["groups"]:
            doc.heading(f"{sec}.{sub} {g['heading']}", 2)
            sub += 1
            doc.paragraphs(sections[f"group_{g['key']}"])
            doc.table(tn[f"summary_{g['key']}"], f"Summary of distance-drawdown results: {g['heading'][0].lower() + g['heading'][1:]}", g["summary_header"], g["summary_rows"], font_pt=8)
            doc.table(tn[f"edges_{g['key']}"], f"Distance to the outer edge of the cone of depression: {g['heading'][0].lower() + g['heading'][1:]}", g["edge_header"], g["edge_rows"], font_pt=8)
            for s in [x for gg in scenario_groups(project) if gg["key"] == g["key"] for x in gg["scenarios"]]:
                k = f"dd_{s['key']}_{g['aquifer']}"
                if k in fn:
                    doc.figure(fn[k], figs[k]["caption"], figs[k]["path"], 6.0)
            doc.landscape()
            doc.table(tn[f"impacts_{g['key']}"], f"Estimated drawdown at registered and permitted wells within the search radius: {g['heading'][0].lower() + g['heading'][1:]}",
                      g["impacts_header"], g["impacts_rows"], font_pt=7, note=g["impacts_note"],
                      col_widths_in=[0.4, 0.85, 0.85, 1.6, 0.6, 1.2, 0.75, 0.75, 0.65] + [0.85] * (len(g["impacts_header"]) - 9))
            doc.portrait()
        if ctx["si"]:
            doc.table(tn["matrix_system"], f"Drawdown induced at each system well by each system well, {ctx['si']['duration_label']} case (ft)", ctx["si"]["header"], ctx["si"]["rows"], font_pt=8)
        if "distance_drawdown" in fn:
            doc.figure(fn["distance_drawdown"], figs["distance_drawdown"]["caption"], figs["distance_drawdown"]["path"], 6.0)
        sec += 1

    doc.heading(f"{sec}. Summary and Professional Opinion", 1)
    doc.paragraphs(sections["post_summary"])
    doc.para("Respectfully submitted,", space_after=30)
    r = review.reviewer
    doc.para(r.name or "[SEALING PROFESSIONAL NAME], [P.G./P.E.]", bold=True, space_after=0)
    doc.para(r.title or "[Title]", space_after=0)
    doc.para(r.firm or _letterhead(project)["firm"], space_after=8)
    doc.para(f"The seal appearing on this document was authorized by {r.name or '[NAME]'}, {r.license_type or '[P.G./P.E.]'} License No. {r.license_no or '[____]'} on {r.authorization_date or '[DATE]'}.", italic=True, size=9)
    doc.para(f"{r.firm or _letterhead(project)['firm']} - TBPG Firm Registration No. {r.firm_registration_no or '[____]'}", italic=True, size=9)

    doc.page_break()
    doc.heading("References", 1)
    for key in sorted(refs, key=lambda k: refs[k]):
        doc.para(refs[key], size=9, space_after=4)

    doc.page_break()
    doc.heading("Appendix A. Guideline Section III cross-reference", 1)
    cl = A.get("checklist") or {"items": []}
    doc.table("A-1", "Cross-reference of Section III items to report sections", ["Guideline item", "Requirement", "Status", "Where addressed / note"],
              [[i["id"], i["text"], i["status_label"], i["where"]] for i in cl["items"]], font_pt=7.5)
    doc.heading("Appendix B. Data sources and provenance", 1)
    prov = A["provenance"]
    doc.para(f"Report generated with hydrostudy version {prov['hydrostudy_version']} on {prov['generated_at']}. District rules: {prov['district_rules']['version']} (verified {prov['district_rules']['verified_on']}). TCEQ limits: {prov['tceq_limits']['version']}.", size=9)
    basis = spacing_basis_sentence(prov["district_rules"])
    if basis:
        doc.para(basis, size=9)
    doc.table("B-1", "Input data files", ["Key", "File", "Source", "Retrieved", "Rows", "SHA-256 (first 12)"],
              [[f["key"], Path(f["path"]).name, f["source"], f["retrieved"], f["rows"] if f["rows"] is not None else "", (f["sha256"] or "")[:12]] for f in prov["files"]], font_pt=7.5)
    doc.heading("Appendix C. Aquifer-test data", 1)
    for i, dt in enumerate(ab["data_tables"], 1):
        doc.table(f"C-{i}", f"Recorded water levels, test {dt['id']}", ["Elapsed time (min)", "Drawdown (ft)", "Rate (gpm)", "Phase"], dt["rows"], font_pt=7.5, col_widths_in=[1.4, 1.2, 1.0, 1.0])
    placeholders = [(n, m) for n, text in sections.items() for m in PLACEHOLDER_RE.findall(text)]
    if review.reviewer.status != "final":
        doc.heading("Appendix D. Review log (draft only; removed from the final report)", 1)
        for sec_name, ph in placeholders:
            doc.bullet(f"{sec_name}: {ph}")
        for f in A["flags"]:
            doc.bullet(f"[{f['level']}] {f['code']}: {f['text']}")
    status = review.reviewer.status
    out_docx = project.build_dir / f"report_v{intake.report.revision.number}_{status}.docx"
    if out_docx.exists() and status == "final":
        raise FileExistsError(f"{out_docx} exists; bump report.revision.number instead of overwriting a final document")
    doc.save(out_docx)
    out_pdf = convert_to_pdf(out_docx) if pdf else None
    return {"docx": str(out_docx), "pdf": str(out_pdf) if out_pdf else None, "placeholders": placeholders,
            "lint": lint, "allowed_numbers": allowed_numbers, "figures": len(fn), "tables": len(tn),
            "sections": list(sections.keys())}
