from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple, Union

from .core import CoherentVoid, Residual, SecureNode, canonical_payload, hash_text, sign_packet


class ResidualVoid:
    """Thin façade over lean CoherentVoid.

    Exposes:
    - lock / lock_and_confirm  – authenticated write path
    - authenticated_ingest_lock / confirm – envelope two-step (backward-compat)
    - project(mode="exact"|"synthesize")  – read path
    - verify_integrity                    – hash-chain check
    - status                              – runtime metrics
    """

    def __init__(
        self,
        secret: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str] = None,
        name: str = "void",
    ) -> None:
        # Resolve secret from config if not provided directly
        if secret is None:
            try:
                from config_loader import load_config
                loaded = config or load_config(config_path)
            except Exception:
                loaded = config or {}
            secret = (
                loaded.get("security", {}).get("secret_key")
                or "development-secret"
            )

        self._secret_str: str = secret
        self._void = CoherentVoid(name=name, secret=secret)
        self._node = SecureNode(f"__facade__{id(self)}", self._void)
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Simple write path
    # ------------------------------------------------------------------
    def lock(self, text: str, domain: str = "general", protect: bool = True) -> str:
        """Lock text directly via HMAC signature; returns 'locked' or error reason."""
        return self._node.lock_text(text, domain=domain, protect=protect)

    def lock_and_confirm(
        self,
        payload: Union[str, bytes],
        metadata: Optional[Dict[str, Any]] = None,
        domain: str = "general",
        protect: bool = True,
    ) -> bool:
        """Envelope-based lock+confirm in one call; returns True on success."""
        merged_metadata = {**(metadata or {}), "domain": domain, "protect": protect}
        packet = SecureNode.lock_payload(payload, secret=self._secret_str, metadata=merged_metadata)
        lock_id = self.authenticated_ingest_lock(packet)
        if not lock_id:
            return False
        return self.confirm(lock_id) is not None

    # ------------------------------------------------------------------
    # Envelope two-step (backward-compat)
    # ------------------------------------------------------------------
    def authenticated_ingest_lock(self, envelope: Dict[str, Any]) -> Optional[str]:
        """Validate envelope and register it for confirmation; returns lock_id or None."""
        if not SecureNode.verify_payload(envelope, self._secret_str):
            return None
        lock_id = hash_text(canonical_payload(envelope))
        with self._lock:
            self._pending[lock_id] = envelope
        return lock_id

    def confirm(self, lock_id: str) -> Optional[Residual]:
        """Commit a previously registered envelope; returns Residual or None."""
        with self._lock:
            envelope = self._pending.pop(lock_id, None)
        if envelope is None:
            return None

        import base64
        kind = envelope.get("kind", "text")
        content = envelope.get("payload", "")
        meta = envelope.get("metadata", {})
        domain = meta.get("domain", "general")
        protect = bool(meta.get("protect", True))

        if kind == "binary":
            raw_bytes = base64.b64decode(content.encode("ascii"))
            text_payload = raw_bytes
        else:
            text_payload = str(content).encode("utf-8")

        # Build HMAC signature for lean ingest
        to_sign = text_payload + b"lock" + domain.encode()
        secret_bytes = self._void.secret
        sig = sign_packet(to_sign, secret_bytes)
        result = self._void.ingest(
            "lock",
            text_payload,
            domain=domain,
            source="facade",
            signature=sig,
            protect=protect,
        )
        if result == "locked":
            return self._void.field.residuals[-1] if self._void.field.residuals else None
        return None

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------
    def project(
        self,
        query: str,
        mode: str = "exact",
        top_k: int = 3,
    ) -> Dict[str, Any]:
        """Project query; returns dict with 'source' and 'results' list."""
        result = self._void.project(query, mode=mode)
        if result in (CoherentVoid._REFUSAL, "Unknown mode"):
            return {"source": "void", "results": []}
        return {"source": "void", "results": [{"payload": result, "score": 1.0}]}

    # ------------------------------------------------------------------
    # Integrity & status
    # ------------------------------------------------------------------
    def verify_integrity(self) -> Tuple[bool, str]:
        return self._void.verify_integrity()

    def status(self) -> Dict[str, Any]:
        void_st = self._void.status()
        return {"void": void_st, "pending_locks": len(self._pending)}

    # ------------------------------------------------------------------
    # Expose void reference for advanced use
    # ------------------------------------------------------------------
    @property
    def void(self) -> CoherentVoid:
        return self._void

