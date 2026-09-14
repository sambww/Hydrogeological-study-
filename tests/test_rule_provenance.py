"""A spacing conclusion may never be stated more firmly than the rule behind it.

Three tiers carry different weight: a reading of the District's own rules (primary), a named operator's attestation
that the rule is unchanged (operator_attested), and a multiplier reconstructed from prior accepted submittals
(derived). The first two let the report quote the distance as the District's requirement, and both expire. The third
makes the report state the distance it applied and ask the reviewer to confirm it.

Lone Star currently ships as operator_attested: the multipliers came out of submittals the District accepted in 2023
and the operator confirms they are current. Nobody has read Rule 3.3.
"""

from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

from hydrostudy.analysis.checks import collect_flags
from hydrostudy.analysis.spacing import spacing_analysis
from hydrostudy.districts.loader import District, load_district
from hydrostudy.districts.status import rule_status, spacing_basis_sentence

TODAY = date.today()
LONG_AGO = (TODAY - timedelta(days=400)).isoformat()


def _district(**over):
    """A copy of the shipped Lone Star rules, with `section__field=value` overrides."""
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


def _flags(spacing, district_id="lsgcd"):
    review = SimpleNamespace(
        opinions=SimpleNamespace(model_dump=lambda: {}),
        reviewer=SimpleNamespace(status="final"),
    )
    intake = SimpleNamespace(report=SimpleNamespace(issuing_firm="other"))
    return collect_flags(intake, review, {}, spacing, [], [],
                         {"has_geometry": True, "notes": "x", "springs_searched": True},
                         {"n_records": 1}, district_id)


def _codes(spacing, district_id="lsgcd"):
    return [f["code"] for f in _flags(spacing, district_id)]


# --------------------------------------------------------------------------------------------------- tier semantics

def test_lone_star_ships_as_operator_attested_and_names_the_attester():
    st = rule_status(load_district("lsgcd"))
    assert st["spacing_source"] == "operator_attested"
    assert st["spacing_authoritative"] is True
    assert st["attested_by"] and st["attested_on"]


def test_derived_spacing_is_never_authoritative_even_when_freshly_verified():
    d = _district(rules__verified_on=TODAY.isoformat(), spacing__source="derived")
    st = rule_status(d)
    assert st["stale"] is False
    assert st["spacing_authoritative"] is False


def test_primary_and_fresh_spacing_is_authoritative():
    d = _district(rules__verified_on=TODAY.isoformat(), spacing__source="primary")
    assert rule_status(d)["spacing_authoritative"] is True


def test_primary_but_stale_spacing_is_not_authoritative():
    d = _district(rules__verified_on=LONG_AGO, spacing__source="primary")
    st = rule_status(d)
    assert st["spacing_stale"] is True
    assert st["spacing_authoritative"] is False


def test_an_attestation_expires_with_the_recheck_window():
    """An operator's word is good for the same window as a reading, not forever."""
    d = _district(spacing__attested_on=LONG_AGO, rules__verified_on=LONG_AGO)
    st = rule_status(d)
    assert st["spacing_stale"] is True
    assert st["spacing_authoritative"] is False


def test_an_attestation_date_does_not_make_a_primary_reading_look_fresh():
    """attested_on dates an attestation only. Switching to primary must not inherit its freshness."""
    d = _district(rules__verified_on=LONG_AGO, spacing__source="primary", spacing__attested_on=TODAY.isoformat())
    assert rule_status(d)["spacing_stale"] is True


def test_spacing_can_carry_its_own_verification_date():
    d = _district(rules__verified_on=LONG_AGO, spacing__source="primary", spacing__verified_on=TODAY.isoformat())
    st = rule_status(d)
    assert st["stale"] is True                      # the guidelines reading is old
    assert st["spacing_authoritative"] is True      # the spacing reading is not


def test_missing_verification_date_reads_as_stale():
    st = rule_status(_district(rules__verified_on=None, spacing__attested_on=None))
    assert st["stale"] is True
    assert st["age_days"] is None
    assert st["spacing_authoritative"] is False


def test_unparseable_date_reads_as_stale_rather_than_fresh():
    st = rule_status(_district(rules__verified_on="soon", spacing__attested_on="last spring"))
    assert st["stale"] is True
    assert st["spacing_authoritative"] is False


def test_recheck_window_boundary():
    d = _district(spacing__source="primary")
    window = d["rules"]["recheck_after_days"]
    d["rules"]["verified_on"] = (TODAY - timedelta(days=window)).isoformat()
    assert rule_status(d)["stale"] is False
    d["rules"]["verified_on"] = (TODAY - timedelta(days=window + 1)).isoformat()
    assert rule_status(d)["stale"] is True


# ------------------------------------------------------------------------------------------- analysis, flags, wording

def test_derived_multiplier_marks_wells_provisional_and_raises_a_review_flag():
    d = _district(spacing__source="derived")
    sp = spacing_analysis(_intake(), d, [], rule_status(d))
    well = sp["wells"][0]
    assert well["rule_available"] is True
    assert well["complies"] is True          # no conflicting wells were supplied
    assert well["provisional"] is True       # but the multiplier itself is unconfirmed
    assert "SPACING_RULE_UNVERIFIED" in _codes(sp)


def test_attested_multiplier_is_not_provisional_and_records_itself_as_info():
    d = _district()
    sp = spacing_analysis(_intake(), d, [], rule_status(d))
    assert sp["wells"][0]["provisional"] is False
    flags = {f["code"]: f for f in _flags(sp)}
    assert "SPACING_RULE_UNVERIFIED" not in flags
    attested = flags["SPACING_RULE_ATTESTED"]
    assert attested["level"] == "info"
    assert "Samuel Ballard" in attested["text"]


def test_primary_rules_raise_neither_spacing_flag():
    d = _district(rules__verified_on=TODAY.isoformat(), spacing__source="primary")
    codes = _codes(spacing_analysis(_intake(), d, [], rule_status(d)))
    assert "SPACING_RULE_UNVERIFIED" not in codes
    assert "SPACING_RULE_ATTESTED" not in codes


def test_expired_attestation_is_reported_as_expiry_not_as_a_missing_source():
    d = _district(spacing__attested_on=LONG_AGO, rules__verified_on=LONG_AGO)
    sp = spacing_analysis(_intake(), d, [], rule_status(d))
    text = next(f["text"] for f in _flags(sp) if f["code"] == "SPACING_RULE_UNVERIFIED")
    assert "outside the re-check window" in text


def test_stale_rules_raise_their_own_flag():
    d = _district(rules__verified_on=LONG_AGO)
    assert "DISTRICT_RULES_STALE" in _codes(spacing_analysis(_intake(), d, [], rule_status(d)))


def test_basis_sentence_per_tier():
    assert spacing_basis_sentence({"spacing_source": "primary"}) is None
    attested = spacing_basis_sentence(
        {"spacing_source": "operator_attested", "attested_by": "A. Driller", "attested_on": "2026-09-14"})
    assert "A. Driller" in attested and "2026-09-14" in attested
    assert "not on a reading of the District Rules" in attested
    assert "subject to confirmation" in spacing_basis_sentence({"spacing_source": "derived"})


def test_black_oak_states_the_rule_and_records_the_basis(black_oak_project):
    p = black_oak_project
    sp = p.artifacts["analysis"]["spacing"]
    assert not any(w["provisional"] for w in sp["wells"])

    checklist = p.artifacts.get("checklist") or p.run_checklist()
    assert next(i for i in checklist["items"] if i["id"] == "II.B.1")["status"] == "satisfied"

    prov = p.artifacts["provenance"]["district_rules"]
    assert prov["spacing_source"] == "operator_attested"
    assert "Samuel Ballard" in spacing_basis_sentence(prov)
