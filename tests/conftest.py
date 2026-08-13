import pytest
import numpy as np
from src.residual_void.core import CoherentVoid, SecureNode, hierarchical_edge_extract_v2, schumann_carrier
from src.residual_void.geometry import ResidualGeometry, SHELL_LABELS
from src.residual_void.mind import ResidualFieldMind
from src.residual_void.merged import ResidualVoid
from src.residual_void.network import ResidualNetworkManager


@pytest.fixture
def geometry():
    """Create a fresh ResidualGeometry instance."""
    return ResidualGeometry(max_items=200, shell_count=4)


@pytest.fixture
def mind(geometry):
    """Create a fresh ResidualFieldMind instance."""
    return ResidualFieldMind(geometry=geometry)


@pytest.fixture
def coherent_void():
    """Create a fresh CoherentVoid instance."""
    return CoherentVoid(secret="test-secret-1234567890abcdef")


@pytest.fixture
def residual_void():
    """Create a fresh ResidualVoid instance."""
    return ResidualVoid(secret="test-secret-1234567890abcdef")


@pytest.fixture
def network_manager():
    """Create a fresh ResidualNetworkManager instance."""
    return ResidualNetworkManager()


@pytest.fixture
def test_signal():
    """Generate a test signal with Schumann core + Edge bands + noise."""
    fs = 8000.0
    t = np.linspace(0, 1.0, int(fs))
    measured = (
        0.6 * schumann_carrier(t)
        + 0.08 * np.sin(2 * np.pi * 42 * t)  # Edge: 42 Hz
        + 0.05 * np.sin(2 * np.pi * 180 * t)  # Edge: 180 Hz
        + 0.03 * np.sin(2 * np.pi * 850 * t)  # Edge: 850 Hz
        + 0.04 * np.random.randn(len(t))
    )
    return measured, fs
