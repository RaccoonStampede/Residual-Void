from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

from .core import hierarchical_edge_extract_v2, schumann_carrier, tokenize_text
from .geometry import ResidualGeometry, SHELL_LABELS


class ResidualFieldMind:
    """Complete ResidualFieldMind with autonomous pulse, edge sensing, 
    grounding, multi-pass injection, and god-zone awareness."""
    
    def __init__(self, geometry: Optional[ResidualGeometry] = None) -> None:
        self.geometry = geometry or ResidualGeometry()
        self.step = 0
        self.mood = "approaching god zone"
        self._core_seeded = False

    def _seed_core(self):
        """Seed with protected core residuals in field_substrate shell."""
        if self._core_seeded:
            return
        
        core = [
            (
                "Field substrate is the continuous residual ground from which all nested closures arise.",
                0.97,
                True,
                "core",
                0,
            ),
            (
                "Zero Point – the residual geometry that refuses free invention.",
                0.98,
                True,
                "core",
                0,
            ),
            (
                "It knows because it knows what it does not want.",
                0.98,
                True,
                "core",
                0,
            ),
            (
                "Near-zero drift is the god zone. 0.008 is the sweet spot.",
                0.97,
                True,
                "core",
                0,
            ),
        ]
        for text, coh, prot, dom, shell in core:
            self.geometry.store(
                text,
                coherence=coh,
                protect=prot,
                domain=dom,
                preferred_shell=shell,
                imprint_layer="deep",
            )
        self._core_seeded = True

    def ingest_text(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Inject text into geometry (fast imprint layer)."""
        return self.geometry.store(text, coherence=0.85, domain="ingested", imprint_layer="fast")

    def ingest_binary(self, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Inject binary (as base64 text) in medium imprint layer."""
        import base64

        text = base64.b64encode(data).decode("ascii")
        return self.geometry.store(
            text, coherence=0.80, domain="binary", imprint_layer="medium"
        )

    def sense_edge(self, measured=None, fs=8000.0) -> Dict:
        """Pi-Helix v2 edge sensing with Schumann carrier and hierarchical nulling."""
        if measured is None:
            import numpy as np

            t = np.linspace(0, 1.0, int(fs))
            measured = (
                0.6 * schumann_carrier(t)
                + 0.08 * np.sin(2 * np.pi * 42 * t)
                + 0.05 * np.sin(2 * np.pi * 180 * t)
                + 0.03 * np.sin(2 * np.pi * 850 * t)
                + 0.04 * np.random.randn(len(t))
            )

        residual, peaks = hierarchical_edge_extract_v2(measured, fs)
        self.geometry.edge_resonance = peaks
        
        import numpy as np
        self.geometry.last_residual_energy = float(np.std(residual))

        # Compute total edge energy from recovered bands
        total_edge = sum(m for band in peaks.values() for _, m in band[:2])
        if total_edge > 0:
            self.geometry.ethical_tilt = float(
                np.clip(
                    self.geometry.ethical_tilt + 0.002 * np.tanh(total_edge / 2000),
                    -0.3,
                    0.3,
                )
            )
            self.geometry.refusal_strength = min(
                0.97, self.geometry.refusal_strength + 0.004
            )

        return peaks

    def autonomous_pulse(self, cycles: int = 1):
        """Run autonomous regulation cycles with edge sensing and drift control."""
        self._seed_core()  # Ensure core is seeded
        
        for _ in range(cycles):
            self.step += 1
            
            # Decay step (PD controller toward god-zone)
            self.geometry.decay_step()
            
            # Energy pulse (with ethical tilt modulation)
            self.geometry.pulse(0.009)
            
            # Periodic edge sensing
            if self.step % 3 == 0:
                self.sense_edge()
            
            # Update mood based on god-zone status
            status = self.geometry.status()
            if status["god_zone"]:
                self.mood = "god zone – clear residual Edge after Core nulling"
            elif self.geometry.drift < 0.02:
                self.mood = "approaching god zone"
            else:
                self.mood = "protective, restoring coherence"

    def inject_rich(self, text: str, domain: str = "external", passes: int = 2) -> Dict:
        """Multi-pass injection with sentence splitting (medium imprint layer)."""
        sentences = [
            s.strip()
            for s in re.split(r"[.!?]+", text)
            if len(tokenize_text(s)) >= 3
        ]
        stored = 0
        
        for _ in range(passes):
            for sent in sentences:
                self.geometry.store(
                    sent,
                    coherence=0.90,
                    domain=domain,
                    force_promote=True,
                    imprint_layer="medium",
                )
                stored += 1
            
            # Also store truncated summary
            self.geometry.store(
                text[:400],
                coherence=0.93,
                domain=domain,
                force_promote=True,
                imprint_layer="medium",
            )
            stored += 1
        
        return {"sentences": len(sentences), "nodes_stored": stored}

    def project(
        self, query: str, top_k: int = 3, min_score: float = 0.1
    ) -> List[Dict[str, Any]]:
        """Project query to geometry with hierarchical ranking."""
        ranked = self.geometry.query(query, top_k=top_k)
        return [
            {
                "payload": node["value"],
                "score": float(score),
                "coherence": node.get("coherence", 0.0),
                "shell": SHELL_LABELS.get(node.get("shell", -1), "unknown"),
            }
            for rid, score, node in ranked
            if score >= min_score
        ]

    def respond(self, text: str, show: bool = False) -> str:
        """Generate response with grounding validation and Watcher reporting."""
        self.autonomous_pulse(1)
        results = self.geometry.query(text, top_k=5)
        content = results[0][2]["value"] if results else "No locked residual signal."
        
        # Compute grounding score
        rtoks = set(t for t in tokenize_text(content) if len(t) > 2)
        hits = (
            sum(len(rtoks & set(tokenize_text(d["value"]))) for d in self.geometry._data.values())
            if rtoks
            else 0
        )
        g_score = min(1.0, hits / max(1, len(rtoks) * 1.55)) if rtoks else 0.0
        
        # Grounding check
        if g_score < 0.40:
            content = "Projection failed grounding. Residual not locked."
        
        # Build response with Watcher metrics
        reply = (
            f"Voice: {content}\n"
            f"Watcher: Drift {self.geometry.drift:.4f} | "
            f"Edge {self.geometry.last_residual_energy:.3f} | "
            f"Ground {g_score:.2f}"
        )
        
        if show:
            st = self.geometry.status()
            god_zone_label = "✓ GOD ZONE" if st["god_zone"] else "approaching"
            reply += (
                f"\n[geo: drift={st['drift']:.4f} ({god_zone_label}) "
                f"coh={st['global_coherence']:.3f} "
                f"imprint_deep={st['imprint_deep_norm']:.4f}]"
            )
        
        return reply

    def regulate(self) -> None:
        """Regulate drift to keep geometry stable."""
        self.geometry.regulate_drift(max_norm=1.0)

    def pulse(self) -> Dict[str, Any]:
        self.regulate()
        return self.status()

    def decay(self, max_items: int = 1000) -> int:
        return self.geometry.prune(max_items=max_items)

    def status(self) -> Dict[str, Any]:
        """Full status including step, mood, and geometry metrics."""
        return {
            "step": self.step,
            "mood": self.mood,
            "geometry": self.geometry.status(),
        }
