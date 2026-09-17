"""hydrostudy command line: new | import-intake | validate | run | render | siting | wellfield | checklist | doctor"""

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


def cmd_import_review(args):
    from pydantic import ValidationError

    from hydrostudy.review_import import load_payload, write_review
    try:
        payload = load_payload(args.payload)
    except (OSError, ValueError) as e:
        print(f"cannot read submission: {e}", file=sys.stderr)
        return 2
    try:
        target = write_review(args.project_dir, payload, force=args.force)
    except FileExistsError as e:
        print(f"{e}. Re-run with --force to overwrite.", file=sys.stderr)
        return 2
    except ValidationError as e:
        print("submission is not a valid review:")
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            print(f"  - {loc}: {err['msg']}")
        return 1
    print(f"Wrote {target}. Next: hydrostudy run {args.project_dir}")
    return 0


def cmd_review_sheet(args):
    from hydrostudy.review_sheet import SheetNotReady, render_sheet
    try:
        target = render_sheet(args.project_dir, args.out)
    except SheetNotReady as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"Wrote {target}. Publish it for the reviewer, then import their submission with: "
          f"hydrostudy import-review {args.project_dir} <submission>.json")
    return 0


def cmd_siting(args):
    from hydrostudy.analysis.siting import SitingNotPossible, SitingRequest, analyze_siting
    from hydrostudy.pipeline import Project
    p = Project(args.project_dir)
    p.run_analysis()
    req = SitingRequest(well_id=args.well, target_rate_gpm=args.rate, grid_spacing_ft=args.grid_ft,
                        setback_ft=args.setback_ft, max_interference_ft=args.max_interference_ft,
                        available_drawdown_ft=args.available_drawdown_ft, top_n=args.top,
                        min_separation_ft=args.min_separation_ft)
    try:
        out = analyze_siting(p, req)
    except SitingNotPossible as e:
        print(f"cannot run a siting search: {e}", file=sys.stderr)
        return 2
    from hydrostudy.pipeline import dump_json
    dump_json(out, p.build_dir / "siting.json")
    if not args.no_figure:
        from hydrostudy.figures import siting_map
        fig_dir = p.build_dir / "figures"
        fig_dir.mkdir(parents=True, exist_ok=True)
        out["figure"] = siting_map.render(p, out, fig_dir / f"fig_siting_{out['well_id']}.png")
        dump_json(out, p.build_dir / "siting.json")
    _print_siting(out, p.build_dir / "siting.json")
    return 0


def _binding_detail(out, c):
    """Why this location is limited, in the terms of the limit that actually bound it."""
    which = c["binding_constraint"]
    if which == "spacing":
        return (f" ({c['nearest_counting_well']['distance_ft']:,.0f} ft to map ID "
                f"{c['nearest_counting_well']['map_id']}, and {out['ft_per_gpm']:g} ft/gpm required)")
    if which == "interference":
        return (f" ({out['max_interference_ft']:,.2f}-ft cap reached at a neighbouring well over "
                f"{c['days_at_max_rate']:,.1f} days)")
    if which == "available drawdown":
        return (f" ({c['self_drawdown_at_max_rate_ft']:,.1f} ft of the {out['available_drawdown_ft']:,.0f} ft "
                f"available, over {c['days_at_max_rate']:,.1f} days)")
    return ""


def _print_siting(out, json_path):
    from hydrostudy.geo.crs import format_dms
    g = out["grid"]
    print(f"\nSiting {out['well_label']} ({out['aquifer']}) at {out['target_rate_gpm']:,.0f} gpm")
    print(f"  Spacing rule:  {out['ft_per_gpm']:g} ft/gpm -> {out['required_spacing_ft']:,.0f} ft required "
          f"({out['rule_reference']}{'; PROVISIONAL' if out['provisional'] else ''})")
    print(f"  Simulation:    {out['duration_label']} at a system rate of {out['system_rate_gpm']:,.0f} gpm, "
          f"T={out['t_ft2d']:,.0f} ft2/day, S={out['s']:.2e}")
    print(f"  Constraints:   {', '.join(out['constraints_applied'])}")
    print(f"  Envelope:      {g['compliant_area_acres']:,.1f} of {g['searched_area_acres']:,.1f} searched acres "
          f"({g['compliant']} of {g['candidates']} points at {g['spacing_ft']:,.0f}-ft spacing) on a "
          f"{g['tract_area_acres']:,.1f}-acre tract")
    if not out["feasible"]:
        h = out["best_by_headroom"]
        print(f"\n  NO location on the tract supports {out['target_rate_gpm']:,.0f} gpm. The best point tops out at "
              f"{h['max_rate_gpm']:,.0f} gpm, limited by {h['binding_constraint']}"
              f"{_binding_detail(out, h)}.")
        print(f"     {format_dms(h['lat'], 'lat')}  {format_dms(h['lon'], 'lon')}, "
              f"{h['move_from_intake_ft']:,.0f} ft from the intake location")
    else:
        print("\n  Ranked locations (least drawdown at someone else's well first):")
        for c in out["best"]:
            print(f"   {c['rank']}. {format_dms(c['lat'], 'lat')}  {format_dms(c['lon'], 'lon')}"
                  f"   max {c['max_rate_gpm']:,.0f} gpm, limited by {c['binding_constraint']}"
                  f"{_binding_detail(out, c)}")
            nb = c["worst_neighbour"]
            if nb:
                print(f"      worst impact {nb['drawdown_at_target_ft']:.2f} ft at map ID {nb['map_id']} "
                      f"({nb['owner'] or 'owner not recorded'}, {nb['distance_ft']:,.0f} ft), of which "
                      f"{nb['drawdown_from_fixed_wells_ft']:.2f} ft is the existing system")
            print(f"      {c['self_drawdown_at_target_ft']:.1f} ft drawdown at the well, "
                  f"{c['boundary_distance_ft']:,.0f} ft to the property line, "
                  f"{c['move_from_intake_ft']:,.0f} ft from the intake location")
            if c["system_wells_inside_radius"]:
                ids = ", ".join(str(w["map_id"]) for w in c["system_wells_inside_radius"])
                print(f"      own system well(s) inside the spacing radius (flagged, not a conflict): map ID {ids}")
        h = out["best_by_headroom"]
        if h["max_rate_gpm"] > max(c["max_rate_gpm"] for c in out["best"]):
            print(f"\n  Most rate headroom is elsewhere: {h['max_rate_gpm']:,.0f} gpm at "
                  f"{format_dms(h['lat'], 'lat')}  {format_dms(h['lon'], 'lon')}, which puts "
                  f"{h['worst_neighbour']['drawdown_at_target_ft']:.2f} ft on map ID "
                  f"{h['worst_neighbour']['map_id']} at the target rate.")
    for n in out["notes"]:
        print(f"\n  Note: {n}")
    print(f"\nWrote {json_path}")
    if out.get("figure"):
        print(f"Figure: {out['figure']['path']}")


def cmd_wellfield(args):
    from hydrostudy.analysis.wellfield import FieldNotPossible, FieldRequest, design_field
    from hydrostudy.pipeline import Project, dump_json
    p = Project(args.project_dir)
    p.run_analysis()
    req = FieldRequest(target_rate_gpm=args.rate, max_wells=args.max_wells,
                       grid_spacing_ft=args.grid_ft, setback_ft=args.setback_ft,
                       min_well_rate_gpm=args.min_well_rate, max_well_rate_gpm=args.max_well_rate,
                       available_drawdown_ft=args.available_drawdown_ft,
                       max_interference_ft=args.max_interference_ft,
                       min_well_spacing_ft=args.min_well_spacing_ft, aquifer=args.aquifer,
                       spacing_safety_ft=args.spacing_safety_ft,
                       cost_per_well=args.cost_per_well, cost_per_ft=args.cost_per_ft,
                       well_depth_ft=args.well_depth_ft)
    try:
        out = design_field(p, req)
    except FieldNotPossible as e:
        print(f"cannot design a well field: {e}", file=sys.stderr)
        return 2
    dump_json(out, p.build_dir / "wellfield.json")
    if not args.no_figure:
        from hydrostudy.figures import wellfield_map
        fig_dir = p.build_dir / "figures"
        fig_dir.mkdir(parents=True, exist_ok=True)
        out["figure"] = wellfield_map.render(p, out, fig_dir / "fig_wellfield.png")
        dump_json(out, p.build_dir / "wellfield.json")
    _print_wellfield(out, p.build_dir / "wellfield.json")
    return 0


def _print_wellfield(out, json_path):
    from hydrostudy.geo.crs import format_dms
    rec = out["recommended"]
    print(f"\nWell field for {out['target_rate_gpm']:,.0f} gpm in the {out['aquifer']}")
    print(f"  Spacing rule:  {out['ft_per_gpm']:g} ft/gpm"
          f"{'; PROVISIONAL' if out['provisional'] else ''}")
    print(f"  Aquifer:       T={out['t_ft2d']:,.0f} ft2/day, S={out['s']:.2e}, "
          f"{out['solution']['citation']}")
    limits = [f"{out['min_well_rate_gpm']:,.0f} gpm minimum per well"]
    if out["max_well_rate_gpm"]:
        limits.append(f"{out['max_well_rate_gpm']:,.0f} gpm maximum per well")
    if out["available_drawdown_ft"]:
        limits.append(f"{out['available_drawdown_ft']:,.0f} ft available drawdown")
    if out["max_interference_ft"]:
        limits.append(f"{out['max_interference_ft']:,.2f} ft interference cap")
    if out["min_well_spacing_ft"]:
        limits.append(f"{out['min_well_spacing_ft']:,.0f} ft between new wells")
    if out["spacing_safety_ft"]:
        limits.append(f"{out['spacing_safety_ft']:,.0f} ft held back from every spacing limit")
    print(f"  Limits:        {'; '.join(limits)}")
    print(f"  Tract:         {out['grid']['tract_area_acres']:,.1f} acres, "
          f"{out['grid']['candidates']} candidate points at {out['grid']['spacing_ft']:,.0f} ft")
    if out["existing_system_rate_gpm"]:
        print(f"  Existing:      {out['existing_system_rate_gpm']:,.0f} gpm already permitted in the system")

    print("\n  Wells   Delivers    Worst neighbour   Deepest well   Meets demand")
    for o in out["options"]:
        nb = o["worst_neighbour"]
        chosen = " <-" if o is rec else ""
        print(f"    {o['wells_drilled']:>2}   {o['total_rate_gpm']:>7.1f} gpm   "
              f"{(nb['drawdown_ft'] if nb else 0):>10.1f} ft   {o['max_well_drawdown_ft']:>9.0f} ft   "
              f"{'yes' if o['meets_target'] else 'no':>12}{chosen}")

    if not rec["meets_target"]:
        print(f"\n  {out['target_rate_gpm']:,.0f} gpm is NOT achievable on this tract under these limits. "
              f"The best field delivers {rec['total_rate_gpm']:,.1f} gpm, "
              f"{rec['shortfall_gpm']:,.0f} gpm short.")
    print(f"\n  Recommended: {rec['wells_drilled']} well(s), {rec['total_rate_gpm']:,.1f} gpm over "
          f"{rec['duration_days']:,.1f} days")
    for w in rec["wells"]:
        print(f"   #{w['slot']}. {format_dms(w['lat'], 'lat')}  {format_dms(w['lon'], 'lon')}")
        print(f"       {w['rate_gpm']:,.1f} gpm, {w['drawdown_ft']:,.1f} ft drawdown, needs "
              f"{w['required_spacing_ft']:,.0f} ft spacing and has "
              f"{w['nearest_counting_well']['distance_ft']:,.0f} ft to map ID "
              f"{w['nearest_counting_well']['map_id']}: {w['spacing_margin_ft']:,.0f} ft of margin")
    if rec["worst_neighbour"]:
        nb = rec["worst_neighbour"]
        print(f"       worst impact {nb['drawdown_ft']:,.2f} ft at map ID {nb['map_id']} "
              f"({nb['owner'] or 'owner not recorded'}): "
              f"{nb['drawdown_from_new_wells_ft']:,.2f} ft from the new field, "
              f"{nb['drawdown_from_fixed_wells_ft']:,.2f} ft from the existing system")
    if rec["estimated_cost"] is not None:
        print(f"       estimated cost ${rec['estimated_cost']:,.0f} at the costs supplied")
    for n in out["notes"]:
        print(f"\n  Note: {n}")
    print(f"\nWrote {json_path}")
    if out.get("figure"):
        print(f"Figure: {out['figure']['path']}")


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
    s = sub.add_parser("import-review", help="write review.yaml from a review sheet submission (JSON)")
    s.add_argument("project_dir")
    s.add_argument("payload", help="path to the submission JSON saved from the sheet or read out of the artifact database")
    s.add_argument("--force", action="store_true", help="overwrite an existing review.yaml")
    s.set_defaults(fn=cmd_import_review)
    s = sub.add_parser("review-sheet", help="build the reviewer's sheet for a project that has been run")
    s.add_argument("project_dir")
    s.add_argument("--out", default=None, help="write somewhere other than build/review_sheet.html")
    s.set_defaults(fn=cmd_review_sheet)
    s = sub.add_parser("siting", help="find where on the tract the well may go and what it can produce there")
    s.add_argument("project_dir")
    s.add_argument("--well", default=None, help="which proposed well to site (default: the first)")
    s.add_argument("--rate", type=float, default=None, help="target rate in gpm (default: the well's max_rate_gpm)")
    s.add_argument("--grid-ft", type=float, default=100.0, help="candidate grid spacing in feet (default 100)")
    s.add_argument("--setback-ft", type=float, default=None,
                   help="keep candidates at least this far from the property line")
    s.add_argument("--max-interference-ft", type=float, default=None,
                   help="cap drawdown at any off-system well in the same aquifer, and report the rate that respects it")
    s.add_argument("--available-drawdown-ft", type=float, default=None,
                   help="drawdown available at the proposed well (static level to pump intake), as a rate limit")
    s.add_argument("--top", type=int, default=5, help="how many locations to rank (default 5)")
    s.add_argument("--min-separation-ft", type=float, default=None,
                   help="how far apart ranked locations must be to count as different options "
                        "(default: twice the grid spacing, at least 200 ft)")
    s.add_argument("--no-figure", action="store_true")
    s.set_defaults(fn=cmd_siting)
    s = sub.add_parser("wellfield", help="design a well field: how many wells, where, and at what rate")
    s.add_argument("project_dir")
    s.add_argument("--rate", type=float, required=True, help="total system demand in gpm")
    s.add_argument("--max-wells", type=int, default=6, help="most wells to consider (default 6)")
    s.add_argument("--grid-ft", type=float, default=200.0, help="candidate grid spacing (default 200)")
    s.add_argument("--setback-ft", type=float, default=None, help="keep wells this far from the property line")
    s.add_argument("--available-drawdown-ft", type=float, default=None,
                   help="drawdown available at each well (static level to pump intake)")
    s.add_argument("--max-interference-ft", type=float, default=None,
                   help="cap drawdown at any off-system well in the same aquifer")
    s.add_argument("--min-well-rate", type=float, default=50.0,
                   help="a well below this rate is not worth drilling (default 50 gpm)")
    s.add_argument("--max-well-rate", type=float, default=None,
                   help="most any single well can produce (pump, column and screen limits)")
    s.add_argument("--min-well-spacing-ft", type=float, default=None,
                   help="keep the new wells this far apart (a design preference, not a District rule)")
    s.add_argument("--spacing-safety-ft", type=float, default=0.0,
                   help="hold this much back from every spacing limit, as margin against the accuracy of "
                        "the District's well coordinates (default 0, which designs right on the limit)")
    s.add_argument("--aquifer", default=None, help="which aquifer to design in (default: the first proposed well's)")
    s.add_argument("--cost-per-well", type=float, default=None, help="your fixed cost per well")
    s.add_argument("--cost-per-ft", type=float, default=None, help="your drilling cost per foot")
    s.add_argument("--well-depth-ft", type=float, default=None, help="planned well depth, for the cost estimate")
    s.add_argument("--no-figure", action="store_true")
    s.set_defaults(fn=cmd_wellfield)
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
