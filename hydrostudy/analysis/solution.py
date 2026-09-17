"""Which analytical solution is in force, resolved once and used everywhere.

Tables, contour maps, distance-drawdown curves, the siting search and the methodology narrative must
all describe the same calculation. The way that goes wrong is for one of them to keep calling Theis
directly while the others move on, so the solution is resolved here, once per aquifer, and passed
around as an object whose `drawdown` has the same signature as `theis.theis_drawdown`.

Choosing Hantush-Jacob requires a leakance for the confining unit. If the intake does not supply one,
this does **not** invent a plausible value: it falls back to Theis and raises a flag saying what is
missing. A leakance is a measured or cited property of a specific clay, and guessing one would put a
number in a sealed report that nobody can source.
"""

from __future__ import annotations

from dataclasses import dataclass

from hydrostudy.analysis.leaky import leakage_factor_ft, leakance_per_day, leaky_drawdown, steady_drawdown
from hydrostudy.analysis.theis import theis_drawdown

THEIS_CITATION = "Theis (1935) nonequilibrium solution"
HANTUSH_CITATION = "Hantush-Jacob (1955) leaky-aquifer solution"


@dataclass(frozen=True)
class Solution:
    """The drawdown solution for one aquifer, plus what to say about it."""

    kind: str                       # "theis" | "hantush"
    leakance: float | None = None   # K'/b' in 1/day
    b_ft: float | None = None       # leakage factor sqrt(T / leakance)
    basis: str | None = None        # where the leakance came from
    requested: str | None = None    # what the intake asked for, if different from `kind`

    @property
    def is_leaky(self) -> bool:
        return self.kind == "hantush"

    @property
    def citation(self) -> str:
        return HANTUSH_CITATION if self.is_leaky else THEIS_CITATION

    @property
    def fell_back(self) -> bool:
        return self.requested is not None and self.requested != self.kind

    def drawdown(self, q_gpm, t_ft2d, s, r_ft, t_days):
        """Same signature as `theis_drawdown`, so it can be injected wherever that is called."""
        if self.is_leaky:
            return leaky_drawdown(q_gpm, t_ft2d, s, r_ft, t_days, self.leakance)
        return theis_drawdown(q_gpm, t_ft2d, s, r_ft, t_days)

    def steady_ceiling_ft(self, q_gpm, t_ft2d, r_ft):
        """The drawdown this solution can never exceed, or None for Theis, which has no ceiling."""
        if not self.is_leaky:
            return None
        return float(steady_drawdown(q_gpm, t_ft2d, r_ft, self.leakance))

    def to_json(self) -> dict:
        return {"kind": self.kind, "citation": self.citation, "leakance_per_day": self.leakance,
                "leakage_factor_ft": self.b_ft, "basis": self.basis, "requested": self.requested,
                "fell_back": self.fell_back}


def solution_from(result: dict) -> Solution:
    """Rebuild the solution a stored scenario result was computed with.

    Figures are rendered from `build/analysis.json`, not from the intake, so they read the solution back
    out of the result they are drawing. A figure that re-derives it from the intake could disagree with
    the numbers beside it after a reviewer override.
    """
    spec = (result or {}).get("solution") or {}
    return Solution(spec.get("kind", "theis"), spec.get("leakance_per_day"),
                    spec.get("leakage_factor_ft"), spec.get("basis"), spec.get("requested"))


def _leakance_from(conf) -> tuple[float | None, str | None]:
    """Leakance and its provenance from a `Confinement`, or (None, None)."""
    if conf is None:
        return None, None
    # An uncited leakance says so. Writing "stated in the intake" would be this module inventing the
    # provenance it exists to demand.
    uncited = "source not stated in the intake; the reviewer must supply a citation before sealing"
    stated = getattr(conf, "leakance_per_day", None)
    if stated:
        return float(stated), (conf.leakance_source or uncited)
    k_prime = getattr(conf, "k_prime_ftd", None)
    if k_prime and conf.thickness_ft:
        derived = (f"K'/b' from a confining-unit conductivity of {k_prime:g} ft/day over "
                   f"{conf.thickness_ft:,.0f} ft")
        basis = f"{derived}; {conf.leakance_source}" if conf.leakance_source else f"{derived}; {uncited}"
        return leakance_per_day(float(k_prime), float(conf.thickness_ft)), basis
    return None, None


def resolve_solution(intake, aquifer_name: str, t_ft2d: float) -> tuple[Solution, list[dict]]:
    """The solution for one aquifer, with any flags the choice raises."""
    requested = getattr(intake.analysis, "solution", "theis")
    if requested == "theis":
        return Solution("theis"), []

    try:
        conf = intake.aquifer(aquifer_name).confinement
    except KeyError:
        conf = None
    leakance, basis = _leakance_from(conf)
    if leakance is None:
        return Solution("theis", requested=requested), [{
            "level": "warn", "code": "LEAKANCE_MISSING",
            "text": f"{aquifer_name}: analysis.solution is '{requested}', which needs the confining unit's "
                    "leakance, but neither confinement.leakance_per_day nor confinement.k_prime_ftd with "
                    "confinement.thickness_ft is given. The Theis solution was used instead, which "
                    "overestimates long-term drawdown where the confining unit leaks. Supply a cited "
                    "leakance or set analysis.solution back to 'theis'."}]

    flags = []
    if conf is not None and conf.status == "confined":
        flags.append({
            "level": "review", "code": "LEAKY_BUT_CONFINED",
            "text": f"{aquifer_name}: a leaky solution was applied to an aquifer whose confinement status "
                    "is 'confined'. Confirm the status, or the report will describe a confining unit that "
                    "both does and does not pass water."})
    if not getattr(conf, "leakance_source", None):
        flags.append({
            "level": "review", "code": "LEAKANCE_UNCITED",
            "text": f"{aquifer_name}: the leakance driving the leaky solution has no source. Every "
                    "reported drawdown depends on it, so set confinement.leakance_source to the test, "
                    "publication or model it came from before the report is sealed."})
    b_ft = leakage_factor_ft(t_ft2d, leakance)
    return Solution("hantush", leakance, b_ft, basis, requested), flags


def leakage_reach_note(sol: Solution, search_radius_ft: float) -> str | None:
    """Whether leakage actually matters at the distances being reported."""
    if not sol.is_leaky or not sol.b_ft:
        return None
    if sol.b_ft > 10 * search_radius_ft:
        return (f"The leakage factor ({sol.b_ft:,.0f} ft) is more than ten times the search radius "
                f"({search_radius_ft:,.0f} ft), so leakage makes little difference to the drawdown "
                "reported here and the result is close to the Theis solution.")
    if sol.b_ft < search_radius_ft / 10:
        return (f"The leakage factor ({sol.b_ft:,.0f} ft) is small relative to the search radius "
                f"({search_radius_ft:,.0f} ft), so drawdown approaches its steady-state cone quickly "
                "and is largely insensitive to pumping duration.")
    return None
