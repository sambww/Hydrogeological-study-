"""The web intake form must stay in step with the intake schema.

The form is the one part of the system a schema change cannot break loudly: add a required field to `Intake` and the
form keeps submitting happily until someone notices the pipeline rejecting every submission. These tests close that
gap from both directions - every required field has a control, and every control names a field that exists.
"""

import json
import re
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from hydrostudy.intake_import import payload_to_intake, write_intake
from hydrostudy.schema.intake import Intake

FORM = Path(__file__).resolve().parents[1] / "web" / "intake_form.html"

#: Deliberately not collected by the form. Post-drilling capture is file-based (LAS logs, test CSVs), so it belongs
#: with the file drop rather than a questionnaire.
SKIP_BRANCHES = {"as_built"}


@pytest.fixture(scope="module")
def html():
    return FORM.read_text(encoding="utf-8")


def _block(html, block_id):
    pattern = r'<script type="application/json" id="' + re.escape(block_id) + r'">(.*?)</script>'
    m = re.search(pattern, html, re.S)
    assert m, f"the form has no {block_id} block"
    return json.loads(m.group(1))


@pytest.fixture(scope="module")
def fields(html):
    """Every schema path the form collects, derived from the spec block exactly as the renderer derives it."""
    out = set()
    for sec in _block(html, "field-spec"):
        for spec in sec.get("fields", []):
            out.add(spec["p"])
        r = sec.get("repeat")
        if not r:
            continue
        for spec in r.get("fields", []):
            out.add(f"{r['path']}[].{spec['p']}")
        for group in r.get("groups", []):
            for spec in group["fields"]:
                out.add(f"{r['path']}[].{group['prefix']}.{spec['p']}")
        for tbl in r.get("tables", []):
            for col in tbl["cols"]:
                out.add(f"{r['path']}[].{tbl['path']}[].{col['p']}")
    assert out, "no fields found in the spec block"
    return out


def _model_of(annotation):
    """The BaseModel behind an annotation, and whether it is wrapped in a list."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (list, set, tuple):
        for a in args:
            if isinstance(a, type) and issubclass(a, BaseModel):
                return a, True
        return None, False
    if args:  # Optional / unions
        for a in args:
            if a is type(None):
                continue
            model, listed = _model_of(a)
            if model is not None:
                return model, listed
    return None, False


def _required_leaves(model=Intake, prefix="", seen=None):
    """Dotted paths of required scalar fields, with [] marking a repeatable row."""
    seen = seen or set()
    if model in seen:
        return set()
    out = set()
    for name, field in model.model_fields.items():
        if name in SKIP_BRANCHES:
            continue
        nested, listed = _model_of(field.annotation)
        if nested is not None:
            # Recurse into rows even when the list itself is optional: once a row exists, its fields are required.
            out |= _required_leaves(nested, f"{prefix}{name}[]." if listed else f"{prefix}{name}.", seen | {model})
        elif field.is_required():
            out.add(prefix + name)
    return out


def _resolve(path, model=Intake):
    """True when a dotted data-field path names a real schema field."""
    parts = path.split(".")
    for i, raw in enumerate(parts):
        name = raw[:-2] if raw.endswith("[]") else raw
        field = model.model_fields.get(name)
        if field is None:
            return False
        nested, _ = _model_of(field.annotation)
        if i < len(parts) - 1:
            if nested is None:
                return False
            model = nested
    return True


def test_every_required_intake_field_has_a_control(fields):
    missing = sorted(p for p in _required_leaves() if p not in fields)
    assert not missing, f"the form has no control for required field(s): {missing}"


def test_every_control_names_a_real_schema_field(fields):
    unknown = sorted(p for p in fields if not _resolve(p))
    assert not unknown, f"the form has control(s) for field(s) that do not exist: {unknown}"


def test_the_form_collects_the_fields_that_drive_the_analysis(fields):
    """Spot check: the numbers the Theis run and the spacing check cannot be done without."""
    for path in ("proposed_wells[].max_rate_gpm", "proposed_wells[].total_depth_ft", "proposed_wells[].aquifer",
                 "aquifers[].params.t_ft2d", "aquifers[].params.s", "permit.annual_volume_gal",
                 "proposed_wells[].screen[].top_ft", "proposed_wells[].borehole[].diameter_in",
                 "existing_wells[].include_in_system"):
        assert path in fields, path


def test_embedded_example_is_a_valid_submission(html, tmp_path):
    """The training example must import, or the first thing a new user tries fails."""
    payload = _block(html, "example-payload")
    intake, _, _ = payload_to_intake(payload)
    assert intake.proposed_wells[0].id == "W2"
    assert write_intake(tmp_path / "p", payload).exists()


def test_example_would_fail_the_same_checks_the_schema_applies(html):
    """Guard the guard: a broken example must be caught, not silently accepted."""
    payload = _block(html, "example-payload")
    payload["proposed_wells"][0]["max_rate_gpm"] = -1
    with pytest.raises(ValidationError):
        payload_to_intake(payload)


def test_form_declares_no_capability_it_cannot_degrade_without(html):
    """Every capability call must be reached through the guarded helper, since use() can resolve null."""
    direct = re.findall(r'(?<!function )claude\.use\(', html)
    assert len(direct) == 1, "capability access should go through the single cap() helper"
    assert 'await cap("db")' in html and 'await cap("downloads")' in html
