from __future__ import annotations

from typing import Any, Dict, Optional

from config_loader import ConfigValidationError, load_config, validate_config

from .core import CoherentVoid, SecureNode
from .mind import ResidualFieldMind


class ResidualVoid:
    def __init__(
        self,
        secret: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str] = None,
    ) -> None:
        loaded_config = config or load_config(config_path)
        try:
            validate_config(loaded_config)
        except ConfigValidationError:
            if loaded_config.get("environment") == "production":
                raise

        security = loaded_config.get("security", {})
        resolved_secret = secret or security.get("secret_key") or "development-secret"

        self.config = loaded_config
        self.surface = CoherentVoid(
            secret=resolved_secret,
            min_project_score=float(loaded_config.get("coherence", {}).get("quorum_size", 2)) / 10.0,
        )
        self.mind = ResidualFieldMind()

    def authenticated_ingest_lock(self, payload: Dict[str, Any]) -> Optional[str]:
        return self.surface.authenticated_ingest_lock(payload)

    def confirm(self, lock_id: str):
        residual = self.surface.confirm(lock_id)
        if residual is None:
            return None

        if residual.kind == "binary":
            self.mind.ingest_text(residual.payload, metadata=residual.metadata)
        else:
            self.mind.ingest_text(residual.payload, metadata=residual.metadata)
        return residual

    def lock_and_confirm(self, payload: str | bytes, metadata: Optional[Dict[str, Any]] = None) -> bool:
        packet = SecureNode.lock_payload(payload, self.surface._secret, metadata=metadata)
        lock_id = self.authenticated_ingest_lock(packet)
        if not lock_id:
            return False
        return self.confirm(lock_id) is not None

    def project(self, query: str, top_k: int = 3):
        surface = self.surface.project(query, top_k=top_k, require_grounding=True)
        if surface:
            return {
                "source": "surface",
                "results": [
                    {
                        "payload": residual.payload,
                        "score": float(score),
                        "kind": residual.kind,
                        "metadata": residual.metadata,
                    }
                    for residual, score in surface
                ],
            }

        geometry = self.mind.project(query, top_k=top_k)
        return {"source": "geometry", "results": geometry}

    def status(self) -> Dict[str, Any]:
        return {
            "environment": self.config.get("environment", "development"),
            "surface": self.surface.status(),
            "mind": self.mind.status(),
        }
