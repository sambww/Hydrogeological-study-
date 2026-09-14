"""hydrostudy command line: new | import-intake | validate | run | render | checklist | doctor"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def cmd_new(args):
    dst = Path(args.project_dir)
    if dst.exists() and any(dst.iterdir()):
        print(f"refusing to scaffold into non-empty directory {dst}", file=sys.stderr)
        return 2
    src = Path(__file__).resolve().parents[1] / "examples" / "black_oak_well_2"
    if not src.exists():
        print("example template not found; create intake.yaml by hand (see docs/WORKFLOW.md)", file=sys.stderr)
        return 2
    (dst / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(src / "intake.yaml", dst / "intake.yaml")
    shutil.copy(src / "review.yaml", dst / "review.yaml")
    shutil.copy(src / "data" / "manifest.yaml", dst / "data" / "manifest.yaml")
    (dst / "data" / "district_wells.csv").write_text("registration_no,permit_no,owner,address,city,total_depth_ft,screen_intervals,aquifer,status,lat,lon\n", encoding="utf-8")
    (dst / "data" / "water_quality_samples.csv").write_text("well_id,well_name,source,sample_date,lat,lon,depth_ft,aquifer,constituent,value,units,qualifier\n", encoding="utf-8")
    print(f"Scaffolded {dst}. Edit intake.yaml, review.yaml and the files under data/, then run: hydrostudy run {dst}")
    return 0


def cmd_import_intake(args):
    from pydantic import ValidationError

    from hydrostudy.intake_import import load_payload, write_intake
    try:
        payload = load_payload(args.payload)
    except (OSError, ValueError) as e:
        print(f"cannot read submission: {e}", file=sys.stderr)
        return 2
    try:
        target = write_intake(args.project_dir, payload, force=args.force)
    except FileExistsError as e:
        print(f"{e}. Re-run with --force to overwrite.", file=sys.stderr)
        return 2
    except ValidationError as e:
        print("submission is not a valid intake:")
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            print(f"  - {loc}: {err['msg']}")
        return 1
    print(f"Wrote {target}. Next: fill data/manifest.yaml sources, then run: hydrostudy run {args.project_dir}")
    return 0


def cmd_validate(args):
    from pydantic import ValidationError

    from hydrostudy.schema.loaders import load_intake, load_review
    d = Path(args.project_dir)
    try:
        intake = load_intake(d / "intake.yaml")
        load_review(d / "review.yaml")
    except ValidationError as e:
        print("intake.yaml is invalid:")
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            print(f"  - {loc}: {err['msg']}")
        return 1
    except FileNotFoundError as e:
        print(f"missing file: {e}")
        return 1
    print(f"OK: {len(intake.proposed_wells)} proposed well(s), {len(intake.existing_wells)} existing well(s), "
          f"system rate {intake.system_rate_gpm:,.0f} gpm, annual volume {intake.permit.annual_volume_gal:,.0f} gal")
    return 0


def _print_summary(project, result, checklist, args_no_pdf=False):
    an = project.artifacts["analysis"]
    print(f"\nReport: {result['docx']}")
    if result.get("pdf"):
        print(f"PDF:    {result['pdf']}")
    elif not args_no_pdf:
        from hydrostudy.report.pdf import pdf_status_message
        print(pdf_status_message())
    print(f"Figures: {result['figures']}  Tables: {result['tables']}  Lint: {'OK' if result['lint']['ok'] else 'PROBLEMS'}")
    print("\nScenario results (drawdown at pumped wells, ft):")
    for sc in an["scenarios"]:
        for res in sc["results_by_aquifer"].values():
            vals = ", ".join(f"{p['id']}={p['total_ft']:.1f}" for p in res["pumped_wells"])
            e1 = next((e for e in res["cone_edges"] if abs(e["threshold_ft"] - 1) < 1e-6), None)
            edge = f"; 1-ft edge {e1['max_ft']:,.0f} ft" if e1 else ""
            print(f"  {sc['title']:<45} {vals}{edge}")
    print("\nGuideline checklist:", ", ".join(f"{k}={v}" for k, v in checklist["counts"].items()) or "no checklist configured for this district")
    for i in checklist["items"]:
        if i["status"] != "satisfied":
            print(f"  - {i['id']}: {i['status_label']} ({i['where']})")
    ph = result.get("placeholders", [])
    if ph:
        print(f"\nPlaceholders for the sealing professional ({len(ph)}):")
        for sec, p in ph:
            print(f"  - [{sec}] {p}")
    flags = [f for f in project.artifacts["flags"] if f["level"] in ("warn", "review")]
    if flags:
        print(f"\nFlags ({len(flags)}):")
        for f in flags:
            print(f"  - [{f['level']}] {f['code']}: {f['text']}")


def cmd_run(args):
    from hydrostudy.pipeline import Project
    p = Project(args.project_dir)
    p.run_analysis()
    p.run_figures()
    cl = p.run_checklist()
    p.artifacts["checklist"] = cl
    from hydrostudy.report.assemble import LintError
    try:
        result = p.run_report(pdf=not args.no_pdf, strict_lint=not args.no_strict_lint)
    except LintError as e:
        print(f"LINT FAILURE: {e}", file=sys.stderr)
        return 3
    _print_summary(p, result, cl, args.no_pdf)
    return 0


def cmd_render(args):
    return cmd_run(args)


def cmd_checklist(args):
    from hydrostudy.pipeline import Project
    p = Project(args.project_dir)
    p.run_analysis()
    p.run_figures()
    cl = p.run_checklist()
    print(json.dumps({"counts": cl["counts"], "items": [(i["id"], i["status"]) for i in cl["items"]]}, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hydrostudy", description="Draft hydrogeological report generator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new", help="scaffold a new project folder")
    s.add_argument("project_dir")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("import-intake", help="write intake.yaml from a web intake form submission (JSON)")
    s.add_argument("project_dir")
    s.add_argument("payload", help="path to the submission JSON saved from the form or read out of the artifact database")
    s.add_argument("--force", action="store_true", help="overwrite an existing intake.yaml")
    s.set_defaults(fn=cmd_import_intake)
    s = sub.add_parser("validate", help="validate intake.yaml and review.yaml")
    s.add_argument("project_dir")
    s.set_defaults(fn=cmd_validate)
    for name, fn in (("run", cmd_run), ("render", cmd_render)):
        s = sub.add_parser(name, help="run analysis, figures, checklist and report")
        s.add_argument("project_dir")
        s.add_argument("--no-pdf", action="store_true")
        s.add_argument("--no-strict-lint", action="store_true", help="write the report even if the narrative lint finds unknown numbers")
        s.set_defaults(fn=fn)
    s = sub.add_parser("doctor", help="check the environment (packages, LibreOffice, optional extras, data hosts)")
    s.add_argument("--network", action="store_true", help="also test reachability of the public data hosts")
    s.set_defaults(fn=lambda a: __import__("hydrostudy.doctor", fromlist=["main"]).main(a.network))
    s = sub.add_parser("checklist", help="print the guideline checklist")
    s.add_argument("project_dir")
    s.set_defaults(fn=cmd_checklist)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
