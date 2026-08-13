import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from residual_void import ResidualFieldMind, ResidualGeometry, ResidualNetworkManager, ResidualVoid


@pytest.fixture(autouse=True)
def seeded_numpy() -> None:
    np.random.seed(0)
    yield


@pytest.fixture
def runtime_config() -> dict:
    return {
        "environment": "development",
        "coherence": {"quorum_size": 2},
    }


@pytest.fixture
def runtime(runtime_config: dict) -> ResidualVoid:
    return ResidualVoid(secret="alpha", config=runtime_config)


@pytest.fixture
def geometry() -> ResidualGeometry:
    return ResidualGeometry(max_items=50, shell_count=5, dimensions=8)


@pytest.fixture
def mind(geometry: ResidualGeometry) -> ResidualFieldMind:
    return ResidualFieldMind(geometry=geometry)


@pytest.fixture
def network_manager() -> ResidualNetworkManager:
    return ResidualNetworkManager()
