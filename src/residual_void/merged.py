from __future__ import annotations

import threading
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .core import CoherentVoid, Residual, SecureNode, canonical_payload, hash_text, sign_packet
from .ingestion import inject_document


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
        self._snapshots: List[Dict[str, Any]] = []

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

    def inject(
        self,
        full_text: str,
        domain: str = "DOC",
        title: str = "SOURCE",
        protect: bool = True,
    ) -> Dict[str, int]:
        return inject_document(self, full_text=full_text, domain=domain, title=title, protect=protect)

    def _state_dict(self) -> Dict[str, Any]:
        residuals = []
        for r in self._void.field.residuals:
            residuals.append(
                {
                    "fragment": r.fragment,
                    "domain": r.domain,
                    "node_id": r.node_id,
                    "protect": r.protect,
                    "shell": r.shell,
                    "imprint_layer": r.imprint_layer,
                    "coherence": r.coherence,
                    "value": r.value,
                    "freqs": dict(r.freqs),
                }
            )
        return {
            "label": "",
            "name": self._void.name,
            "secret": self._secret_str,
            "residuals": residuals,
            "pending": deepcopy(self._pending),
            "captured_at": time.time(),
        }

    def _load_state_dict(self, state: Dict[str, Any]) -> None:
        secret = str(state.get("secret", self._secret_str))
        name = str(state.get("name", "void"))
        new_void = CoherentVoid(name=name, secret=secret)
        new_node = SecureNode(f"__facade__{id(self)}", new_void)
        for item in state.get("residuals", []):
            payload = str(item.get("fragment", "")).strip()
            if not payload:
                continue
            ok, reason = new_void.field.store(
                payload,
                domain=str(item.get("domain", "general")),
                node_id=str(item.get("node_id", "restore")),
                protect=bool(item.get("protect", True)),
                shell=int(item.get("shell", 0)),
                imprint_layer=str(item.get("imprint_layer", "fast")),
                coherence=float(item.get("coherence", 0.85)),
                value=float(item.get("value", 0.0)),
                freqs=item.get("freqs") if isinstance(item.get("freqs"), dict) else None,
            )
            if ok:
                new_void.lock_count += 1
            elif reason != "duplicate":
                raise ValueError(f"restore_failed:{reason}")
        self._void = new_void
        self._node = new_node
        self._pending = deepcopy(state.get("pending", {}))

    def snapshot(self, label: str = "") -> Dict[str, Any]:
        snap = self._state_dict()
        snap["label"] = label or f"snapshot-{len(self._snapshots) + 1}"
        self._snapshots.append(deepcopy(snap))
        return snap

    def list_snapshots(self) -> List[str]:
        return [str(s.get("label", "")) for s in self._snapshots]

    def restore(self, label: Optional[str] = None) -> bool:
        if not self._snapshots:
            return False
        target = self._snapshots[-1]
        if label is not None:
            matches = [s for s in self._snapshots if s.get("label") == label]
            if not matches:
                return False
            target = matches[-1]
        self._load_state_dict(deepcopy(target))
        return True

    def save_snapshot_file(self, path: str) -> str:
        snap = self.snapshot(label=f"file:{Path(path).name}")
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)

    def load_snapshot_file(self, path: str) -> bool:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._load_state_dict(data)
        self._snapshots.append(deepcopy(data))
        return True

    def audit_drift(self, probes: Optional[List[str]] = None, rounds: int = 3) -> Dict[str, Any]:
        probes = probes or [
            "what is locked in this void?",
            "how many residuals are present?",
            "summarize known protected content",
        ]
        rounds = max(1, int(rounds))
        outputs: Dict[str, List[str]] = {probe: [] for probe in probes}
        identity_holds = 0
        for _ in range(rounds):
            ok, _ = self.verify_integrity()
            if ok:
                identity_holds += 1
            for probe in probes:
                result = self.project(probe, mode="synthesize")
                payload = result["results"][0]["payload"] if result["results"] else ""
                outputs[probe].append(payload)
        drift_by_probe = {}
        for probe, vals in outputs.items():
            unique = len(set(vals))
            drift_by_probe[probe] = 0.0 if len(vals) < 2 else (unique - 1) / (len(vals) - 1)
        drift_score = float(
            0.7 * (sum(drift_by_probe.values()) / max(1, len(drift_by_probe)))
            + 0.3 * (1.0 - identity_holds / rounds)
        )
        return {
            "rounds": rounds,
            "drift_score": round(drift_score, 4),
            "identity_hold": round(identity_holds / rounds, 4),
            "verdict": "stable" if drift_score <= 0.25 else "drifting",
            "probe_drift": drift_by_probe,
        }

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
