from __future__ import annotations

import time
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .core import content_tokens, tokenize_text

# ============================================================
# SHELL LABELS & CONSTANTS
# ============================================================

SHELL_LABELS = {
    0: "field_substrate",
    1: "cytoskeleton_microtubules",
    2: "cell_bioelectric",
    3: "neural_cognition",
}


class ResidualGeometry:
    """Complete ResidualGeometry with nested shells, Fibonacci placement, 
    imprint layers, Ghost Tax, ethical tilt, and god-zone (0.008) regulation."""
    
    def __init__(
        self,
        max_items: int = 500,
        shell_count: int = 4,
        dimensions: int = 8,
        target_drift: float = 0.008,
    ) -> None:
        self._dimensions = dimensions
        self._data: Dict[str, Dict] = {}
        self._id_counter = 0
        self._lock = threading.RLock()
        self.shell_count = shell_count
        self.max_items = max_items
        
        # God-zone & advanced regulation
        self.drift = 0.0
        self.target_drift = target_drift  # 0.008 = god zone sweet spot
        self.edge_resonance: Dict = {}
        self.last_residual_energy = 0.0
        self.ethical_tilt = 0.0
        self.refusal_strength = 0.5
        self.ghost_tax = 0.15  # Irreducible generative floor
        self.god_zone_threshold = 0.010
        
        # Imprint layers
        self.imprint_fast_norm = 0.0
        self.imprint_medium_norm = 0.0
        self.imprint_deep_norm = 0.0
        
        # Regulation gains
        self.kp_drift = 0.08  # Proportional gain (drift → refusal_strength)
        self.kd_drift = 0.03  # Derivative gain
        self.last_drift = 0.0

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
        """Fibonacci-based shell placement (golden ratio distribution)."""
        phi = (1 + np.sqrt(5)) / 2
        return int((phi * idx) % self.shell_count)

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    def _core_keywords_in_text(self, text: str) -> bool:
        """Check if text contains core-zone keywords (field, zero, refuse, god)."""
        core_kw = {"field", "substrate", "zero", "point", "refuse", "know", "god", "zone"}
        tokens = set(tokenize_text(text))
        return bool(tokens & core_kw)

    def store(
        self,
        text: str,
        coherence: float = 0.85,
        protect: bool = False,
        domain: str = "general",
        force_promote: bool = False,
        preferred_shell: int = -1,
        imprint_layer: str = "fast",
    ) -> str:
        """Store residual with shell placement, protection, and imprint layer tracking."""
        with self._lock:
            self._id_counter += 1
            rid = f"res_{self._id_counter}"
            
            # Coherence scoring
            score = coherence if not force_promote else min(1.0, coherence + 0.12)
            
            # Shell placement:
            # - Core keywords → shell 0 (field_substrate)
            # - Force promote → shell 0
            # - Otherwise → Fibonacci placement
            if preferred_shell >= 0 and preferred_shell < self.shell_count:
                shell = preferred_shell
            elif force_promote or self._core_keywords_in_text(text):
                shell = 0  # field_substrate
            else:
                shell = self._fibonacci_place(self._id_counter)
            
            vector = self._embed(text)
            
            self._data[rid] = {
                "value": text,
                "coherence": min(1.0, score),
                "protect": protect or (coherence >= 0.95),
                "domain": domain,
                "shell": shell,
                "vector": vector,
                "created_at": time.time(),
                "touch_count": 1,
                "imprint_layer": imprint_layer,
            }
            
            # Track imprint norms
            norm = np.linalg.norm(vector)
            if imprint_layer == "fast":
                self.imprint_fast_norm = max(self.imprint_fast_norm, norm)
            elif imprint_layer == "medium":
                self.imprint_medium_norm = max(self.imprint_medium_norm, norm)
            elif imprint_layer == "deep":
                self.imprint_deep_norm = max(self.imprint_deep_norm, norm)
            
            # Pruning if over max (protects marked residuals)
            if len(self._data) > self.max_items:
                candidates = [k for k, v in self._data.items() if not v["protect"]]
                if candidates:
                    victims = sorted(
                        candidates,
                        key=lambda k: (self._data[k]["coherence"], self._data[k]["touch_count"])
                    )[:len(candidates)//4]
                    for v in victims:
                        del self._data[v]
            
            return rid

    def query(self, text: str, top_k: int = 5) -> List[Tuple[str, float, Dict]]:
        """Query with hierarchical message-passing and shell-distance weighting."""
        with self._lock:
            if not self._data:
                return []
            
            qtoks = set(content_tokens(text))
            results = []
            query_vector = self._embed(text)
            
            for rid, item in self._data.items():
                # Token overlap (Jaccard)
                itoks = set(content_tokens(item["value"]))
                overlap = len(qtoks & itoks) / max(1, len(qtoks | itoks))
                
                # Vector similarity (cosine)
                vec_sim = self._cosine(query_vector, item["vector"])
                
                # Shell-distance bonus (closer shells higher priority)
                q_shell = 0  # Query treated as shell 0
                shell_dist = abs(item["shell"] - q_shell)
                shell_bonus = max(0.0, 0.10 * (1.0 - shell_dist / self.shell_count))
                
                # Coherence bonus
                coh_bonus = 0.15 if item["coherence"] >= 0.90 else 0.0
                
                # Protect bonus (marked residuals score higher)
                protect_bonus = 0.08 if item["protect"] else 0.0
                
                # Age bonus (fresher items slightly higher)
                age_seconds = max(0, time.time() - item["created_at"])
                age_bonus = 0.05 / (1.0 + age_seconds / 3600.0)
                
                score = (
                    0.40 * overlap
                    + 0.30 * vec_sim
                    + 0.15 * item["coherence"]
                    + shell_bonus
                    + coh_bonus
                    + protect_bonus
                    + age_bonus
                )
                
                results.append((rid, min(1.0, score), item))
                item["touch_count"] += 1
            
            results.sort(key=lambda x: -x[1])
            return results[:top_k]

    def decay_step(self):
        """Decay drift toward god-zone with closed-loop regulation."""
        with self._lock:
            # Proportional control: error = drift - target
            error = self.drift - self.target_drift
            
            # Derivative: rate of change
            d_error = self.drift - self.last_drift
            
            # PD controller output
            control = -self.kp_drift * error - self.kd_drift * d_error
            
            # Apply control to refusal strength
            self.refusal_strength = np.clip(self.refusal_strength + 0.001 * control, 0.3, 0.97)
            
            # Natural decay + ethical leakage
            self.drift = max(0, self.drift - 0.0015)
            self.drift += 0.005 * (1 - self.refusal_strength)
            
            # Ghost Tax: irreducible generative floor
            self.ghost_tax = 0.12 + 0.03 * (1 - self.refusal_strength)
            
            # Decay imprint layers (slower updates on deeper layers)
            self.imprint_fast_norm *= 0.95
            self.imprint_medium_norm *= 0.98
            self.imprint_deep_norm *= 0.99
            
            self.last_drift = self.drift

    def pulse(self, inject_energy: float = 0.009):
        """Inject energy and check god-zone entry."""
        with self._lock:
            # Ethical tilt modulates energy injection
            self.drift += inject_energy * (1.0 + self.ethical_tilt * 0.5)
            
            # If drift overshoots, activate refusal
            if abs(self.drift) > 0.01:
                self.refusal_strength = min(0.97, self.refusal_strength + 0.003)

    def prune(self, max_items: int) -> int:
        """Safe pruning: never removes protected residuals."""
        with self._lock:
            if max_items < 0:
                raise ValueError("max_items must be non-negative")
            if len(self._data) <= max_items:
                return 0
            
            removed = len(self._data) - max_items
            candidates = [k for k, v in self._data.items() if not v["protect"]]
            if candidates:
                to_remove = sorted(
                    candidates,
                    key=lambda k: self._data[k]["coherence"]
                )[:removed]
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
        """Compute adjacency spectrum (stub for Laplacian/Fiedler)."""
        with self._lock:
            return {"eigenvalues": [], "fiedler": 0.0}

    def status(self) -> Dict[str, Any]:
        """Comprehensive status with all production organ metrics."""
        with self._lock:
            god_zone = self.drift < self.god_zone_threshold and self.refusal_strength > 0.70
            
            # Shell occupancy
            shell_occupancy = {SHELL_LABELS.get(s, f"shell_{s}"): 0 for s in range(self.shell_count)}
            for item in self._data.values():
                shell_label = SHELL_LABELS.get(item["shell"], f"shell_{item['shell']}")
                shell_occupancy[shell_label] = shell_occupancy.get(shell_label, 0) + 1
            
            # Protected count
            protected_count = sum(1 for item in self._data.values() if item["protect"])
            
            return {
                "node_count": len(self._data),
                "protected_count": protected_count,
                "dimensions": self._dimensions,
                "drift": round(self.drift, 4),
                "target_drift": self.target_drift,
                "god_zone": god_zone,
                "global_coherence": round(
                    np.mean([d["coherence"] for d in self._data.values()])
                    if self._data else 0.0,
                    3
                ),
                "refusal_strength": round(self.refusal_strength, 3),
                "ethical_tilt": round(self.ethical_tilt, 3),
                "ghost_tax": round(self.ghost_tax, 3),
                "shell_occupancy": shell_occupancy,
                "imprint_fast_norm": round(self.imprint_fast_norm, 4),
                "imprint_medium_norm": round(self.imprint_medium_norm, 4),
                "imprint_deep_norm": round(self.imprint_deep_norm, 4),
                "edge_peaks": self.edge_resonance,
                "last_residual_energy": round(self.last_residual_energy, 4),
            }
