"""Coordinate parsing and a local azimuthal-equidistant projection in US survey feet.

All distances, grids and figures use a local AEQD CRS centered on the project site, so no state-plane
zone is hard-coded (Montgomery County is Texas Central; neighbors are South Central)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyproj import Geod, Transformer

_DMS = re.compile(
    r"""^\s*(-?\d+(?:\.\d+)?)\s*[°º:\s]\s*(\d+(?:\.\d+)?)?\s*['′:\s]?\s*(\d+(?:\.\d+)?)?\s*["″]?\s*([NSEWnsew])?\s*$"""
)


def parse_coordinate(value, kind: str | None = None) -> float:
    """Accept decimal degrees (float or str) or DMS strings like 30° 10' 12.60"N / 95 34 41.15 W.
    `kind` = 'lat' or 'lon' enables range checks. West and South are returned negative."""
    if isinstance(value, (int, float)):
        deg = float(value)
    else:
        s = str(value).strip().replace("’", "'").replace("”", '"').replace("″", '"').replace("′", "'")
        try:
            deg = float(s)
        except ValueError:
            m = _DMS.match(s)
            if not m:
                raise ValueError(f"unrecognized coordinate: {value!r}") from None
            d = float(m.group(1))
            mi = float(m.group(2) or 0)
            se = float(m.group(3) or 0)
            hemi = (m.group(4) or "").upper()
            sign = -1.0 if d < 0 else 1.0
            deg = sign * (abs(d) + mi / 60.0 + se / 3600.0)
            if hemi in ("S", "W"):
                deg = -abs(deg)
    if kind == "lat" and not -90 <= deg <= 90:
        raise ValueError(f"latitude out of range: {deg}")
    if kind == "lon" and not -180 <= deg <= 180:
        raise ValueError(f"longitude out of range: {deg}")
    return deg


def format_dms(deg: float, kind: str) -> str:
    hemi = ("N" if deg >= 0 else "S") if kind == "lat" else ("E" if deg >= 0 else "W")
    a = abs(deg)
    d = int(a)
    m = int((a - d) * 60)
    s = (a - d - m / 60) * 3600
    return f"{d}° {m:02d}' {s:05.2f}\" {hemi}"


@dataclass
class LocalCRS:
    """Azimuthal equidistant projection centered on (lat0, lon0), units US survey feet."""

    lat0: float
    lon0: float

    def __post_init__(self):
        self.proj4 = (
            f"+proj=aeqd +lat_0={self.lat0} +lon_0={self.lon0} +datum=NAD83 +units=us-ft +no_defs"
        )
        self._fwd = Transformer.from_crs("EPSG:4326", self.proj4, always_xy=True)
        self._inv = Transformer.from_crs(self.proj4, "EPSG:4326", always_xy=True)

    def to_local(self, lon, lat):
        return self._fwd.transform(lon, lat)

    def to_wgs84(self, x_ft, y_ft):
        return self._inv.transform(x_ft, y_ft)


_GEOD = Geod(ellps="GRS80")


def geodesic_distance_ft(lon1, lat1, lon2, lat2) -> float:
    """Ellipsoidal distance in US survey feet (cross-check for the local projection)."""
    _, _, m = _GEOD.inv(lon1, lat1, lon2, lat2)
    return m / 0.3048006096012192
