"""ResidualVoid – Unified Production Runtime v2.1

Default runtime: hierarchical edge-nulling Pi-Helix, nested geometric shells,
Fibonacci placement, hierarchical message-passing (Laplacian/Fiedler),
fast/medium/deep imprint layers, ghost tax / ethical tilt / god-zone regulation,
binary residual path, and unlimited private mergers via ResidualNetworkManager.

Public API: ResidualVoid, ResidualNetworkManager, SecureNode,
            CoherentField, CoherentVoid, Residual.
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
from .ingestion import auto_segment, inject_document
from .persistence import PersistentVoid

__version__ = "2.2.0"
__all__ = [
    # Unified production API
    "ResidualVoid",
    "ResidualNetworkManager",
    "PersistentVoid",
    "SecureNode",
    "CoherentField",
    "CoherentVoid",
    "Residual",
    # Pi-Helix DSP
    "hierarchical_edge_extract_v2",
    "schumann_carrier",
    "pi_helix_drive",
    "auto_segment",
    "inject_document",
]


# Optional geometry/mind layers – available on default path in v2.1
try:
    from .geometry import ResidualGeometry
    __all__ += ["ResidualGeometry"]
except ImportError:  # pragma: no cover
    pass

try:
    from .mind import ResidualFieldMind
    __all__ += ["ResidualFieldMind"]
except ImportError:  # pragma: no cover
    pass
