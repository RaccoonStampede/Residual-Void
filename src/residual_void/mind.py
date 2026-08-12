from __future__ import annotations

from typing import Any, Dict, List, Optional

from .geometry import ResidualGeometry


class ResidualFieldMind:
    def __init__(self, geometry: Optional[ResidualGeometry] = None) -> None:
        self.geometry = geometry or ResidualGeometry()

    def ingest_text(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.geometry.store(text, metadata=metadata)

    def ingest_binary(self, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.geometry.store(data, metadata=metadata)

    def project(self, query: str, top_k: int = 3, min_score: float = 0.1) -> List[Dict[str, Any]]:
        ranked = self.geometry.query(query, top_k=top_k, use_multiprocessing=True)
        return [
            {"payload": node["payload"], "score": float(score), "metadata": node.get("metadata", {})}
            for node, score in ranked
            if score >= min_score
        ]

    def regulate(self) -> None:
        self.geometry.regulate_drift(max_norm=1.0)

    def pulse(self) -> Dict[str, Any]:
        self.regulate()
        return self.status()

    def decay(self, max_items: int = 1000) -> int:
        return self.geometry.prune(max_items=max_items)

    def status(self) -> Dict[str, Any]:
        return self.geometry.status()
