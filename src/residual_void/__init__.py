"""ResidualVoid – Lean Permanent Core + Cryptographic Hash Chain v2.0

Public API: ResidualVoid, ResidualNetworkManager, SecureNode,
            CoherentField, CoherentVoid, Residual.

Optional experimental layers (geometry / mind / Pi-Helix) remain
available as direct imports but are not loaded on the default path.
"""

from .core import (
    CoherentField,
    CoherentVoid,
    Residual,
    SecureNode,
    hierarchical_edge_extract_v2,
    schumann_carrier,
    pi_helix_drive,
)
from .merged import ResidualVoid
from .network import ResidualNetworkManager

__version__ = "2.0.0"
__all__ = [
    # Core lean API
    "ResidualVoid",
    "ResidualNetworkManager",
    "SecureNode",
    "CoherentField",
    "CoherentVoid",
    "Residual",
    # Pi-Helix DSP (optional – kept for backward compat)
    "hierarchical_edge_extract_v2",
    "schumann_carrier",
    "pi_helix_drive",
]

# Optional experimental layers – imported lazily to avoid mandatory dependencies
def _lazy_geometry():
    from .geometry import ResidualGeometry  # noqa: F401
    return ResidualGeometry

def _lazy_mind():
    from .mind import ResidualFieldMind  # noqa: F401
    return ResidualFieldMind

# Make them importable from the package for backward compat
try:
    from .geometry import ResidualGeometry
    from .mind import ResidualFieldMind
    __all__ += ["ResidualGeometry", "ResidualFieldMind"]
except ImportError:  # pragma: no cover
    pass

