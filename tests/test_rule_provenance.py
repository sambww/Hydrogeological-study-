"""A spacing conclusion may never be stated more firmly than the rule behind it.

The LSGCD multipliers in this repo were reconstructed from submittals the District accepted, not read from the District
Rules. These tests hold the line that the report asks the reviewer to confirm the distance instead of asserting
compliance, and that a properly sourced rule file drops the qualifier.
"""

from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

from hydrostudy.analysis.checks import collect_flags
from hydrostudy.analysis.spacing import spacing_analysis
from hydrostudy.districts.loader import District, load_district
from hydrostudy.districts.status import rule_status


def _district(**over):
    d = District(deepcopy(dict(load_district("lsgcd"))))
    for key, value in over.items():
        section, _, field = key.partition("__")
        d[section][field] = value
    return d


def _intake():
    return SimpleNamespace(
        permit=SimpleNamespace(spacing_exception_requested=False),
        proposed_wells=[SimpleNamespace(id="w1", aquifer="Evangeline", max_rate_gpm=500.0)],
        system_rate_gpm=500.0,
    )


def test_derived_spacing_is_never_authoritative_even_when_freshly_verified():
    d = _district(rules__verified_on=date.today().isoformat())
    st = rule_status(d)
    assert st["stale"] is False
    assert st["spacing_source"] == "derived"
    assert st["spacing_authoritative"] is False


def test_primary_and_fresh_spacing_is_authoritative():
    d = _district(rules__verified_on=date.today().isoformat(), spacing__source="primary")
    assert rule_status(d)["spacing_authoritative"] is True


def test_primary_but_stale_spacing_is_not_authoritative():
    old = (date.today() - timedelta(days=400)).isoformat()
    d = _district(rules__verified_on=old, spacing__source="primary")
    st = rule_status(d)
    assert st["stale"] is True
    assert st["spacing_authoritative"] is False


def test_missing_verification_date_reads_as_stale():
    st = rule_status(_district(rules__verified_on=None))
    assert st["stale"] is True
    assert st["age_days"] is None


def test_recheck_window_boundary():
    d = _district(spacing__source="primary")
    window = d["rules"]["recheck_after_days"]
    on_window = (date.today() - timedelta(days=window)).isoformat()
    past_window = (date.today() - timedelta(days=window + 1)).isoformat()
    d["rules"]["verified_on"] = on_window
    assert rule_status(d)["stale"] is False
    d["rules"]["verified_on"] = past_window
    assert rule_status(d)["stale"] is True


def test_spacing_analysis_marks_wells_provisional_and_flags_it():
    d = _district()
    sp = spacing_analysis(_intake(), d, [], rule_status(d))
    well = sp["wells"][0]
    assert well["rule_available"] is True
    assert well["complies"] is True          # no conflicting wells were supplied
    assert well["provisional"] is True       # but the multiplier itself is unconfirmed
    codes = [f["code"] for f in _flags(sp)]
    assert "SPACING_RULE_UNVERIFIED" in codes


def test_primary_rules_drop_the_provisional_marker_and_the_flag():
    d = _district(rules__verified_on=date.today().isoformat(), spacing__source="primary")
    sp = spacing_analysis(_intake(), d, [], rule_status(d))
    assert sp["wells"][0]["provisional"] is False
    assert "SPACING_RULE_UNVERIFIED" not in [f["code"] for f in _flags(sp)]


def test_stale_rules_raise_their_own_flag():
    d = _district(rules__verified_on=(date.today() - timedelta(days=400)).isoformat())
    sp = spacing_analysis(_intake(), d, [], rule_status(d))
    assert "DISTRICT_RULES_STALE" in [f["code"] for f in _flags(sp)]


def _flags(spacing):
    review = SimpleNamespace(
        opinions=SimpleNamespace(model_dump=lambda: {}),
        reviewer=SimpleNamespace(status="final"),
    )
    intake = SimpleNamespace(report=SimpleNamespace(issuing_firm="other"))
    return collect_flags(intake, review, {}, spacing, [], [],
                         {"has_geometry": True, "notes": "x", "springs_searched": True},
                         {"n_records": 1}, "lsgcd")


def test_black_oak_report_asks_rather_than_asserts(black_oak_project):
    p = black_oak_project
    sp = p.artifacts["analysis"]["spacing"]
    assert all(w["provisional"] for w in sp["wells"])

    checklist = p.artifacts.get("checklist") or p.run_checklist()
    item = next(i for i in checklist["items"] if i["id"] == "II.B.1")
    assert item["status"] == "needs_professional_input"
