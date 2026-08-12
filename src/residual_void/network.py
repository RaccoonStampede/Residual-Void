from __future__ import annotations

import hmac
from typing import Any, Dict, Optional

from .merged import ResidualVoid


class ResidualNetworkManager:
    def __init__(self) -> None:
        self._networks: Dict[str, Dict[str, Any]] = {}

    def create_network(self, name: str, secret: str, config: Optional[Dict[str, Any]] = None) -> ResidualVoid:
        if name in self._networks:
            raise ValueError(f"Network {name!r} already exists")

        runtime = ResidualVoid(secret=secret, config=config)
        self._networks[name] = {"secret": secret, "runtime": runtime}
        return runtime

    def remove_network(self, name: str, secret: str) -> bool:
        record = self._networks.get(name)
        if not record:
            return False
        if not hmac.compare_digest(record["secret"], secret):
            return False
        del self._networks[name]
        return True

    def list_networks(self):
        return sorted(self._networks.keys())

    def get_network(self, name: str, secret: str) -> Optional[ResidualVoid]:
        record = self._networks.get(name)
        if not record:
            return None
        if not hmac.compare_digest(record["secret"], secret):
            return None
        return record["runtime"]

    def status(self, name: Optional[str] = None, secret: Optional[str] = None) -> Dict[str, Any]:
        if name is None:
            return {"network_count": len(self._networks), "networks": self.list_networks()}

        if secret is None:
            raise ValueError("secret is required when requesting status for one network")

        runtime = self.get_network(name, secret)
        if runtime is None:
            return {"error": "network not found or unauthorized"}
        return runtime.status()
