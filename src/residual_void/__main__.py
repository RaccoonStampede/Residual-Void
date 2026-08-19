from __future__ import annotations

import argparse
import json
from typing import Optional

from . import __version__
from .core import SecureNode
from .merged import ResidualVoid
from .network import ResidualNetworkManager
from .server import serve_residual_void


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="ResidualVoid unified production runtime bootstrap"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default=None, help="Optional config path")
    parser.add_argument("--demo", action="store_true", help="Run a smoke demo (single-node)")
    parser.add_argument(
        "--network-demo",
        action="store_true",
        help="Run a multi-network smoke demo via ResidualNetworkManager",
    )
    parser.add_argument("--serve", action="store_true", help="Run HTTP service")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host for --serve")
    parser.add_argument("--port", type=int, default=7700, help="HTTP bind port for --serve")
    parser.add_argument(
        "--service-name",
        default="ResidualVoid",
        help="mDNS service instance name for --serve",
    )
    parser.add_argument(
        "--snapshot",
        default="void_snapshot.json",
        help="Path to the persistent snapshot file (loaded on boot, saved via POST /snapshot)",
    )
    args = parser.parse_args(argv)

    if args.network_demo:
        mgr = ResidualNetworkManager()
        mgr.create_network("line_a", secret="secret-a", initial_nodes=["node_1"])
        mgr.create_network("line_b", secret="secret-b", initial_nodes=["node_2"])
        node = mgr.get_node("line_a", "node_1")
        node.lock_text("NETWORK::DEMO::OK", domain="general")
        result = {
            "networks": mgr.list_networks(),
            "line_a_status": mgr.network_status("line_a"),
        }
        print(json.dumps(result, indent=2))
        return 0

    runtime = ResidualVoid(config_path=args.config)

    if args.serve:
        import os
        snapshot_path = args.snapshot
        if os.path.exists(snapshot_path):
            try:
                runtime.load_snapshot_file(snapshot_path)
                snap_status = runtime.status()
                print(
                    f"[ResidualVoid] Restored snapshot from '{snapshot_path}' "
                    f"({snap_status['void'].get('residual_count', '?')} residuals)"
                )
            except Exception as exc:
                print(f"[ResidualVoid] WARNING: failed to restore snapshot '{snapshot_path}': {exc}")
        serve_residual_void(
            host=args.host,
            port=args.port,
            runtime=runtime,
            service_name=args.service_name,
            snapshot_path=snapshot_path,
        )
        return 0

    if args.demo:
        packet = SecureNode.lock_payload("hello residual void", secret=runtime._secret_str)
        lock_id = runtime.authenticated_ingest_lock(packet)
        if lock_id:
            runtime.confirm(lock_id)
        projection = runtime.project("hello")
        print(json.dumps({"status": runtime.status(), "projection": projection}, indent=2))
        return 0

    print(json.dumps(runtime.status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
