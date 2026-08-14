#!/usr/bin/env python3
"""
ResidualVoid HyperDrive Module
==============================
HyperDrive synthesis extension for the ResidualVoid engine.

Provides:
- RealityCore  – deterministic mean-field oscillator
- fuzzy_token_hits / _levenshtein / _jaro_winkler – hardened fuzzy matchers
- question_frequency – query intent profiler
- CoherentVoid (with _vibrate_residuals + HyperDrive project())

All symbols re-exported from src/residual_void/core.py so this module
acts as a convenient standalone entry-point for the HyperDrive feature set.
"""

from __future__ import annotations

from residual_void.core import (
    # oscillator
    RealityCore,
    # fuzzy helpers
    _levenshtein,
    _jaro_winkler,
    fuzzy_token_hits,
    # frequency profiler
    question_frequency,
    # core engine
    CoherentField,
    CoherentVoid,
    Residual,
    SecureNode,
    # shared utilities
    bytes_to_bits,
    bytes_to_bits_packed,
    hamming_sim,
    content_tokens,
    tokenize,
    sign_packet,
    verify_signature,
    # signal processing
    schumann_carrier,
    hierarchical_edge_extract_v2,
    # constants
    BIT_DIM,
)

__all__ = [
    "RealityCore",
    "_levenshtein",
    "_jaro_winkler",
    "fuzzy_token_hits",
    "question_frequency",
    "CoherentField",
    "CoherentVoid",
    "Residual",
    "SecureNode",
    "bytes_to_bits",
    "bytes_to_bits_packed",
    "hamming_sim",
    "content_tokens",
    "tokenize",
    "sign_packet",
    "verify_signature",
    "schumann_carrier",
    "hierarchical_edge_extract_v2",
    "BIT_DIM",
]

# ────────────────────────────────────────────────────────────────────────────
# Quick self-test (run as: python residual_void_hyperdrive.py)
# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    SECRET = "hyperdrive-test-secret"
    void = CoherentVoid(name="hd_test", secret=SECRET)
    node = SecureNode("hd_node", void)

    # ── 1. Exact mode: grounded hit ──────────────────────────────────────
    r1 = node.lock_text("USER::ALICE::locked residual coherent field payload", domain="secure")
    assert r1 == "locked", f"Expected locked, got {r1!r}"
    hit = void.project("USER::ALICE", mode="exact")
    assert "residual" in hit.lower() or "USER" in hit, f"Exact hit failed: {hit!r}"
    print(f"[PASS] exact grounded hit: {hit[:60]!r}")

    # ── 2. Exact mode: strict refusal ────────────────────────────────────
    refused = void.project("PASSCODE::XYZZY", mode="exact")
    assert refused == CoherentVoid._REFUSAL, f"Expected refusal, got {refused!r}"
    print(f"[PASS] exact refusal: {refused!r}")

    # ── 3. Synthesize mode: causal query ─────────────────────────────────
    node.lock_text(
        "The residual field signal explains why coherence emerges after core nulling.",
        domain="knowledge",
    )
    node.lock_text(
        "Void stability is caused by the balance between ghost tax and refusal strength.",
        domain="knowledge",
    )
    synth = void.project("Why does the residual field maintain coherence?", mode="synthesize")
    assert synth != CoherentVoid._REFUSAL, f"Synthesize unexpected refusal: {synth!r}"
    print(f"[PASS] synthesize causal: {synth[:80]!r}")

    # ── 4. Synthesize mode: entity query ─────────────────────────────────
    node.lock_text(
        "Alice is the primary author of the coherent void memoir describing residual states.",
        domain="knowledge",
    )
    synth_entity = void.project("Who wrote the memoir about the void?", mode="synthesize")
    print(f"[INFO] synthesize entity: {synth_entity[:80]!r}")

    # ── 5. Post-query chain integrity ────────────────────────────────────
    ok, msg = void.verify_integrity()
    assert ok, f"Chain integrity failed: {msg}"
    print(f"[PASS] chain integrity: {msg}")

    # ── 6. Status print ──────────────────────────────────────────────────
    st = void.status()
    print(f"[INFO] status: locked={st['locked']} refusals={st['refusals']} chain_ok={st['chain_ok']}")

    # ── 7. RealityCore oscillator sanity ─────────────────────────────────
    core = RealityCore(phase=1.5, scale=2.0)
    for _ in range(20):
        core.step(dt=0.05)
    assert -3.0 <= core.phase <= 3.0, f"Phase out of range: {core.phase}"
    assert -2.0 <= core.vel <= 2.0, f"Vel out of range: {core.vel}"
    print(f"[PASS] RealityCore oscillator: phase={core.phase:.3f} vel={core.vel:.3f}")

    # ── 8. question_frequency ────────────────────────────────────────────
    freq = question_frequency("Why does the field signal cause coherence?")
    assert freq["class"] == "causal"
    assert freq["process_bias"] >= 0.0
    print(f"[PASS] question_frequency causal: {freq}")

    # ── 9. Fuzzy matching helpers ────────────────────────────────────────
    assert _levenshtein("residual", "residuol") == 1
    assert _jaro_winkler("coherent", "coherent") == 1.0
    score = fuzzy_token_hits({"coherent", "residual"}, {"coherents", "residuals", "void"})
    assert score > 0, f"Expected fuzzy hits, got {score}"
    print(f"[PASS] fuzzy helpers: lev=ok jw=ok fuzzy_hits={score:.2f}")

    print("\nAll HyperDrive self-tests passed.")
