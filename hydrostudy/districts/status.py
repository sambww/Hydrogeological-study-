"""Provenance and freshness of the district rules used to reach compliance conclusions.

A spacing conclusion is only as good as the multiplier behind it. Multipliers reconstructed from prior accepted
submittals (source: derived) are not a substitute for the District's own rules document (source: primary), and even a
primary reading goes stale. `rule_status` turns those two facts into one structure the narrative, flags and checklist
all read, so the report never states a regulatory conclusion more firmly than its source supports.
"""

from __future__ import annotations

from datetime import date

DEFAULT_RECHECK_DAYS = 180


def _parse(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def rule_status(district, today: date | None = None) -> dict:
    today = today or date.today()
    rules = district.get("rules", {}) or {}
    spacing = district.get("spacing", {}) or {}

    verified = _parse(rules.get("verified_on"))
    recheck = int(rules.get("recheck_after_days") or DEFAULT_RECHECK_DAYS)
    age = (today - verified).days if verified else None
    stale = age is None or age > recheck

    source = (rules.get("source") or "unknown").lower()
    spacing_source = (spacing.get("source") or source).lower()
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
        # A spacing distance may be quoted as the District's rule only when it was read from the District's own
        # rules document and that reading is still inside the recheck window.
        "spacing_authoritative": has_multiplier and spacing_source == "primary" and not stale,
        "authoritative": source == "primary" and not stale,
    }
