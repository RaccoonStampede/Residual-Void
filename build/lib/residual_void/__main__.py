from __future__ import annotations

import argparse
import json
from typing import Optional

from . import __version__
from .core import SecureNode
from .merged import ResidualVoid


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ResidualVoid runtime bootstrap")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default=None, help="Optional config path")
    parser.add_argument("--demo", action="store_true", help="Run a lightweight smoke demo")
    args = parser.parse_args(argv)

    runtime = ResidualVoid(config_path=args.config)

    if args.demo:
        packet = SecureNode.lock_payload("hello residual void", secret=runtime.surface._secret)
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
