from __future__ import annotations

import hmac
import time
import threading
from typing import Any, Dict, List, Optional

from .core import SecureNode
from .merged import ResidualVoid


class ResidualNetworkManager:
    """Multi-network manager with isolated secrets, key rotation, and nonce replay protection."""
    
    def __init__(self) -> None:
        self._networks: Dict[str, Dict[str, Any]] = {}
        self._seen_nonces: Dict[str, Dict[str, int]] = {}
        self._key_history: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create_network(
        self,
        name: str,
        secret: str,
        config: Optional[Dict[str, Any]] = None,
        initial_nodes: Optional[List[str]] = None,
    ) -> ResidualVoid:
        """Create isolated network with optional initial nodes."""
        with self._lock:
            if name in self._networks:
                raise ValueError(f"Network {name!r} already exists")

            runtime = ResidualVoid(secret=secret, config=config)
            nodes = {}
            if initial_nodes:
                for nid in initial_nodes:
                    nodes[nid] = SecureNode()
            
            self._networks[name] = {
                "secret": secret,
                "runtime": runtime,
                "nodes": nodes,
                "created_at": time.time(),
            }
            self._seen_nonces.setdefault(name, {})
            self._key_history.setdefault(name, {"previous_secret": None, "grace_seconds": 300})
            return runtime

    def add_node(self, network_name: str, node_id: str) -> SecureNode:
        """Add a node to an existing network."""
        with self._lock:
            if network_name not in self._networks:
                raise ValueError(f"Network {network_name!r} does not exist")
            entry = self._networks[network_name]
            if node_id in entry["nodes"]:
                return entry["nodes"][node_id]
            node = SecureNode()
            entry["nodes"][node_id] = node
            return node

    def get_node(self, network_name: str, node_id: str) -> Optional[SecureNode]:
        """Get node from network."""
        with self._lock:
            entry = self._networks.get(network_name)
            if not entry:
                return None
            return entry["nodes"].get(node_id)

    def list_nodes(self, network_name: str) -> List[str]:
        """List all nodes in a network."""
        with self._lock:
            entry = self._networks.get(network_name)
            if not entry:
                return []
            return list(entry["nodes"].keys())

    def set_key_rotation(
        self,
        name: str,
        active_secret: str,
        previous_secret: Optional[str] = None,
        grace_seconds: int = 300,
    ) -> None:
        """Rotate keys with grace period for old secret."""
        with self._lock:
            if name not in self._networks:
                raise ValueError(f"Network {name!r} does not exist")
            self._networks[name]["secret"] = active_secret
            self._key_history[name] = {
                "previous_secret": previous_secret,
                "grace_seconds": grace_seconds,
            }

    def remove_network(self, name: str, secret: str) -> bool:
        """Remove network (requires correct secret)."""
        with self._lock:
            record = self._networks.get(name)
            if not record:
                return False
            if not hmac.compare_digest(record["secret"], secret):
                return False
            del self._networks[name]
            self._seen_nonces.pop(name, None)
            self._key_history.pop(name, None)
            return True

    def list_networks(self) -> List[str]:
        """List all network names."""
        with self._lock:
            return sorted(self._networks.keys())

    def get_network(self, name: str, secret: str) -> Optional[ResidualVoid]:
        """Get network runtime (requires correct secret)."""
        with self._lock:
            record = self._networks.get(name)
            if not record:
                return None
            if not hmac.compare_digest(record["secret"], secret):
                return None
            return record["runtime"]

    def validate_message(self, name: str, secret: str, payload: Dict[str, Any]) -> bool:
        """Validate message with replay protection and key rotation grace period."""
        with self._lock:
            record = self._networks.get(name)
            if not record:
                return False

            history = self._key_history.get(name, {"previous_secret": None, "grace_seconds": 300})
            previous_secret = history.get("previous_secret")
            grace_seconds = int(history.get("grace_seconds", 300))
            active_secret = record["secret"]

            # Check if secret matches active or previous
            if not hmac.compare_digest(active_secret, secret) and not (
                previous_secret and hmac.compare_digest(previous_secret, secret)
            ):
                return False

            # Verify payload signature
            if not SecureNode.verify_payload(
                payload, active_secret, previous_secret=previous_secret
            ):
                return False

            # Replay protection: check nonce
            nonce = payload.get("nonce")
            if not isinstance(nonce, str) or not nonce:
                return False

            seen = self._seen_nonces.setdefault(name, {})
            now = int(time.time())

            # Clean up expired nonces
            for previous_nonce in list(seen):
                if seen[previous_nonce] <= now:
                    del seen[previous_nonce]

            # Check if nonce already seen (replay attack)
            if nonce in seen:
                return False

            # Validate timestamp
            current_payload_time = payload.get("iat")
            if current_payload_time is None:
                current_payload_time = payload.get("timestamp")

            if not isinstance(current_payload_time, int):
                return False

            # If using previous_secret, enforce grace period
            if previous_secret and hmac.compare_digest(previous_secret, secret):
                if current_payload_time < now - grace_seconds:
                    return False

            # Record nonce as seen
            exp = payload.get("exp")
            if not isinstance(exp, int):
                return False

            seen[nonce] = max(now, exp)
            return True

    def void_to_geometry_sync(self, network_name: str, secret: str, domain_filter: Optional[str] = None) -> int:
        """Synchronize residuals from void (surface) to geometry (mind)."""
        runtime = self.get_network(network_name, secret)
        if not runtime:
            return 0
        
        residuals = runtime.surface.field._residuals
        if domain_filter:
            residuals = [r for r in residuals if r.domain == domain_filter]
        
        synced = 0
        for res in residuals[-40:]:  # Sync last 40
            if res.kind == "binary":
                runtime.mind.ingest_binary(res.payload.encode("utf-8"))
            else:
                runtime.mind.ingest_text(res.payload)
            synced += 1
        
        runtime.mind.autonomous_pulse(3)
        return synced

    def geometry_to_void_sync(self, network_name: str, secret: str, min_coherence: float = 0.90) -> int:
        """Synchronize residuals from geometry (mind) back to void (surface)."""
        runtime = self.get_network(network_name, secret)
        if not runtime:
            return 0
        
        pushed = 0
        for rid, data in list(runtime.mind.geometry._data.items()):
            if data.get("protect") or data["coherence"] >= min_coherence:
                packet = SecureNode.lock_payload(
                    data["value"],
                    runtime.surface._secret,
                    metadata={"source": "geometry", "coherence": data["coherence"]}
                )
                lock_id = runtime.surface.authenticated_ingest_lock(packet)
                if lock_id:
                    runtime.surface.confirm(lock_id)
                    pushed += 1
        
        return pushed

    def cross_network_bridge(
        self,
        source_network: str,
        source_secret: str,
        target_network: str,
        target_secret: str,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Bridge query across networks (source projects, target receives)."""
        source = self.get_network(source_network, source_secret)
        target = self.get_network(target_network, target_secret)
        
        if not source or not target:
            return []
        
        # Query source
        results = source.project(query, top_k=top_k)
        if not results or "results" not in results:
            return []
        
        # Inject into target
        for item in results.get("results", []):
            payload = item.get("payload", "")
            if payload:
                target.mind.inject_rich(payload, domain="bridged", passes=1)
        
        target.mind.autonomous_pulse(2)
        
        return results.get("results", [])

    def status(self, name: Optional[str] = None, secret: Optional[str] = None) -> Dict[str, Any]:
        """Get status of network(s)."""
        with self._lock:
            if name is None:
                return {
                    "network_count": len(self._networks),
                    "networks": self.list_networks(),
                }

            if secret is None:
                raise ValueError("secret is required when requesting status for one network")

            runtime = self.get_network(name, secret)
            if runtime is None:
                return {"error": "network not found or unauthorized"}
            
            entry = self._networks.get(name)
            st = runtime.status()
            st["nodes"] = list(entry.get("nodes", {}).keys()) if entry else []
            st["created_at"] = entry.get("created_at") if entry else 0
            return st

    def full_status(self) -> Dict[str, Any]:
        """Get detailed status of all networks (no auth required for summary)."""
        with self._lock:
            all_networks = {}
            for name in self._networks:
                entry = self._networks[name]
                try:
                    st = entry["runtime"].status()
                    all_networks[name] = {
                        "nodes": list(entry.get("nodes", {}).keys()),
                        "created_at": entry.get("created_at", 0),
                        "surface": st.get("surface", {}),
                        "mind": st.get("mind", {}),
                    }
                except Exception:
                    all_networks[name] = {"error": "status unavailable"}
            
            return {
                "network_count": len(self._networks),
                "networks": all_networks,
                "timestamp": time.time(),
            }
