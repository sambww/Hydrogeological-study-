import copy

import pytest
import yaml
from pydantic import ValidationError

from hydrostudy.schema.intake import Intake
from tests.conftest import ROOT


def _base():
    return yaml.safe_load((ROOT / "examples" / "black_oak_well_2" / "intake.yaml").read_text())


def test_example_validates():
    i = Intake.model_validate(_base())
    assert i.system_rate_gpm == 735
    assert i.proposed_wells[0].effective_r_w_ft() == 0.5


def test_default_r_w_from_borehole():
    d = _base()
    d["proposed_wells"][0].pop("r_w_ft")
    i = Intake.model_validate(d)
    assert i.proposed_wells[0].effective_r_w_ft() == pytest.approx(7.875 / 24)


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["proposed_wells"][0]["screen"].__setitem__(0, {"top_ft": 700, "bottom_ft": 900, "diameter_in": 6}), "exceeds total depth"),
    (lambda d: d["proposed_wells"][0]["casing"].__setitem__(0, {"top_ft": -2, "bottom_ft": 720, "diameter_in": 8.625}), "casing bottom"),
    (lambda d: d["proposed_wells"][0].__setitem__("lon", "95.578"), "negative"),
    (lambda d: d["proposed_wells"][0].__setitem__("aquifer", "Jasper"), "not defined"),
    (lambda d: d["existing_wells"][0].__setitem__("id", "W2"), "unique"),
    (lambda d: d["permit"].__setitem__("annual_volume_gal", -5), "greater than 0"),
])
def test_rejects_bad_intake(mutate, msg):
    d = copy.deepcopy(_base())
    mutate(d)
    with pytest.raises(ValidationError) as e:
        Intake.model_validate(d)
    assert msg.lower() in str(e.value).lower()
