"""ResidualVoid – Unified Production Runtime v2.3

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
    HyperSeed,
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
from .dynamics import (
    LINEAR_RESPONSE_COEFFICIENT,
    MODULAR_LYAPUNOV_EXPONENT,
    MODULAR_WINDOW_HIGH,
    MODULAR_WINDOW_LOW,
    PureHarnessConfig,
    PureHarnessDynamics,
    ResidualFlowResult,
)
from .server import (
    connect_to_residualvoid,
    create_http_server,
    discover_and_connect,
    serve_residual_void,
    start_mdns_advertisement,
)

__version__ = "2.3.0"
__all__ = [
    # Unified production API
    "ResidualVoid",
    "ResidualNetworkManager",
    "PersistentVoid",
    "SecureNode",
    "CoherentField",
    "CoherentVoid",
    "HyperSeed",
    "Residual",
    # Pi-Helix DSP
    "hierarchical_edge_extract_v2",
    "schumann_carrier",
    "pi_helix_drive",
    "auto_segment",
    "inject_document",
    "create_http_server",
    "serve_residual_void",
    "start_mdns_advertisement",
    "discover_and_connect",
    "connect_to_residualvoid",
    "LINEAR_RESPONSE_COEFFICIENT",
    "MODULAR_LYAPUNOV_EXPONENT",
    "MODULAR_WINDOW_LOW",
    "MODULAR_WINDOW_HIGH",
    "PureHarnessConfig",
    "PureHarnessDynamics",
    "ResidualFlowResult",
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
