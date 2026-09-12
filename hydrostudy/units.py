"""Unit constants and number formatting. Every unit conversion in the package goes through here."""

from __future__ import annotations

import math

# 1 gallon per minute = 1440 gal/day / 7.48052 gal/ft3 = 192.5 ft3/day
GPM_TO_CFD = 192.5
GAL_PER_FT3 = 7.48052
FT_PER_MILE = 5280.0
MIN_PER_DAY = 1440.0
HOURS_PER_DAY = 24.0
FT_PER_US_SURVEY_FT = 1.0  # local CRS is built directly in US survey feet
DAYS_PER_YEAR = 365.0


def gpm_to_cfd(q_gpm: float) -> float:
    return q_gpm * GPM_TO_CFD


def hours_to_days(h: float) -> float:
    return h / HOURS_PER_DAY


def years_to_days(y: float) -> float:
    return y * DAYS_PER_YEAR


def ft_to_miles(ft: float) -> float:
    return ft / FT_PER_MILE


def gallons_at_rate(q_gpm: float, t_days: float) -> float:
    return q_gpm * MIN_PER_DAY * t_days


# ---------- formatting (used by the report context; the lint checks numbers against these strings) ----------

def fmt_ft(x: float, nd: int = 1) -> str:
    return f"{x:,.{nd}f}"


def fmt_int(x: float) -> str:
    return f"{int(round(x)):,}"


def fmt_days(d: float) -> str:
    if abs(d - round(d)) < 1e-9:
        return fmt_int(d)
    return f"{d:,.2f}"


def fmt_sci(x: float, nd: int = 2) -> str:
    """3.36e-4 -> '3.36 x 10^-4' (Word-friendly plain text)."""
    if x == 0:
        return "0"
    exp = int(math.floor(math.log10(abs(x))))
    mant = x / 10**exp
    return f"{mant:.{nd}f} x 10^{exp}"


def fmt_gal(x: float) -> str:
    return fmt_int(x)


def fmt_miles(ft: float, nd: int = 1) -> str:
    return f"{ft_to_miles(ft):,.{nd}f}"
