from __future__ import annotations

import re
import threading
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .core import CoherentVoid, Residual, SecureNode, canonical_payload, hash_text, sign_packet
from .ingestion import inject_document

# ---------------------------------------------------------------------------
# Atomic-lock helpers
# ---------------------------------------------------------------------------

_ANAPHORIC_LOCK_RE = re.compile(
    r'^(?:it|this|these|they|its|that|those)\b', re.IGNORECASE
)


def _split_atomic(body: str) -> List[str]:
    """Split a body string into atomic (single-idea) sentences.

    Mirrors the sentence-splitting and anaphoric-merge logic in
    auto_segment() so that direct lock() calls enforce the same
    atomicity that inject_document() provides.

    Rules:
    - Protect decimal numbers (e.g. "3.14") before splitting.
    - Split only on ". " / "! " / "? " followed by a capital letter
      (not semicolons — those connect related clauses in one idea).
    - Merge sentences that open with an unresolved anaphoric pronoun
      (It/This/These/They/Its/That/Those) onto the preceding sentence
      so that "A HyperSeed is … 200 bytes. It carries Ghost Tax." stays
      together rather than becoming a spurious ghost-tax residual.
    """
    # Protect decimals: "3.14" → "3DECIMAL14"
    body = re.sub(r"(\d)\.(\d)", r"\1DECIMAL\2", body)
    # Ensure at least one space after sentence-ending punctuation
    body = re.sub(r"(?<=[.!?])(?=[A-Z])", " ", body)
    body = body.replace("DECIMAL", ".")

    raw = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]

    # Anaphoric merge
    merged: List[str] = []
    for s in raw:
        if merged and _ANAPHORIC_LOCK_RE.match(s):
            merged[-1] = merged[-1].rstrip() + " " + s
        else:
            merged.append(s)
    return merged


def _shadow_fragments(text: str) -> List[str]:
    """Create ranked Shadow units while preserving *text* as the Source."""
    parts = text.split("::", 2)
    if len(parts) != 3:
        sentences = _split_atomic(text.strip())
        return sentences or [text.strip()]

    prefix = f"{parts[0]}::{parts[1]}"
    body = parts[2].strip()
    sentences = _split_atomic(body)
    if len(sentences) <= 1:
        return [text.strip()]
    return [
        f"{prefix if i == 0 else f'{prefix}_S{i + 1}'}::{sentence}"
        for i, sentence in enumerate(sentences)
        if sentence
    ]


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
    def lock(
        self,
        text: str,
        domain: str = "general",
        protect: bool = True,
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
        identity: Optional[str] = None,
        scale: float = 1.0,
        density: float = 1.0,
        mass: Optional[float] = None,
        intent: str = "",
        shadow_texts: Optional[List[str]] = None,
    ) -> str:
        """Lock text directly via HMAC signature; returns 'locked' or error reason.

        Atomic enforcement: if the body contains multiple sentences they are
        split into separate residuals before committing, matching the same
        atomicity guarantee that inject_document() provides.  This prevents
        multi-idea blobs from accumulating ego (Bellman strength) on broad
        token coverage and winning frame-gated queries they should not answer.

        Protocol:
          - Pre-tagged text  (TOPIC::TAG::body): prefix is preserved; each
            sentence beyond the first gets a _S2, _S3 … suffix on the tag.
          - Untagged text    (raw body only):    each sentence is committed
            as-is; no synthetic tag is injected.
          - Single-sentence bodies pass through with zero overhead.
        """
        shadows = shadow_texts if shadow_texts is not None else _shadow_fragments(text)
        return self._node.lock_text(
            text,
            domain=domain,
            protect=protect,
            shell=shell,
            imprint_layer=imprint_layer,
            coherence=coherence,
            identity=identity,
            scale=scale,
            density=density,
            mass=mass,
            intent=intent,
            shadow_texts=shadows,
        )

    def lock_and_confirm(
        self,
        payload: Union[str, bytes],
        metadata: Optional[Dict[str, Any]] = None,
        domain: str = "general",
        protect: bool = True,
        identity: Optional[str] = None,
        scale: float = 1.0,
        density: float = 1.0,
        mass: Optional[float] = None,
        intent: str = "",
    ) -> bool:
        """Envelope-based lock+confirm in one call; returns True on success."""
        merged_metadata = {
            **(metadata or {}),
            "domain": domain,
            "protect": protect,
            "identity": identity,
            "scale": scale,
            "density": density,
            "mass": mass,
            "intent": intent,
        }
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
        identity = meta.get("identity")
        scale = float(meta.get("scale", 1.0))
        density = float(meta.get("density", 1.0))
        mass_raw = meta.get("mass")
        mass = float(mass_raw) if mass_raw is not None else None
        intent = str(meta.get("intent", ""))

        if kind == "binary":
            raw_bytes = base64.b64decode(content.encode("ascii"))
            text_payload = raw_bytes
        else:
            text_payload = str(content).encode("utf-8")
        shadow_payloads: List[Union[str, bytes]]
        if kind == "binary":
            shadow_payloads = [text_payload]
        else:
            shadow_payloads = _shadow_fragments(
                text_payload.decode("utf-8", errors="replace")
            )

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
            seed_identity=identity,
            seed_scale=scale,
            seed_density=density,
            seed_mass=mass,
            seed_intent=intent,
            shadow_payloads=shadow_payloads,
        )
        if result == "locked":
            info = self.last_locked_info() or {}
            source_id = info.get("source_id")
            for residual in reversed(self._void.field.residuals):
                if residual.layer == "source" and residual.source_id == source_id:
                    return residual
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
        # Multi-residual intents (LIST/COMPARE/RELATE/STEPS/SUMMARIZE) return
        # List[str]; wrap each item as a separate payload entry.
        if isinstance(result, list):
            if not result:
                return {"source": "void", "results": []}
            return {"source": "void", "results": [{"payload": r, "score": 1.0} for r in result]}
        if result in (CoherentVoid._REFUSAL, "Unknown mode"):
            return {"source": "void", "results": []}
        return {"source": "void", "results": [{"payload": result, "score": 1.0}]}

    def inject(
        self,
        full_text: str,
        domain: str = "DOC",
        title: str = "SOURCE",
        protect: bool = True,
        identity: Optional[str] = None,
        scale: float = 1.0,
        density: float = 1.0,
        mass: Optional[float] = None,
        intent: str = "",
    ) -> Dict[str, int]:
        return inject_document(
            self,
            full_text=full_text,
            domain=domain,
            title=title,
            protect=protect,
            identity=identity,
            scale=scale,
            density=density,
            mass=mass,
            intent=intent,
        )

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
                    "freqs": list(r.freqs),
                    "layer": r.layer,
                    "source_id": r.source_id,
                    "seed_identity": r.seed_identity,
                    "seed_scale": r.seed_scale,
                    "seed_density": r.seed_density,
                    "seed_mass": r.seed_mass,
                    "seed_intent": r.seed_intent,
                }
            )
        return {
            "label": "",
            "name": self._void.name,
            "residuals": residuals,
            "pending": deepcopy(self._pending),
            "captured_at": time.time(),
        }

    def _load_state_dict(self, state: Dict[str, Any]) -> None:
        secret = self._secret_str
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
                freqs=item.get("freqs") if isinstance(item.get("freqs"), list) else None,
                layer=str(item.get("layer", "legacy")),
                source_id=str(item.get("source_id", "")) or None,
                seed_identity=str(item.get("seed_identity", "default")),
                seed_scale=float(item.get("seed_scale", 1.0)),
                seed_density=float(item.get("seed_density", 1.0)),
                seed_mass=float(item.get("seed_mass", 1.0)),
                seed_intent=str(item.get("seed_intent", "")),
            )
            if ok:
                new_void.lock_count += 1
            elif reason != "duplicate":
                raise ValueError(f"restore_failed:{reason}")
        # Backfill governance for residuals that pre-date the governance layer.
        # Re-derives family="" entries and enforces FIFO active-engram ordering
        # so a newly locked residual can correctly demote old ungoverned cousins.
        new_void.field.backfill_governance()
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
    # Optional Pure-Harness dynamics
    # ------------------------------------------------------------------
    def configure_pure_harness(
        self,
        *,
        enabled: bool = True,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Enable or retune diagnostics without changing retrieval behavior."""
        return self._void.configure_pure_harness(
            enabled=enabled,
            **overrides,
        )

    def pure_harness_response(
        self,
        initial_residual: float,
        gamma: float,
        **controls: Any,
    ) -> float:
        return self._void.pure_harness_response(
            initial_residual,
            gamma,
            **controls,
        )

    def evolve_residual_pairs(
        self,
        residuals: List[float],
        **controls: Any,
    ) -> Dict[str, Any]:
        return self._void.evolve_residual_pairs(residuals, **controls)

    # ------------------------------------------------------------------
    # Field management
    # ------------------------------------------------------------------
    def clear(self) -> Dict[str, Any]:
        """Wipe all residuals and reset the void to genesis state."""
        with self._lock:
            self._pending.clear()
        return self._void.clear()

    # ------------------------------------------------------------------
    # Integrity & status
    # ------------------------------------------------------------------
    def verify_integrity(self) -> Tuple[bool, str]:
        return self._void.verify_integrity()

    def last_locked_info(self) -> Optional[Dict[str, Any]]:
        """Return family key and active state captured atomically during the last store on this thread.

        Uses per-thread storage written inside CoherentField.store() while the
        field lock is still held, so concurrent locks on other threads do not
        contaminate this result.
        """
        from .core import _store_result_local
        info = getattr(_store_result_local, "info", None)
        return info  # {"family": str, "active": bool} or None if no lock yet on this thread

    def status(self) -> Dict[str, Any]:
        from . import __version__

        # void.status() calls field.status() under field._lock, so the
        # governance summary (active_families, latent_count, families) is
        # consistent with concurrent lock/store operations.
        void_st = self._void.status()

        return {
            "void": void_st,
            "pending_locks": len(self._pending),
            "version": __version__,
            # Promote the already-locked memory summary to the top level so
            # API consumers get it without traversing void_st.
            "memory": void_st.pop("memory", {}),
        }

    # ------------------------------------------------------------------
    # Expose void reference for advanced use
    # ------------------------------------------------------------------
    @property
    def void(self) -> CoherentVoid:
        return self._void
