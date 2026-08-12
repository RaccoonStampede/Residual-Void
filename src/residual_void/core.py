from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


def tokenize_text(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def cosine_similarity(vec_a: Counter, vec_b: Counter) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(vec_a[key] * vec_b.get(key, 0) for key in vec_a)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hamming_distance_hex(hex_a: str, hex_b: str) -> int:
    if len(hex_a) != len(hex_b):
        raise ValueError("Hex strings must have equal length")
    return sum((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(hex_a, hex_b))


def canonical_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def hmac_sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_verify(secret: str, message: str, signature: str) -> bool:
    expected = hmac_sign(secret, message)
    return hmac.compare_digest(expected, signature)


@dataclass
class Residual:
    residual_id: str
    kind: str
    payload: str
    tokens: List[str]
    token_vector: Counter
    created_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)


def _score_rank_item(item: Tuple[Residual, Counter]) -> Tuple[Residual, float]:
    residual, query_vector = item
    similarity = cosine_similarity(query_vector, residual.token_vector)
    age_seconds = max(time.time() - residual.created_at, 0.0)
    freshness = 1.0 / (1.0 + age_seconds / 3600.0)
    score = 0.85 * similarity + 0.15 * freshness
    return residual, score


class CoherentField:
    def __init__(self, graph_similarity_threshold: float = 0.2) -> None:
        self._residuals: List[Residual] = []
        self._adjacency: np.ndarray = np.zeros((0, 0), dtype=float)
        self._graph_similarity_threshold = graph_similarity_threshold

    def store(self, payload: str | bytes, kind: str = "text", metadata: Optional[Dict[str, Any]] = None) -> Residual:
        if isinstance(payload, bytes):
            normalized = base64.b64encode(payload).decode("ascii")
            inferred_kind = "binary"
        else:
            normalized = payload
            inferred_kind = kind

        tokens = tokenize_text(normalized)
        created_at = time.time()
        residual_id = hash_text(f"{inferred_kind}:{normalized}:{created_at}")
        residual = Residual(
            residual_id=residual_id,
            kind=inferred_kind,
            payload=normalized,
            tokens=tokens,
            token_vector=Counter(tokens),
            created_at=created_at,
            metadata=metadata or {},
        )
        self._residuals.append(residual)
        self._rebuild_graph_incremental(residual)
        return residual

    def rank(self, query: str, top_k: int = 5, use_multiprocessing: bool = False) -> List[Tuple[Residual, float]]:
        query_vector = Counter(tokenize_text(query))
        if not self._residuals:
            return []

        payload = [(residual, query_vector) for residual in self._residuals]
        if use_multiprocessing and len(payload) > 8:
            workers = min(cpu_count(), len(payload))
            with Pool(processes=workers) as pool:
                scored = pool.map(_score_rank_item, payload)
        else:
            scored = [_score_rank_item(item) for item in payload]

        scored.sort(key=lambda entry: entry[1], reverse=True)
        return scored[: max(1, top_k)]

    def _rebuild_graph_incremental(self, newest: Residual) -> None:
        total = len(self._residuals)
        if total == 1:
            self._adjacency = np.zeros((1, 1), dtype=float)
            return

        old = self._adjacency
        new_adj = np.zeros((total, total), dtype=float)
        new_adj[: total - 1, : total - 1] = old

        for idx, existing in enumerate(self._residuals[:-1]):
            similarity = cosine_similarity(existing.token_vector, newest.token_vector)
            if similarity >= self._graph_similarity_threshold:
                new_adj[idx, total - 1] = similarity
                new_adj[total - 1, idx] = similarity

        self._adjacency = new_adj

    def rebuild_graph(self) -> None:
        total = len(self._residuals)
        self._adjacency = np.zeros((total, total), dtype=float)
        for i in range(total):
            for j in range(i + 1, total):
                similarity = cosine_similarity(self._residuals[i].token_vector, self._residuals[j].token_vector)
                if similarity >= self._graph_similarity_threshold:
                    self._adjacency[i, j] = similarity
                    self._adjacency[j, i] = similarity

    def spectrum(self) -> Dict[str, Any]:
        if self._adjacency.size == 0:
            return {"eigenvalues": [], "fiedler": 0.0}

        degree = np.diag(self._adjacency.sum(axis=1))
        laplacian = degree - self._adjacency
        eigenvalues = np.linalg.eigvalsh(laplacian)
        values = [float(v) for v in sorted(eigenvalues.tolist())]
        fiedler = values[1] if len(values) > 1 else 0.0
        return {"eigenvalues": values, "fiedler": float(fiedler)}

    def status(self) -> Dict[str, Any]:
        return {
            "residual_count": len(self._residuals),
            "graph_nodes": int(self._adjacency.shape[0]),
            "graph_edges": int(np.count_nonzero(np.triu(self._adjacency, k=1))),
        }


class SecureNode:
    @staticmethod
    def lock_payload(payload: str | bytes, secret: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = int(time.time())
        if isinstance(payload, bytes):
            encoded_payload = base64.b64encode(payload).decode("ascii")
            kind = "binary"
        else:
            encoded_payload = payload
            kind = "text"

        body = {
            "payload": encoded_payload,
            "kind": kind,
            "timestamp": now,
            "metadata": metadata or {},
        }
        serialized = canonical_payload(body)
        body["signature"] = hmac_sign(secret, serialized)
        return body

    @staticmethod
    def verify_payload(payload: Dict[str, Any], secret: str, ttl_seconds: int = 30, skew_seconds: int = 10) -> bool:
        signature = payload.get("signature", "")
        body = {k: v for k, v in payload.items() if k != "signature"}
        serialized = canonical_payload(body)

        if not signature or not hmac_verify(secret, serialized, signature):
            return False

        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, int):
            return False

        now = int(time.time())
        if timestamp > now + skew_seconds:
            return False
        if now - timestamp > ttl_seconds + skew_seconds:
            return False

        return True


class CoherentVoid:
    def __init__(self, secret: str, min_project_score: float = 0.2) -> None:
        self._secret = secret
        self._field = CoherentField()
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._min_project_score = min_project_score

    def authenticated_ingest_lock(self, payload: Dict[str, Any]) -> Optional[str]:
        if not SecureNode.verify_payload(payload, self._secret):
            return None

        lock_id = hash_text(canonical_payload(payload))
        self._pending[lock_id] = payload
        return lock_id

    def confirm(self, lock_id: str) -> Optional[Residual]:
        payload = self._pending.pop(lock_id, None)
        if payload is None:
            return None

        kind = payload.get("kind", "text")
        content = payload.get("payload", "")
        if kind == "binary":
            decoded = base64.b64decode(content.encode("ascii"))
            return self._field.store(decoded, kind=kind, metadata=payload.get("metadata") or {})
        return self._field.store(str(content), kind=kind, metadata=payload.get("metadata") or {})

    def project(self, query: str, top_k: int = 3, require_grounding: bool = True) -> List[Tuple[Residual, float]]:
        ranked = self._field.rank(query, top_k=top_k, use_multiprocessing=True)
        if not ranked:
            return []
        if ranked[0][1] < self._min_project_score:
            return []
        if require_grounding and not self._is_grounded(ranked):
            return []
        return ranked

    def _is_grounded(self, ranked: Sequence[Tuple[Residual, float]]) -> bool:
        if not ranked:
            return False
        return any(score >= self._min_project_score for _, score in ranked)

    def status(self) -> Dict[str, Any]:
        return {
            "pending_locks": len(self._pending),
            "min_project_score": self._min_project_score,
            "field": self._field.status(),
        }

    @property
    def field(self) -> CoherentField:
        return self._field
