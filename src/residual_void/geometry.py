from __future__ import annotations

import time
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .core import content_tokens, tokenize_text


class ResidualGeometry:
    """Full ResidualGeometry with nested shells, god-zone, ghost tax, ethical tilt."""
    
    def __init__(self, max_items: int = 500, shell_count: int = 3, dimensions: int = 8) -> None:
        self._dimensions = dimensions
        self._data: Dict[str, Dict] = {}
        self._id_counter = 0
        self._lock = threading.RLock()
        self.shell_count = shell_count
        self.max_items = max_items
        
        # God-zone & regulation
        self.drift = 0.0
        self.edge_resonance: Dict = {}
        self.last_residual_energy = 0.0
        self.ethical_tilt = 0.0
        self.refusal_strength = 0.5
        self.ghost_tax = 0.15
        self.god_zone_threshold = 0.010

    def _embed(self, text: str) -> np.ndarray:
        """Token-based embedding."""
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

    def _fibonacci_place(self, idx: int) -> int:
        """Fibonacci-based shell placement."""
        phi = (1 + np.sqrt(5)) / 2
        return int((phi * idx) % self.shell_count)

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    def store(self, text: str, coherence: float = 0.85, protect: bool = False,
              domain: str = "general", force_promote: bool = False, preferred_shell: int = 0) -> str:
        with self._lock:
            self._id_counter += 1
            rid = f"res_{self._id_counter}"
            
            # Coherence scoring
            score = coherence if not force_promote else min(1.0, coherence + 0.12)
            
            # Shell placement (Fibonacci-based)
            shell = preferred_shell if preferred_shell < self.shell_count else self._fibonacci_place(self._id_counter)
            
            vector = self._embed(text)
            
            self._data[rid] = {
                "value": text,
                "coherence": min(1.0, score),
                "protect": protect or (coherence >= 0.95),
                "domain": domain,
                "shell": shell,
                "vector": vector,
                "created_at": time.time(),
                "touch_count": 1
            }
            
            # Pruning if over max
            if len(self._data) > self.max_items:
                candidates = [k for k, v in self._data.items() if not v["protect"]]
                if candidates:
                    victims = sorted(candidates, key=lambda k: (self._data[k]["coherence"], self._data[k]["touch_count"]))[:len(candidates)//4]
                    for v in victims:
                        del self._data[v]
            
            return rid

    def query(self, text: str, top_k: int = 5) -> List[Tuple[str, float, Dict]]:
        with self._lock:
            if not self._data:
                return []
            
            qtoks = set(content_tokens(text))
            results = []
            query_vector = self._embed(text)
            
            for rid, item in self._data.items():
                # Token overlap
                itoks = set(content_tokens(item["value"]))
                overlap = len(qtoks & itoks) / max(1, len(qtoks | itoks))
                
                # Vector similarity
                vec_sim = self._cosine(query_vector, item["vector"])
                
                # Coherence bonus
                coh_bonus = 0.15 if item["coherence"] >= 0.90 else 0.0
                
                score = 0.4 * overlap + 0.35 * vec_sim + 0.25 * item["coherence"] + coh_bonus
                results.append((rid, score, item))
                item["touch_count"] += 1
            
            results.sort(key=lambda x: -x[1])
            return results[:top_k]

    def decay_step(self):
        """Decay drift (god-zone regulation)."""
        with self._lock:
            self.drift = max(0, self.drift - 0.0015)
            self.drift += 0.005 * (1 - self.refusal_strength)
            self.ghost_tax = 0.12 + 0.03 * (1 - self.refusal_strength)

    def pulse(self, inject_energy: float = 0.009):
        """Inject energy and check god-zone."""
        with self._lock:
            self.drift += inject_energy * (1.0 + self.ethical_tilt * 0.5)
            if abs(self.drift) > 0.01:
                self.refusal_strength = min(1.0, self.refusal_strength + 0.003)

    def prune(self, max_items: int) -> int:
        """Safe pruning (protects marked residuals)."""
        with self._lock:
            if max_items < 0:
                raise ValueError("max_items must be non-negative")
            if len(self._data) <= max_items:
                return 0
            
            removed = len(self._data) - max_items
            candidates = [k for k, v in self._data.items() if not v["protect"]]
            if candidates:
                to_remove = sorted(candidates, key=lambda k: self._data[k]["coherence"])[:removed]
                for k in to_remove:
                    del self._data[k]
            return removed

    def regulate_drift(self, max_norm: float = 1.0) -> None:
        """Regulate drift to keep geometry stable."""
        with self._lock:
            for rid in self._data:
                vector = self._data[rid]["vector"]
                norm = np.linalg.norm(vector)
                if norm > max_norm and norm > 0:
                    self._data[rid]["vector"] = (vector / norm) * max_norm

    def spectrum(self) -> Dict[str, Any]:
        """Compute adjacency spectrum (stub)."""
        with self._lock:
            return {"eigenvalues": [], "fiedler": 0.0}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            god_zone = self.drift < self.god_zone_threshold and self.refusal_strength > 0.70
            return {
                "node_count": len(self._data),
                "dimensions": self._dimensions,
                "drift": round(self.drift, 4),
                "god_zone": god_zone,
                "global_coherence": round(np.mean([d["coherence"] for d in self._data.values()]) if self._data else 0.0, 3),
                "refusal_strength": round(self.refusal_strength, 3),
                "ethical_tilt": round(self.ethical_tilt, 3),
                "ghost_tax": round(self.ghost_tax, 3),
            }
