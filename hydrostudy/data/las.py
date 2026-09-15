"""Minimal LAS 2.0 header reader for inventorying geophysical logs (version, well, curve sections only)."""

from __future__ import annotations

import re
from pathlib import Path

_LINE = re.compile(r"^\s*([^.\s]+)\s*\.([^\s:]*)\s*(.*?)\s*:\s*(.*)$")


def read_las_header(path: str | Path) -> dict:
    """Return {'version', 'wrap', 'null', 'strt', 'stop', 'step', 'well': {...}, 'curves': [{mnemonic, unit, description}]}.
    Data rows are counted but not parsed."""
    out = {"path": str(path), "version": None, "wrap": None, "null": None, "strt": None, "stop": None, "step": None,
           "well": {}, "curves": [], "n_data_rows": 0, "ok": False, "error": None}
    section = None
    try:
        with open(path, encoding="latin-1", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("~"):
                    section = line[1].upper()
                    continue
                if section == "A":
                    out["n_data_rows"] += 1
                    continue
                m = _LINE.match(line)
                if not m:
                    continue
                mnem, unit, value, desc = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
                if section == "V":
                    if mnem == "VERS":
                        out["version"] = value
                    elif mnem == "WRAP":
                        out["wrap"] = value
                elif section == "W":
                    out["well"][mnem] = {"unit": unit, "value": value, "description": desc}
                    if mnem == "STRT":
                        out["strt"] = _f(value)
                    elif mnem == "STOP":
                        out["stop"] = _f(value)
                    elif mnem == "STEP":
                        out["step"] = _f(value)
                    elif mnem == "NULL":
                        out["null"] = _f(value)
                elif section == "C":
                    out["curves"].append({"mnemonic": mnem, "unit": unit, "description": desc})
        out["ok"] = bool(out["curves"])
    except OSError as e:
        out["error"] = str(e)
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
