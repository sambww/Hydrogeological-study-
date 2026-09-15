"""Generate SYNTHETIC aquifer-test series for the post-drilling example.

The public record gives only the endpoints of the real 36-hour test on Black Oak Well No. 1 (270 gpm, 364 -> 434.9 ft).
No test data for Well No. 2 are public, so the series below are generated from the Theis solution with the parameters
adopted in the pre-drilling report (T = 1,023 ft2/day, S = 3.36e-4, r_w = 0.5 ft) plus a small well-loss term and
measurement noise. They exist only to exercise the pipeline; replace them with field data for a real submittal."""

import csv
import math
from pathlib import Path

import numpy as np

T, S, RW = 1023.0, 3.36e-4, 0.5
C_LOSS = 2.0e-5          # ft per gpm^2 (well loss)
GPM_TO_CFD = 192.5
rng = np.random.default_rng(7)
here = Path(__file__).parent


def W(u):
    from scipy.special import exp1
    return exp1(u)


def theis(q, r, t_days):
    return q * GPM_TO_CFD / (4 * math.pi * T) * W(r * r * S / (4 * T * t_days))


# 1) constant-rate test: 385 gpm for 36 hours, readings on a log-spaced schedule
times = np.unique(np.concatenate([np.arange(1, 10, 1), np.arange(10, 100, 10), np.arange(100, 2161, 60), [2160]]))
with open(here / "test_cr_385gpm.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["elapsed_min", "water_level_ft", "rate_gpm", "phase"])
    swl = 352.0
    for t in times:
        s = theis(385, RW, t / 1440) + C_LOSS * 385**2 + rng.normal(0, 0.15)
        w.writerow([int(t), round(swl + s, 2), round(385 + rng.normal(0, 2), 0), "pumping"])
    # recovery for 12 hours after shutdown at 2160 min (residual drawdown = s(t) - s(t'))
    for tp in np.unique(np.concatenate([np.arange(1, 10, 1), np.arange(10, 100, 10), np.arange(100, 721, 60)])):
        t_total = 2160 + tp
        sp = theis(385, RW, t_total / 1440) - theis(385, RW, tp / 1440) + rng.normal(0, 0.1)
        w.writerow([int(t_total), round(swl + sp, 2), 0, "recovery"])

# 2) step test: 200, 300, 385 gpm, 120 min each (rate increments superposed)
steps = [(200, 120), (300, 120), (385, 120)]
with open(here / "test_step.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["elapsed_min", "drawdown_ft", "rate_gpm", "phase"])
    t_start = [0, 120, 240]
    rates = [200, 300, 385]
    for t in range(1, 361, 1):
        if t % 5 and t not in (120, 240, 360):
            continue
        s = 0.0
        q_now = 0
        for i, (q, dur) in enumerate(steps):
            if t > t_start[i]:
                dq = q - (rates[i - 1] if i else 0)
                s += theis(dq, RW, (t - t_start[i]) / 1440)
                q_now = q
        s += C_LOSS * q_now**2 + rng.normal(0, 0.1)
        w.writerow([t, round(s, 2), q_now, "pumping"])

# 3) synthetic LAS header (inventory only)
las = """~VERSION INFORMATION
 VERS.                 2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0
 WRAP.                  NO : ONE LINE PER DEPTH STEP
~WELL INFORMATION
 STRT.FT              0.0 : START DEPTH
 STOP.FT            780.0 : STOP DEPTH
 STEP.FT              0.5 : STEP
 NULL.            -999.25 : NULL VALUE
 WELL.     BLACK OAK WELL NO. 2 : WELL (SYNTHETIC EXAMPLE FILE)
~CURVE INFORMATION
 DEPT.FT                  : DEPTH
 GR  .GAPI                : GAMMA RAY
 SP  .MV                  : SPONTANEOUS POTENTIAL
 RES16.OHMM               : 16-INCH NORMAL RESISTIVITY
 RES64.OHMM               : 64-INCH NORMAL RESISTIVITY
~A  DEPT      GR      SP   RES16   RES64
    0.0    45.2   -12.1    18.5    22.0
    0.5    46.0   -12.3    18.9    22.4
    1.0    44.8   -12.0    19.2    22.9
"""
(here / "black_oak_2_openhole.las").write_text(las)
print("synthetic data written")
