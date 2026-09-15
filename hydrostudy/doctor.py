"""`hydrostudy doctor`: environment checks (packages, LibreOffice Writer, optional extras, public data hosts)."""

from __future__ import annotations

import importlib
import sys
import urllib.error
import urllib.request

REQUIRED = ["numpy", "scipy", "matplotlib", "shapely", "pyproj", "pandas", "pydantic", "yaml", "jinja2", "docx"]
OPTIONAL = {"requests": "connectors (scripts/fetch_public_data.py)", "flopy": "GAM sampling (scripts/build_gam_lookup.py)",
            "pytest": "test suite"}
HOSTS = [
    ("TWDB groundwater data", "https://www.twdb.texas.gov/groundwater/data/gwdbrpt.asp"),
    ("TWDB groundwater data viewer", "https://www3.twdb.texas.gov/apps/waterdatainteractive/groundwaterdataviewer"),
    ("USGS publications (HAGM archive)", "https://pubs.usgs.gov/sir/2012/5154/"),
    ("USGS elevation point service", "https://epqs.nationalmap.gov/v1/json?x=-95.578&y=30.170&units=Feet&wkid=4326"),
    ("USGS NHD map service", "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer?f=json"),
    ("TCEQ Drinking Water Viewer", "https://dwv.tceq.texas.gov/"),
    ("Lone Star GCD", "https://lonestargcd.org/"),
    ("Montgomery County open data (parcels)", "https://data-moco.opendata.arcgis.com/"),
]


def _check_packages():
    rows = []
    for m in REQUIRED:
        try:
            mod = importlib.import_module(m)
            rows.append(("PASS", f"package {m}", getattr(mod, "__version__", "")))
        except ImportError:
            rows.append(("FAIL", f"package {m}", "missing: pip install -e .[dev]"))
    for m, why in OPTIONAL.items():
        try:
            mod = importlib.import_module(m)
            rows.append(("PASS", f"optional {m}", getattr(mod, "__version__", "")))
        except ImportError:
            rows.append(("WARN", f"optional {m}", f"missing; needed for {why}"))
    return rows


def _check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 10)
    return [("PASS" if ok else "FAIL", "python", f"{v.major}.{v.minor}.{v.micro}" + ("" if ok else " (need 3.10+)"))]


def _check_libreoffice():
    from hydrostudy.report.pdf import _exe, soffice_available
    if not _exe():
        return [("WARN", "LibreOffice", "not installed; DOCX only (install libreoffice-writer for PDF export)")]
    if soffice_available():
        return [("PASS", "LibreOffice Writer", "DOCX to PDF conversion works")]
    return [("WARN", "LibreOffice Writer", "installed without the Writer component; PDF export disabled")]


def _check_hosts(timeout=10):
    rows = []
    for name, url in HOSTS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hydrostudy-doctor"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                rows.append(("PASS", f"reach {name}", f"HTTP {r.status}"))
        except urllib.error.HTTPError as e:
            rows.append(("PASS" if e.code < 500 else "WARN", f"reach {name}", f"HTTP {e.code}"))
        except Exception as e:  # noqa: BLE001 - any transport failure is reported, not raised
            rows.append(("WARN", f"reach {name}", f"unreachable ({type(e).__name__}); connectors will not work from this machine"))
    return rows


def run(network: bool = False) -> list[tuple[str, str, str]]:
    rows = _check_python() + _check_packages() + _check_libreoffice()
    if network:
        rows += _check_hosts()
    return rows


def main(network: bool = False) -> int:
    rows = run(network)
    width = max(len(r[1]) for r in rows)
    for status, name, detail in rows:
        print(f"[{status}] {name.ljust(width)}  {detail}")
    fails = [r for r in rows if r[0] == "FAIL"]
    warns = [r for r in rows if r[0] == "WARN"]
    print()
    if fails:
        print(f"{len(fails)} problem(s) must be fixed before running the pipeline.")
        return 1
    print(f"Environment OK ({len(warns)} warning(s)). Next: .venv/bin/pytest, then hydrostudy run examples/black_oak_well_2")
    if not network:
        print("Add --network to test reachability of the public data hosts used by the connectors.")
    return 0
