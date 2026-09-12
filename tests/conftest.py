import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def black_oak_project():
    from hydrostudy.pipeline import Project
    p = Project(ROOT / "examples" / "black_oak_well_2")
    p.run_analysis()
    return p
