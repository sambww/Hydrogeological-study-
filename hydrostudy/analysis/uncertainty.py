"""How sure is the drawdown? Parameter uncertainty propagated by Monte Carlo.

Every number this package reports rests on one transmissivity and one storativity. Black Oak's T came
from a single 36-hour test; the GAM says something 20% different for the same cell. A reviewing
geoscientist, or a District hearing, asks how sure the answer is, and a single value cannot answer.

This draws T and S from declared distributions, recomputes drawdown for every draw, and reports the
spread: a median, an interval, and - the number that actually settles arguments - the probability that
drawdown at a specific well exceeds a specific figure.

Three rules it keeps.

**Nothing is defaulted.** A spread must be declared in the intake with a `source`
(`schema/intake.py::ParamDistribution`). Inventing a coefficient of variation would be inventing the
confidence interval, which is worse than having none: it puts a number nobody can source into the one
part of a report that is explicitly about how much to trust the other numbers. Without a declared
distribution this refuses and says what to supply.

**It is reproducible.** A sealed report has to be re-derivable, so the draw count and the seed are
inputs and both are recorded in the output. The same project and seed give bit-identical numbers.

**It reports its own error.** A quantile from 10,000 draws is itself an estimate. The standard error of
each reported quantile comes out alongside it, so "the p90 is 79 ft" cannot be read as more precise than
the sampling supports.

T and S are sampled independently unless the intake declares a correlation. A single-well pump test
cannot separate the two - a fit trades one against the other - so the pair really is correlated in that
case, and the output says which assumption was used either way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from hydrostudy.analysis.boundaries import for_aquifer, with_images
from hydrostudy.analysis.solution import resolve_solution
from hydrostudy.analysis.theis import PumpingWell, pumping_center

#: Draws. 10,000 puts the standard error of a p90 at well under a tenth of a foot for these spreads,
#: which is finer than any input justifies.
DEFAULT_DRAWS = 10_000
#: Recorded in the output, because a confidence interval nobody can reproduce is not evidence.
DEFAULT_SEED = 20260917
#: 1.2816 = the standard normal z for p10/p90, used to turn a declared pair into a lognormal.
Z90 = 1.2815515655446004


class UncertaintyNotPossible(RuntimeError):
    """No declared distribution, or nothing to propagate it through."""


@dataclass
class UncertaintyRequest:
    draws: int = DEFAULT_DRAWS
    seed: int = DEFAULT_SEED
    quantiles: tuple = (0.10, 0.50, 0.90)
    #: Drawdown figures to report an exceedance probability for, at every receptor.
    thresholds_ft: tuple = ()
    aquifer: str | None = None
    scenario_key: str | None = None


@dataclass
class _Receptor:
    kind: str            # "pumped" | "registered" | "boundary"
    label: str
    detail: dict = field(default_factory=dict)
    r_by_well: np.ndarray = None       # distance from each pumping well, already floored at r_w


def _lognormal_params(dist) -> tuple[float, float]:
    """(mu, sigma) on the log scale, from whichever pair of numbers was declared."""
    if dist.p10 is not None:
        mu = (math.log(dist.p10) + math.log(dist.p90)) / 2.0
        return mu, (math.log(dist.p90) - math.log(dist.p10)) / (2.0 * Z90)
    return math.log(dist.median), math.log(dist.gsd)


def icdf(dist, u):
    """The declared distribution's inverse CDF at probability `u`. The single derivation of its shape.

    Everything that needs a number out of a distribution goes through here: the sampler, and the
    `declared_*` figures the narrative quotes. Two derivations of the same lognormal would eventually
    disagree, and the one the caption used would be the one nobody tested.
    """
    from scipy.stats import norm
    u = np.asarray(u, dtype=float)
    if dist.kind == "lognormal":
        mu, sigma = _lognormal_params(dist)
        return np.exp(mu + sigma * norm.ppf(u))
    if dist.kind == "uniform":
        return dist.minimum + u * (dist.maximum - dist.minimum)
    a, c, b = dist.minimum, dist.mode, dist.maximum
    split = (c - a) / (b - a)
    lower = a + np.sqrt(np.maximum(u * (b - a) * (c - a), 0.0))
    upper = b - np.sqrt(np.maximum((1.0 - u) * (b - a) * (b - c), 0.0))
    return np.where(u < split, lower, upper)


def declared_quantile(dist, q: float) -> float:
    """A quantile of the distribution as declared, not of a finite sample of it.

    What a caption or a table calls "the declared p10 to p90" has to be the declaration itself. A sample
    quantile from 10,000 draws lands a few units away, and printing that as the declared spread misstates
    the input - visibly so for a uniform, whose declared minimum is a round number the operator chose.
    """
    return float(icdf(dist, q))


def sample(dist, n: int, rng) -> np.ndarray:
    """`n` draws from a declared distribution. Positive by construction, like the parameters."""
    return _from_normal(dist, rng.normal(0.0, 1.0, n))


def _from_normal(dist, z) -> np.ndarray:
    """Turn standard-normal deviates into draws from `dist`, preserving their order.

    Sampling through a shared normal scale is what lets two parameters be correlated. Only the lognormal
    has a natural one; for a uniform or triangular the deviates go through the normal CDF first, which
    couples the two parameters' ranks rather than their values - enough to express "high T goes with high
    S" without claiming more structure than the intake declared.
    """
    from scipy.stats import norm
    if dist.kind == "lognormal":
        mu, sigma = _lognormal_params(dist)
        return np.exp(mu + sigma * np.asarray(z, dtype=float))
    return icdf(dist, norm.cdf(z))


def draw_parameters(unc, n: int, seed: int, t_fixed: float, s_fixed: float):
    """(T draws, S draws, notes). A parameter with no declared spread is held at its intake value."""
    rng = np.random.default_rng(seed)
    notes = []
    corr = unc.log_correlation if unc else None
    # One normal deviate per parameter, correlated if the intake says they are.
    z1 = rng.normal(0.0, 1.0, n)
    z2 = rng.normal(0.0, 1.0, n)
    if corr:
        z2 = corr * z1 + math.sqrt(max(1.0 - corr**2, 0.0)) * z2
        notes.append(f"T and S were drawn with a rank correlation of {corr:+.2f} "
                     f"({(unc.correlation_source or 'source not stated in the intake')}).")
    else:
        notes.append("T and S were drawn independently. A single-well pump test cannot separate them, so "
                     "if these spreads come from one such test the real pair is correlated and this "
                     "overstates the spread of their combination; declare uncertainty.log_correlation to "
                     "model it.")

    t_dist = unc.t_ft2d if unc else None
    s_dist = unc.s if unc else None
    t_draws = _from_normal(t_dist, z1) if t_dist else np.full(n, float(t_fixed))
    s_draws = _from_normal(s_dist, z2) if s_dist else np.full(n, float(s_fixed))
    if t_dist is None:
        notes.append(f"Transmissivity was held at its intake value ({t_fixed:,.0f} ft2/day): no spread "
                     "was declared for it.")
    if s_dist is None:
        notes.append(f"Storativity was held at its intake value ({s_fixed:.2e}): no spread was declared "
                     "for it.")
    return t_draws, s_draws, notes


def quantile_standard_error(values: np.ndarray, q: float) -> float:
    """Standard error of a sample quantile, by the usual asymptotic density estimate.

    Reported so a p90 from a finite number of draws is not read as an exact figure.
    """
    n = values.size
    if n < 100:
        return float("nan")
    lo = max(0.0, q - 0.05)
    hi = min(1.0, q + 0.05)
    spread = float(np.quantile(values, hi) - np.quantile(values, lo))
    if spread <= 0:
        return 0.0
    density = (hi - lo) / spread                     # f(x_q), from the local slope of the quantile curve
    return math.sqrt(q * (1.0 - q) / n) / density


def _summary(values: np.ndarray, quantiles, thresholds) -> dict:
    out = {
        "mean_ft": float(np.mean(values)),
        "quantiles": {f"{q:g}": {"ft": float(np.quantile(values, q)),
                                 "standard_error_ft": quantile_standard_error(values, q)}
                      for q in quantiles},
        "min_ft": float(np.min(values)), "max_ft": float(np.max(values)),
    }
    if thresholds:
        out["exceedance"] = {f"{th:g}": float(np.mean(values > th)) for th in thresholds}
    return out


def propagate(project, req: UncertaintyRequest | None = None) -> dict:
    """Drawdown as a distribution rather than a value, for one scenario and one aquifer."""
    req = req or UncertaintyRequest()
    intake = project.intake
    if req.draws < 100:
        raise UncertaintyNotPossible("at least 100 draws are needed for a meaningful quantile")

    aquifer = req.aquifer or intake.proposed_wells[0].aquifer
    params = project.artifacts["analysis"]["aquifer_params"].get(aquifer)
    if params is None:
        known = ", ".join(sorted(project.artifacts["analysis"]["aquifer_params"]))
        raise UncertaintyNotPossible(f"the intake defines no aquifer named {aquifer!r} (defined: {known})")

    try:
        unc = intake.aquifer(aquifer).uncertainty
    except KeyError:
        unc = None
    if unc is None or (unc.t_ft2d is None and unc.s is None):
        raise UncertaintyNotPossible(_no_distribution_message(aquifer, params))

    scenarios = project.artifacts["analysis"]["scenarios"]
    candidates = [s for s in scenarios if aquifer in s["results_by_aquifer"]]
    if req.scenario_key:
        candidates = [s for s in candidates if s["key"] == req.scenario_key]
        if not candidates:
            keys = ", ".join(s["key"] for s in scenarios)
            raise UncertaintyNotPossible(f"no scenario {req.scenario_key!r} in this project (have: {keys})")
    else:
        # The case the District decides on: the whole system at maximum production, or the largest
        # scenario available if this project has only one well.
        system = [s for s in candidates if s["group"] == "system" and s["duration_kind"] == "max_production"]
        candidates = system or [s for s in candidates if s["duration_kind"] == "max_production"] or candidates
    if not candidates:
        raise UncertaintyNotPossible(f"no scenario in this project pumps from the {aquifer}")
    scenario = candidates[0]
    res = scenario["results_by_aquifer"][aquifer]

    sol, sol_flags = resolve_solution(intake, aquifer, params["t_ft2d"])
    boundaries = for_aquifer(project.build_boundaries(), aquifer)
    group = [PumpingWell(w["id"], w["x_ft"], w["y_ft"], w["q_gpm"], w["r_w_ft"], aquifer)
             for w in res["wells_xy"]]
    field_wells, images = with_images(group, boundaries, intake.analysis.image_max_order)
    t_days = scenario["duration_days"]

    receptors = _receptors(project, intake, res, field_wells, aquifer, boundaries, group)
    if not receptors:
        raise UncertaintyNotPossible("no receptor to report: the scenario has no pumped well")

    t_draws, s_draws, notes = draw_parameters(unc, req.draws, req.seed, params["t_ft2d"], params["s"])

    # Drawdown for every draw at every receptor. Theis and Hantush-Jacob both take arrays, so this is
    # one vectorised evaluation per pumping well rather than a loop over draws.
    q = np.array([w.q_gpm for w in field_wells], dtype=float)
    results = []
    for rec in receptors:
        total = np.zeros(req.draws, dtype=float)
        for j in range(len(field_wells)):
            if q[j] == 0:
                continue
            total += np.asarray(sol.drawdown(q[j], t_draws, s_draws, rec.r_by_well[j], t_days), dtype=float)
        results.append({"kind": rec.kind, "label": rec.label, **rec.detail,
                        **_summary(total, req.quantiles, req.thresholds_ft), "_draws": total})

    det = _deterministic(res, receptors)
    # Where the value the report currently states falls in this distribution. If the intake's T is the
    # conservative end of the declared spread rather than its middle, the reported number is already a
    # high percentile, and that is worth knowing before anyone reads the median as "the answer".
    for r, rec in zip(results, receptors, strict=True):
        r["key"] = receptor_key(rec.kind, rec.detail)
        point = det.get(r["key"])
        r["deterministic_ft"] = point
        r["deterministic_percentile"] = (None if point is None
                                         else float(np.mean(r["_draws"] <= point)))
    samples = [r.pop("_draws") for r in results]
    return {
        "aquifer": aquifer, "scenario_key": scenario["key"], "scenario_title": scenario["title"],
        "duration_days": t_days, "duration_label": scenario["duration_label"],
        "total_rate_gpm": scenario["total_rate_gpm"],
        "draws": req.draws, "seed": req.seed, "quantiles": list(req.quantiles),
        "thresholds_ft": list(req.thresholds_ft),
        "solution": sol.to_json(),
        "boundary_labels": [b.label for b in boundaries],
        "image_well_count": len(images),
        "parameters": {
            "t_ft2d": _param_summary(t_draws, unc.t_ft2d, params["t_ft2d"]),
            "s": _param_summary(s_draws, unc.s, params["s"]),
            "log_correlation": unc.log_correlation,
        },
        "receptors": results,
        "deterministic": det,
        # Kept out of the JSON (10,000 floats per receptor), handed back for the figure to plot.
        "_samples": samples,
        "notes": notes + [f["text"] for f in sol_flags] + list(_general_notes(req, results, det)),
    }


def _param_summary(draws, dist, fixed) -> dict:
    """The declaration and the sample, kept apart.

    `declared_*` is the input, and is what a caption or a table quotes. `sample_*` is what this particular
    set of draws produced, which is close to it but not it.
    """
    return {
        "declared": dist is not None,
        "kind": dist.kind if dist else None,
        "source": dist.source if dist else None,
        "intake_value": float(fixed),
        "declared_p10": declared_quantile(dist, 0.10) if dist else float(fixed),
        "declared_median": declared_quantile(dist, 0.50) if dist else float(fixed),
        "declared_p90": declared_quantile(dist, 0.90) if dist else float(fixed),
        "sample_median": float(np.median(draws)),
        "sample_p10": float(np.quantile(draws, 0.10)),
        "sample_p90": float(np.quantile(draws, 0.90)),
    }


def _receptors(project, intake, res, field_wells, aquifer, boundaries, group) -> list:
    """Where drawdown is reported: each pumped well, each registered well, and the property boundary."""
    from hydrostudy.analysis.boundaries import beyond
    cx, cy = pumping_center(group)
    out = []

    def distances(x, y):
        return np.array([max(math.hypot(x - w.x_ft, y - w.y_ft), w.r_w_ft) for w in field_wells])

    for pw in res["pumped_wells"]:
        w = next(x for x in field_wells if x.id == pw["id"])
        r = distances(w.x_ft, w.y_ft)
        # A well's own distance to itself is its evaluation radius, not zero.
        r[[i for i, f in enumerate(field_wells) if f.id == w.id]] = w.r_w_ft
        label = next((x.label for x in intake.all_wells if x.id == pw["id"]), pw["id"])
        out.append(_Receptor("pumped", label, {"well_id": pw["id"], "q_gpm": pw["q_gpm"],
                                               "r_w_ft": pw["r_w_ft"]}, r))

    for imp in res["nearby_impacts"]:
        if imp["drawdown_ft"] is None or imp["applicability"] != "same" or imp["is_system_well"]:
            continue
        n = next(x for x in project.artifacts["nearby_wells"] if x["map_id"] == imp["map_id"])
        if beyond(boundaries, n["x_ft"], n["y_ft"], cx, cy):
            continue
        out.append(_Receptor("registered", f"Map ID {imp['map_id']}",
                             {"map_id": imp["map_id"], "owner": imp["owner"],
                              "registration_no": imp["registration_no"] or None,
                              "distance_ft": imp["distance_ft"]},
                             distances(n["x_ft"], n["y_ft"])))
    return out


def receptor_key(kind: str, detail: dict) -> str:
    """A stable identity for a receptor: a well id or a map id, never a display name.

    `display_name` is free text and nothing requires it to be unique, so keying on it silently merges
    two like-named wells and hands each the other's number. Well ids and map ids are unique by schema.
    """
    return f"well:{detail['well_id']}" if kind == "pumped" else f"map:{detail['map_id']}"


def _deterministic(res, receptors) -> dict:
    """What the report currently states, so the interval can be read against it."""
    by_id = {p["id"]: p["total_ft"] for p in res["pumped_wells"]}
    by_map = {i["map_id"]: i["drawdown_ft"] for i in res["nearby_impacts"]}
    out = {}
    for rec in receptors:
        value = (by_id.get(rec.detail["well_id"]) if rec.kind == "pumped"
                 else by_map.get(rec.detail["map_id"]))
        out[receptor_key(rec.kind, rec.detail)] = value
    return out


def quantile_keys(quantiles) -> tuple[str, str, str]:
    """(lowest, most central, highest) of whatever quantiles were requested, as output keys.

    Anything narrating or plotting the result reads these. Hard-coding "0.1"/"0.9" made
    `--quantiles 0.05,0.5,0.95` - the invocation the runbook itself recommends - die with a KeyError.
    """
    qs = sorted(float(q) for q in quantiles)
    mid = min(qs, key=lambda q: abs(q - 0.5))
    return f"{qs[0]:g}", f"{mid:g}", f"{qs[-1]:g}"


def _ordinal(fraction: float) -> str:
    """A fraction as an ordinal percentile: 0.74 -> "74th". "74% percentile" is not English."""
    n = round(fraction * 100)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _general_notes(req, results, det):
    yield (f"{req.draws:,} draws with seed {req.seed}. Both are recorded so this interval can be "
           "reproduced exactly; a confidence interval nobody can re-derive is not evidence.")
    yield ("A quantile from a finite sample is itself an estimate, so each one is reported with its "
           "standard error. Do not quote an interval more precisely than that error allows.")
    off_centre = [r for r in results
                  if r.get("deterministic_percentile") is not None
                  and not 0.35 <= r["deterministic_percentile"] <= 0.65]
    if off_centre and len(off_centre) == len(results):
        pct = sum(r["deterministic_percentile"] for r in off_centre) / len(off_centre)
        where = "above" if pct > 0.5 else "below"
        yield (f"The drawdown the report currently states sits around the {_ordinal(pct)} percentile of this "
               f"distribution, {where} its middle, at every receptor. That is what happens when the "
               "intake's parameter is one end of the declared spread rather than its centre - which may "
               "be a deliberately conservative choice, but it means the median here is not the reported "
               "number and should not be quoted as a correction to it.")
    _, mid_k, high_k = quantile_keys(req.quantiles)
    worst = max((r for r in results if r["kind"] == "registered"),
                key=lambda r: r["quantiles"][high_k]["ft"], default=None)
    if worst:
        high = worst["quantiles"][high_k]["ft"]
        mid = worst["quantiles"][mid_k]["ft"]
        yield (f"The registered well most exposed to the parameter spread is {worst['label']}: "
               f"p{float(mid_k) * 100:g} of {mid:,.1f} ft against p{float(high_k) * 100:g} of "
               f"{high:,.1f} ft. The difference between those two is what the aquifer not being known "
               "precisely is worth at that well.")
    yield ("This propagates the parameter spreads that were declared, and nothing else. It says nothing "
           "about whether the Theis assumptions hold, whether the District's well database is complete, "
           "or whether the pumping schedule is what was modelled. A narrow interval here is not a "
           "statement that the answer is right.")


def _no_distribution_message(aquifer: str, params: dict) -> str:
    """Refusal that names what to supply, and points at the spread the intake may already imply."""
    msg = (f"no parameter uncertainty is declared for the {aquifer}. Add an `uncertainty` block to that "
           "aquifer with a distribution and its source, for example:\n"
           "    uncertainty:\n"
           "      t_ft2d: {kind: lognormal, p10: <low>, p90: <high>, source: \"<test or model>\"}\n"
           "This is deliberately not defaulted: a spread is a claim about how well the aquifer is known, "
           "and a guessed one would put an unsourceable number in the part of a report that is about how "
           "much to trust the other numbers.")
    mismatch = params.get("gam_mismatch")
    if mismatch:
        lo = min(mismatch["stated_t_ft2d"], mismatch["gam_t_ft2d"])
        hi = max(mismatch["stated_t_ft2d"], mismatch["gam_t_ft2d"])
        msg += (f"\n\nThis intake already carries two independent estimates of transmissivity: "
                f"{mismatch['stated_t_ft2d']:,.0f} ft2/day stated and {mismatch['gam_t_ft2d']:,.0f} ft2/day "
                f"from the model at the same cell. A p10 of {lo:,.0f} and a p90 of {hi:,.0f} would bracket "
                "them, and the reviewer may well want it wider than that. Adopting it is their call, not "
                "this tool's.")
    return msg
