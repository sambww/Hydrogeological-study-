"""Provenance and freshness of the district rules used to reach compliance conclusions.

A spacing conclusion is only as good as the multiplier behind it. There are three tiers:

* ``primary``           - read from a document the District published.
* ``operator_attested`` - confirmed current by a named person with standing in the district, on a date.
* ``derived``           - reconstructed from something else, such as prior accepted submittals.

The first two support quoting the distance as the District's requirement; the third does not, and the report says so
instead of asserting compliance. Every tier expires: an attestation and a reading of the published guidelines age on
their own clocks, so the spacing scope carries its own verification date. ``rule_status`` turns all of that into one
structure the narrative, flags, checklist and provenance appendix read, so the report never states a regulatory
conclusion more firmly than its source supports.
"""

from __future__ import annotations

from datetime import date

DEFAULT_RECHECK_DAYS = 180

#: Sources that support quoting a rule as the District's own requirement.
AUTHORITATIVE_SOURCES = ("primary", "operator_attested")


def _parse(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _age(value, recheck: int, today: date) -> tuple[int | None, bool]:
    """Return (age in days, stale). An unparseable or missing date reads as stale, never as fresh."""
    when = _parse(value)
    if when is None:
        return None, True
    days = (today - when).days
    return days, days > recheck


def rule_status(district, today: date | None = None) -> dict:
    today = today or date.today()
    rules = district.get("rules", {}) or {}
    spacing = district.get("spacing", {}) or {}
    recheck = int(rules.get("recheck_after_days") or DEFAULT_RECHECK_DAYS)

    source = (rules.get("source") or "unknown").lower()
    spacing_source = (spacing.get("source") or source).lower()

    age, stale = _age(rules.get("verified_on"), recheck, today)

    # The spacing scope keeps its own clock. attested_on only dates an attestation, so it is ignored for any other
    # source: marking spacing primary must not inherit freshness from a leftover attestation date.
    spacing_date = spacing.get("verified_on")
    if not spacing_date and spacing_source == "operator_attested":
        spacing_date = spacing.get("attested_on")
    spacing_date = spacing_date or rules.get("verified_on")
    spacing_age, spacing_stale = _age(spacing_date, recheck, today)

    has_multiplier = bool(spacing.get("well_to_well"))

    return {
        "source": source,
        "source_note": rules.get("source_note"),
        "verified_on": rules.get("verified_on"),
        "verified_by": rules.get("verified_by"),
        "age_days": age,
        "recheck_after_days": recheck,
        "stale": stale,
        "spacing_source": spacing_source,
        "spacing_source_note": spacing.get("source_note") or rules.get("source_note"),
        "spacing_verified_on": spacing_date,
        "spacing_age_days": spacing_age,
        "spacing_stale": spacing_stale,
        "attested_by": spacing.get("attested_by") or rules.get("attested_by"),
        "attested_on": spacing.get("attested_on") or rules.get("attested_on"),
        # A spacing distance may be quoted as the District's rule only when its source carries that weight and the
        # verification behind it is still inside the recheck window.
        "spacing_authoritative": has_multiplier and spacing_source in AUTHORITATIVE_SOURCES and not spacing_stale,
        "authoritative": source in AUTHORITATIVE_SOURCES and not stale,
    }


def spacing_basis_sentence(rules_prov: dict) -> str | None:
    """One provenance sentence saying what the spacing multipliers rest on, or None when the Rules themselves do.

    Takes the ``district_rules`` provenance dict written by the pipeline so both assemblers can render the same note.
    A reader of the sealed report should never have to open the repo to find out where a regulatory number came from.
    """
    source = (rules_prov.get("spacing_source") or "").lower()
    if source == "primary":
        return None
    if source == "operator_attested":
        who = rules_prov.get("attested_by") or "an unnamed operator"
        when = rules_prov.get("attested_on")
        return ("Spacing multipliers are stated on the attestation of " + who
                + (f", {when}, " if when else " ")
                + "that the District's spacing rule is unchanged, not on a reading of the District Rules.")
    return ("Spacing multipliers were not read from the District Rules; the required distance is stated as applied and "
            "is subject to confirmation by the reviewing professional.")
