import pytest

from hydrostudy.analysis.scenarios import max_production_days
from hydrostudy.geo.crs import LocalCRS, geodesic_distance_ft, parse_coordinate


def test_max_production_days_black_oak():
    assert max_production_days(29_000_000, 385).days == pytest.approx(52.31, abs=0.01)
    assert max_production_days(29_000_000, 735).days == pytest.approx(27.4, abs=0.01)


def test_max_production_cap_and_flags():
    d = max_production_days(1_000_000_000, 100)
    assert d.capped and d.days == 365 and d.flags
    d2 = max_production_days(100_000, 1000)
    assert d2.days < 1 and d2.flags


def test_parse_coordinates():
    assert parse_coordinate('30° 10\' 12.60"N', "lat") == pytest.approx(30.1701667, abs=1e-6)
    assert parse_coordinate('95° 34\' 41.15"W', "lon") == pytest.approx(-95.5781, abs=1e-4)
    assert parse_coordinate("95 34 41.15 W", "lon") == pytest.approx(-95.5781, abs=1e-4)
    assert parse_coordinate("-95.578056", "lon") == pytest.approx(-95.578056)
    assert parse_coordinate(30.17, "lat") == 30.17
    with pytest.raises(ValueError):
        parse_coordinate("abc")
    with pytest.raises(ValueError):
        parse_coordinate("100", "lat")


def test_local_crs_distance_matches_geodesic():
    lat2, lon2 = parse_coordinate('30° 10\' 12.60"N'), parse_coordinate('95° 34\' 41.15"W')
    crs = LocalCRS(lat2, lon2)
    x, y = crs.to_local(-95.578056, 30.170000)
    d = (x * x + y * y) ** 0.5
    assert d == pytest.approx(62, abs=1.5)                 # Well No. 1 is reported 62 ft away
    # 2-mile check
    lon_far, lat_far = -95.55, 30.19
    xf, yf = crs.to_local(lon_far, lat_far)
    assert (xf**2 + yf**2) ** 0.5 == pytest.approx(geodesic_distance_ft(lon2, lat2, lon_far, lat_far), rel=1e-3)
    lon_b, lat_b = crs.to_wgs84(x, y)
    assert lon_b == pytest.approx(-95.578056, abs=1e-7) and lat_b == pytest.approx(30.17, abs=1e-7)
