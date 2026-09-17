"""Variable pumping rates by superposition in time.

Every scenario elsewhere in this package pumps at one constant rate, which is what the District asks
for and is the conservative case. Real wells do not: they cycle with demand, a municipal system leans
on one well in summer, and a step-drawdown test is a rate schedule by definition. Recovery is the same
mechanism - the rate steps down to zero and the residual drawdown is what is left of the earlier steps.

A rate change is a new well switched on at the moment of the change, pumping the *difference*:

    s(t) = sum over changes i of  (Q_i - Q_(i-1)) * f(r, t - t_i)   for every t_i < t

with Q before the first step taken as zero. `f` is any single-well drawdown solution, so this works
unchanged for Theis or for the leaky Hantush-Jacob solution.

Three exact identities pin it, and `tests/test_schedule.py` asserts all three: a single step reproduces
the constant-rate solution it was built from; pumping then stopping reproduces the Theis recovery
expression; and the whole thing is linear, so scaling every rate scales the drawdown.

**Not yet on the report path.** Nothing in the pipeline calls this: the District asks for constant-rate
scenarios and those stay the reported case. It is here as the piece a duty-cycle or step-test scenario
needs, tested to the same standard as the rest so that work does not start from unverified arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydrostudy.analysis.theis import theis_drawdown


@dataclass(frozen=True)
class RateStep:
    """A rate that begins at `start_day` and continues until the next step."""

    start_day: float
    rate_gpm: float

    def __post_init__(self):
        if self.start_day < 0:
            raise ValueError("a rate step cannot start before time zero")


def normalize(steps) -> list[RateStep]:
    """Sorted, with coincident and repeated rates collapsed. Rejects duplicate start times."""
    ordered = sorted(steps, key=lambda s: s.start_day)
    starts = [s.start_day for s in ordered]
    if len(set(starts)) != len(starts):
        raise ValueError("two rate steps start at the same time; give one rate per change")
    out: list[RateStep] = []
    for s in ordered:
        if out and out[-1].rate_gpm == s.rate_gpm:
            continue                      # a "change" to the same rate is not a change
        out.append(s)
    return out


def rate_at(steps, t_days: float) -> float:
    """The rate in force at a moment; zero before the first step."""
    rate = 0.0
    for s in normalize(steps):
        if s.start_day <= t_days:
            rate = s.rate_gpm
        else:
            break
    return rate


def volume_gal(steps, t_days: float) -> float:
    """Total pumped up to `t_days`, in gallons. What a permit is measured against."""
    from hydrostudy.units import MIN_PER_DAY
    ordered = normalize(steps)
    total = 0.0
    for i, s in enumerate(ordered):
        if s.start_day >= t_days:
            break
        end = min(ordered[i + 1].start_day if i + 1 < len(ordered) else t_days, t_days)
        total += s.rate_gpm * MIN_PER_DAY * (end - s.start_day)
    return total


def schedule_drawdown(steps, t_ft2d: float, s_storativity: float, r_ft, t_days, solution=None):
    """Drawdown from a rate schedule at radius r and time t.

    `solution(q_gpm, t_ft2d, s, r_ft, t_days)` defaults to Theis; pass
    `functools.partial(leaky_drawdown, leakance=...)`-style callables for other solutions.
    """
    fn = solution or theis_drawdown
    ordered = normalize(steps)
    if not ordered:
        return np.zeros(np.broadcast(np.asarray(r_ft, dtype=float),
                                     np.asarray(t_days, dtype=float)).shape)
    r = np.asarray(r_ft, dtype=float)
    t = np.asarray(t_days, dtype=float)
    total = np.zeros(np.broadcast(r, t).shape, dtype=float)
    previous = 0.0
    for step in ordered:
        delta = step.rate_gpm - previous
        previous = step.rate_gpm
        if delta == 0:
            continue
        elapsed = t - step.start_day
        active = elapsed > 0
        if not np.any(active):
            continue
        # Only evaluate where this step has started; `elapsed <= 0` is not a valid time for the solution.
        # The difference is handed to the solution as its rate rather than scaled afterwards, so this
        # does not quietly assume the solution is linear in Q beyond wherever it actually is.
        safe = np.where(active, elapsed, 1.0)
        total = total + np.where(active, fn(delta, t_ft2d, s_storativity, r, safe), 0.0)
    return total


def residual_drawdown(q_gpm: float, stop_day: float, t_ft2d: float, s: float, r_ft, t_days,
                      solution=None):
    """Convenience for the commonest schedule: pump `q_gpm` until `stop_day`, then stop.

    This is exactly what a recovery test measures, and is `schedule_drawdown` with two steps.
    """
    return schedule_drawdown([RateStep(0.0, q_gpm), RateStep(stop_day, 0.0)],
                             t_ft2d, s, r_ft, t_days, solution)
