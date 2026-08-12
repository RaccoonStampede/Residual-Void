from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .core import tokenize_text


class ResidualGeometry:
    def __init__(self, dimensions: int = 8, graph_similarity_threshold: float = 0.2) -> None:
        self._dimensions = dimensions
        self._graph_similarity_threshold = graph_similarity_threshold
        self._nodes: List[Dict[str, Any]] = []
        self._adjacency: np.ndarray = np.zeros((0, 0), dtype=float)
        self._occupied: set[Tuple[float, ...]] = set()

    def _embed(self, text: str) -> np.ndarray:
        tokens = tokenize_text(text)
        vector = np.zeros(self._dimensions, dtype=float)
        if not tokens:
            return vector
        for idx, token in enumerate(tokens):
            bucket = idx % self._dimensions
            vector[bucket] += (sum(ord(ch) for ch in token) % 17) + 1
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector
        return vector / norm

    def _place_collision_free(self, vector: np.ndarray) -> np.ndarray:
        placement = vector.copy()
        for _ in range(10):
            key = tuple(np.round(placement, 6).tolist())
            if key not in self._occupied:
                self._occupied.add(key)
                return placement
            placement = placement + np.random.default_rng().normal(0, 1e-4, size=placement.shape)
        key = tuple(np.round(placement, 6).tolist())
        self._occupied.add(key)
        return placement

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    def store(self, payload: str | bytes, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        text = payload.decode("utf-8", errors="ignore") if isinstance(payload, bytes) else str(payload)
        vector = self._embed(text)
        vector = self._place_collision_free(vector)

        node = {
            "payload": text,
            "vector": vector,
            "metadata": metadata or {},
            "created_at": time.time(),
        }
        self._nodes.append(node)
        self._expand_graph_incremental(node)
        return node

    def _expand_graph_incremental(self, newest: Dict[str, Any]) -> None:
        total = len(self._nodes)
        if total == 1:
            self._adjacency = np.zeros((1, 1), dtype=float)
            return

        old = self._adjacency
        new_adj = np.zeros((total, total), dtype=float)
        new_adj[: total - 1, : total - 1] = old

        newest_vector = newest["vector"]
        for idx, node in enumerate(self._nodes[:-1]):
            similarity = self._cosine(node["vector"], newest_vector)
            if similarity >= self._graph_similarity_threshold:
                new_adj[idx, total - 1] = similarity
                new_adj[total - 1, idx] = similarity

        self._adjacency = new_adj

    def query(self, text: str, top_k: int = 5, use_multiprocessing: bool = True) -> List[Tuple[Dict[str, Any], float]]:
        if not self._nodes:
            return []

        query_vector = self._embed(text)
        scored: List[Tuple[Dict[str, Any], float]] = []
        for node in self._nodes:
            score = self._cosine(query_vector, node["vector"])
            scored.append((node, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(1, top_k)]

    def regulate_drift(self, max_norm: float = 1.0) -> None:
        for node in self._nodes:
            vector = node["vector"]
            norm = np.linalg.norm(vector)
            if norm > max_norm and norm > 0:
                node["vector"] = (vector / norm) * max_norm

    def prune(self, max_items: int) -> int:
        if max_items < 0:
            raise ValueError("max_items must be non-negative")
        if len(self._nodes) <= max_items:
            return 0

        removed = len(self._nodes) - max_items
        self._nodes = self._nodes[-max_items:]

        self._adjacency = np.zeros((0, 0), dtype=float)
        self._occupied = set()
        replay_nodes = self._nodes
        self._nodes = []
        for node in replay_nodes:
            self.store(node["payload"], metadata=node.get("metadata") or {})

        return removed

    def spectrum(self) -> Dict[str, Any]:
        if self._adjacency.size == 0:
            return {"eigenvalues": [], "fiedler": 0.0}

        degree = np.diag(self._adjacency.sum(axis=1))
        laplacian = degree - self._adjacency
        eigenvalues = np.linalg.eigvalsh(laplacian)
        values = [float(v) for v in sorted(eigenvalues.tolist())]
        fiedler = values[1] if len(values) > 1 else 0.0
        return {"eigenvalues": values, "fiedler": fiedler}

    def status(self) -> Dict[str, Any]:
        return {
            "node_count": len(self._nodes),
            "graph_nodes": int(self._adjacency.shape[0]),
            "graph_edges": int(np.count_nonzero(np.triu(self._adjacency, k=1))),
            "dimensions": self._dimensions,
        }
