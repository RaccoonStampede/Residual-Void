from __future__ import annotations

import hmac
import time
from typing import Any, Dict, Optional

from .core import SecureNode
from .merged import ResidualVoid


class ResidualNetworkManager:
    def __init__(self) -> None:
        self._networks: Dict[str, Dict[str, Any]] = {}
        self._seen_nonces: Dict[str, Dict[str, int]] = {}
        self._key_history: Dict[str, Dict[str, Any]] = {}

    def create_network(self, name: str, secret: str, config: Optional[Dict[str, Any]] = None) -> ResidualVoid:
        if name in self._networks:
            raise ValueError(f"Network {name!r} already exists")

        runtime = ResidualVoid(secret=secret, config=config)
        self._networks[name] = {"secret": secret, "runtime": runtime}
        self._seen_nonces.setdefault(name, {})
        self._key_history.setdefault(name, {"previous_secret": None, "grace_seconds": 300})
        return runtime

    def set_key_rotation(self, name: str, active_secret: str, previous_secret: Optional[str] = None, grace_seconds: int = 300) -> None:
        if name not in self._networks:
            raise ValueError(f"Network {name!r} does not exist")
        self._networks[name]["secret"] = active_secret
        self._key_history[name] = {
            "previous_secret": previous_secret,
            "grace_seconds": grace_seconds,
        }

    def remove_network(self, name: str, secret: str) -> bool:
        record = self._networks.get(name)
        if not record:
            return False
        if not hmac.compare_digest(record["secret"], secret):
            return False
        del self._networks[name]
        self._seen_nonces.pop(name, None)
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

    def validate_message(self, name: str, secret: str, payload: Dict[str, Any]) -> bool:
        record = self._networks.get(name)
        if not record:
            return False

        history = self._key_history.get(name, {"previous_secret": None, "grace_seconds": 300})
        previous_secret = history.get("previous_secret")
        grace_seconds = int(history.get("grace_seconds", 300))
        active_secret = record["secret"]

        if not hmac.compare_digest(active_secret, secret) and not (
            previous_secret and hmac.compare_digest(previous_secret, secret)
        ):
            return False

        current_payload_time = payload.get("iat")
        if current_payload_time is None:
            current_payload_time = payload.get("timestamp")
        now = int(time.time())

        if previous_secret and hmac.compare_digest(previous_secret, secret):
            if not isinstance(current_payload_time, int):
                return False
            if current_payload_time < now - grace_seconds:
                return False

        if not SecureNode.verify_payload(payload, active_secret, previous_secret=previous_secret):
            return False

        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            return False

        seen = self._seen_nonces.setdefault(name, {})
        for previous_nonce in list(seen):
            if seen[previous_nonce] <= now:
                del seen[previous_nonce]

        if nonce in seen:
            return False

        exp = payload.get("exp")
        if not isinstance(exp, int):
            return False

        seen[nonce] = max(now, exp)
        return True

    def status(self, name: Optional[str] = None, secret: Optional[str] = None) -> Dict[str, Any]:
        if name is None:
            return {"network_count": len(self._networks), "networks": self.list_networks()}

        if secret is None:
            raise ValueError("secret is required when requesting status for one network")

        runtime = self.get_network(name, secret)
        if runtime is None:
            return {"error": "network not found or unauthorized"}
        return runtime.status()
