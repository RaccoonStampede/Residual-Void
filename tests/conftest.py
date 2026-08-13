import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from residual_void import CoherentVoid, ResidualFieldMind, ResidualGeometry, ResidualNetworkManager, ResidualVoid
from residual_void.core import schumann_carrier


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
    return ResidualGeometry(max_items=200, shell_count=5, dimensions=8)


@pytest.fixture
def mind(geometry: ResidualGeometry) -> ResidualFieldMind:
    return ResidualFieldMind(geometry=geometry)


@pytest.fixture
def coherent_void() -> CoherentVoid:
    return CoherentVoid(secret="test-secret-1234567890abcdef")


@pytest.fixture
def residual_void() -> ResidualVoid:
    return ResidualVoid(secret="test-secret-1234567890abcdef")


@pytest.fixture
def network_manager() -> ResidualNetworkManager:
    return ResidualNetworkManager()


@pytest.fixture
def test_signal():
    fs = 8000.0
    t = np.linspace(0, 1.0, int(fs))
    measured = (
        0.6 * schumann_carrier(t)
        + 0.08 * np.sin(2 * np.pi * 42 * t)
        + 0.05 * np.sin(2 * np.pi * 180 * t)
        + 0.03 * np.sin(2 * np.pi * 850 * t)
        + 0.04 * np.random.randn(len(t))
    )
    return measured, fs
