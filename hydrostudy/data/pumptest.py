"""Aquifer-test data files: load and normalize to elapsed minutes and drawdown.

CSV columns: `elapsed_min` plus either `drawdown_ft` or `water_level_ft` (ft bgl). Optional: `rate_gpm` per row,
`phase` (pumping|recovery), `t_since_stop_min` for recovery rows."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


class TestSeries:
    def __init__(self, elapsed_min, drawdown_ft, rate_gpm=None, phase=None, t_since_stop_min=None, source=""):
        self.elapsed_min = np.asarray(elapsed_min, dtype=float)
        self.drawdown_ft = np.asarray(drawdown_ft, dtype=float)
        self.rate_gpm = None if rate_gpm is None else np.asarray(rate_gpm, dtype=float)
        self.phase = phase
        self.t_since_stop_min = None if t_since_stop_min is None else np.asarray(t_since_stop_min, dtype=float)
        self.source = source

    @property
    def n(self):
        return len(self.elapsed_min)

    def pumping(self):
        if self.phase is None:
            if self.t_since_stop_min is None:
                return self
            # Mirror `recovery()`: rows marked only by t_since_stop_min must be excluded here, or recovery data
            # would be fitted as part of the drawdown curve.
            m = ~(np.isfinite(self.t_since_stop_min) & (self.t_since_stop_min > 0))
            return self._subset(m)
        m = np.array([str(p).lower() != "recovery" for p in self.phase])
        return self._subset(m)

    def recovery(self):
        if self.phase is None:
            # `phase` is documented as optional, so a recovery series identified only by t_since_stop_min must still
            # be found; otherwise the test silently goes unanalysed and the report says it could not be analysed.
            if self.t_since_stop_min is None:
                return None
            m = np.isfinite(self.t_since_stop_min) & (self.t_since_stop_min > 0)
        else:
            m = np.array([str(p).lower() == "recovery" for p in self.phase])
        return self._subset(m) if m.any() else None

    def _subset(self, m):
        return TestSeries(self.elapsed_min[m], self.drawdown_ft[m],
                          None if self.rate_gpm is None else self.rate_gpm[m],
                          None if self.phase is None else [p for p, k in zip(self.phase, m, strict=True) if k],
                          None if self.t_since_stop_min is None else self.t_since_stop_min[m], self.source)

    def rate_variation(self):
        """Max relative deviation of the row-wise rate from its mean (None if rates not recorded)."""
        if self.rate_gpm is None:
            return None
        r = self.rate_gpm[np.isfinite(self.rate_gpm)]
        if len(r) == 0 or r.mean() == 0:
            return None
        return float(np.max(np.abs(r - r.mean())) / r.mean())


def load_test_series(path: str | Path, swl_ft: float | None) -> TestSeries:
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    if "elapsed_min" not in cols:
        raise ValueError(f"{path}: column elapsed_min is required")
    t = df[cols["elapsed_min"]].astype(float).to_numpy()
    if "drawdown_ft" in cols:
        s = df[cols["drawdown_ft"]].astype(float).to_numpy()
    elif "water_level_ft" in cols:
        if swl_ft is None:
            raise ValueError(f"{path}: water_level_ft given but no static water level to reference")
        s = df[cols["water_level_ft"]].astype(float).to_numpy() - swl_ft
    else:
        raise ValueError(f"{path}: need drawdown_ft or water_level_ft")
    rate = df[cols["rate_gpm"]].astype(float).to_numpy() if "rate_gpm" in cols else None
    phase = df[cols["phase"]].astype(str).tolist() if "phase" in cols else None
    tss = df[cols["t_since_stop_min"]].astype(float).to_numpy() if "t_since_stop_min" in cols else None
    order = np.argsort(t, kind="stable")
    return TestSeries(t[order], s[order], None if rate is None else rate[order],
                      None if phase is None else [phase[i] for i in order], None if tss is None else tss[order],
                      source=str(path))
