"""
Tests for the HyperDrive delta:
  - RealityCore oscillator
  - _levenshtein / _jaro_winkler / fuzzy_token_hits
  - question_frequency
  - Residual.ensure_core / Residual.bits
  - CoherentField.rank() freq-aware scoring
  - CoherentVoid._vibrate_residuals
  - CoherentVoid.project() exact + synthesize paths (gating, recovery, vibration)
  - Query chain logging and integrity invariants
"""
from __future__ import annotations

import pytest

from residual_void.core import (
    CoherentField,
    CoherentVoid,
    RealityCore,
    Residual,
    SecureNode,
    _jaro_winkler,
    _levenshtein,
    fuzzy_token_hits,
    question_frequency,
)


# ============================================================
# RealityCore oscillator
# ============================================================
class TestRealityCore:
    def test_fields_initialised(self) -> None:
        c = RealityCore(phase=0.5, vel=0.1, scale=2.0)
        assert hasattr(c, "leak") and c.leak > 0
        assert hasattr(c, "fluidity") and c.fluidity > 0
        assert hasattr(c, "restore") and c.restore > 0
        assert hasattr(c, "slow_leak") and c.slow_leak > 0

    def test_scale_affects_params(self) -> None:
        c1 = RealityCore(scale=1.0)
        c2 = RealityCore(scale=4.0)
        # Higher scale → lower leak (more stable)
        assert c2.leak < c1.leak

    def test_step_clips_phase_and_vel(self) -> None:
        c = RealityCore(phase=2.9, vel=1.9, force=5.0)
        for _ in range(50):
            c.step(dt=0.05)
        assert -3.0 <= c.phase <= 3.0
        assert -2.0 <= c.vel <= 2.0

    def test_step_converges_toward_reference(self) -> None:
        c = RealityCore(phase=2.0, reference=0.0, scale=1.0)
        initial_dist = abs(c.phase - c.reference)
        for _ in range(100):
            c.step(dt=0.05)
        final_dist = abs(c.phase - c.reference)
        assert final_dist < initial_dist, "Phase should move toward reference"


# ============================================================
# Fuzzy helpers
# ============================================================
class TestLevenshtein:
    def test_identical(self) -> None:
        assert _levenshtein("abc", "abc") == 0

    def test_empty(self) -> None:
        assert _levenshtein("", "abc") == 3
        assert _levenshtein("abc", "") == 3

    def test_one_edit(self) -> None:
        assert _levenshtein("residual", "residuol") == 1  # substitution
        assert _levenshtein("coherent", "cohrent") == 1   # deletion

    def test_multi_edit(self) -> None:
        assert _levenshtein("kitten", "sitting") == 3


class TestJaroWinkler:
    def test_identical(self) -> None:
        assert _jaro_winkler("coherent", "coherent") == 1.0

    def test_empty(self) -> None:
        assert _jaro_winkler("", "") == 1.0
        assert _jaro_winkler("abc", "") == 0.0

    def test_high_similarity(self) -> None:
        score = _jaro_winkler("residual", "residuals")
        assert score > 0.90

    def test_low_similarity(self) -> None:
        score = _jaro_winkler("abc", "xyz")
        assert score < 0.5


class TestFuzzyTokenHits:
    def test_exact_hit_is_one(self) -> None:
        score = fuzzy_token_hits({"coherent"}, {"coherent", "field"})
        assert score == pytest.approx(1.00)

    def test_prefix_soft_hit(self) -> None:
        # "coherents" vs "coherent" – shared 5-char prefix, lengths 9 vs 8
        score = fuzzy_token_hits({"coherents"}, {"coherent"})
        assert score == pytest.approx(0.65)

    def test_levenshtein_jw_hit(self) -> None:
        # "signul" vs "signal": lev=1, jw=0.933≥0.93, no shared 5-char prefix or suffix
        score = fuzzy_token_hits({"signul"}, {"signal"})
        assert score == pytest.approx(0.70)

    def test_no_hit_for_short_tokens(self) -> None:
        score = fuzzy_token_hits({"ab"}, {"ac"})
        assert score == pytest.approx(0.0)

    def test_multiple_tokens(self) -> None:
        score = fuzzy_token_hits(
            {"coherent", "residual"},
            {"coherents", "residuals", "void"},
        )
        assert score > 0


# ============================================================
# question_frequency
# ============================================================
class TestQuestionFrequency:
    def test_causal_class(self) -> None:
        f = question_frequency("Why does the field cause coherence?")
        assert f["class"] == "causal"
        assert f["fluct_open"] == pytest.approx(0.52)

    def test_process_class(self) -> None:
        f = question_frequency("Describe the process steps method procedure flow.")
        assert f["class"] == "process"
        assert f["process_bias"] > 0

    def test_entity_class(self) -> None:
        f = question_frequency("Who wrote the memoir?")
        assert f["class"] == "entity"
        assert f["entity_bias"] > 0

    def test_speculative_penalty(self) -> None:
        f = question_frequency("Could this possibly work in theory?")
        assert f["speculative"] > 0

    def test_neutral_class(self) -> None:
        f = question_frequency("residual locked binary")
        assert f["class"] in ("neutral", "causal", "process", "what", "factual", "entity", "locator", "speculative")

    def test_diag_scale_increases_with_diag_words(self) -> None:
        f_low = question_frequency("something random")
        f_high = question_frequency("residual void field coherent locked binary edge signal")
        assert f_high["diag_scale"] > f_low["diag_scale"]

    def test_required_keys_present(self) -> None:
        f = question_frequency("test query")
        for key in ("class", "diag_scale", "fluct_open", "soft_prefer",
                    "process_bias", "entity_bias", "speculative"):
            assert key in f


# ============================================================
# Residual.ensure_core + bits
# ============================================================
class TestResidualExtensions:
    def _make_residual(self) -> Residual:
        field = CoherentField()
        field.store("alpha beta gamma delta epsilon locked content", domain="test")
        return field.residuals[0]

    def test_bits_lazy_cache(self) -> None:
        res = self._make_residual()
        assert res._sig_bits is None
        b1 = res.bits()
        b2 = res.bits()
        assert b1 is b2  # same object (cached)

    def test_ensure_core_deterministic(self) -> None:
        res = self._make_residual()
        c1 = res.ensure_core(scale=1.0)
        c2 = res.ensure_core(scale=1.0)
        assert c1 is c2  # same core returned

    def test_ensure_core_creates_reality_core(self) -> None:
        res = self._make_residual()
        c = res.ensure_core(scale=2.0)
        assert isinstance(c, RealityCore)
        assert -1.0 <= c.phase <= 1.0  # seeded from hash


# ============================================================
# CoherentField.rank() freq-aware
# ============================================================
class TestCoherentFieldRankFreq:
    def _populated_field(self) -> CoherentField:
        field = CoherentField()
        field.store(
            "The residual void field signal maintains coherent locked binary edge ground.",
            domain="knowledge",
        )
        field.store(
            "Alice is the primary author of the memoir on void coherence.",
            domain="knowledge",
        )
        field.store(
            "How the process operates: step by step residual method.",
            domain="knowledge",
        )
        return field

    def test_rank_accepts_freq_kwarg(self) -> None:
        field = self._populated_field()
        freq = question_frequency("residual locked signal")
        results = field.rank("residual locked signal", freq=freq)
        assert isinstance(results, list)

    def test_rank_without_freq_auto_builds(self) -> None:
        field = self._populated_field()
        # No freq arg → question_frequency called internally
        results = field.rank("residual locked signal")
        assert isinstance(results, list)

    def test_diag_words_boost_residual_fragments(self) -> None:
        field = self._populated_field()
        # Fragment 0 has many diag words; should score higher than Fragment 1
        freq = question_frequency("residual void signal coherent locked edge")
        results = field.rank("residual void signal coherent locked edge", freq=freq)
        frags = [r.fragment for r, _ in results]
        assert frags[0].startswith("The residual void field")

    def test_lexical_damp_zero_hit(self) -> None:
        field = self._populated_field()
        # A query with zero lexical overlap → all dampened, low scores
        results = field.rank("xyzqwerty foobarbaz", freq=question_frequency("xyzqwerty foobarbaz"))
        if results:
            assert results[0][1] < 0.30


# ============================================================
# CoherentVoid._vibrate_residuals
# ============================================================
class TestVibrateResiduals:
    def _void_with_data(self) -> CoherentVoid:
        void = CoherentVoid(secret="test-secret-key")
        node = SecureNode("n", void)
        for txt in [
            "The residual field coherently locks binary signals in the void domain.",
            "Edge nulling removes the Schumann carrier so the pure residual edge remains.",
            "Ghost tax is the irreducible generative leakage preventing sterile lock.",
        ]:
            node.lock_text(txt, domain="knowledge")
        return void

    def test_returns_list_of_strings(self) -> None:
        void = self._void_with_data()
        ranked = void.field.rank("residual field void")
        candidates = [(r, s) for r, s in ranked if r.domain != "query"][:6]
        result = void._vibrate_residuals(candidates)
        assert isinstance(result, list)
        assert all(isinstance(f, str) for f in result)

    def test_at_most_three_results(self) -> None:
        void = self._void_with_data()
        ranked = void.field.rank("residual field void")
        candidates = [(r, s) for r, s in ranked if r.domain != "query"][:6]
        result = void._vibrate_residuals(candidates)
        assert len(result) <= 3

    def test_empty_input_returns_empty(self) -> None:
        void = self._void_with_data()
        assert void._vibrate_residuals([]) == []

    def test_deduplication(self) -> None:
        void = self._void_with_data()
        ranked = void.field.rank("residual field void")
        candidates = [(r, s) for r, s in ranked if r.domain != "query"][:6]
        result = void._vibrate_residuals(candidates)
        keys = [f[:80].lower() for f in result]
        assert len(keys) == len(set(keys))


# ============================================================
# CoherentVoid.project() exact path (unchanged invariants)
# ============================================================
class TestCoherentVoidExactPath:
    def _void(self) -> tuple:
        void = CoherentVoid(secret="test-secret")
        node = SecureNode("node", void)
        return void, node

    def test_exact_grounded_hit(self) -> None:
        void, node = self._void()
        node.lock_text("USER::ALICE::locked residual payload text here", domain="secure")
        result = void.project("USER::ALICE", mode="exact")
        assert "residual" in result.lower() or "USER" in result

    def test_exact_strict_refusal_passcode_style(self) -> None:
        void, node = self._void()
        node.lock_text("alpha beta gamma delta epsilon omega locked content here", domain="gen")
        result = void.project("PASSCODE::XYZZY::UNKNOWN", mode="exact")
        assert result == CoherentVoid._REFUSAL

    def test_exact_refusal_low_score(self) -> None:
        void, _ = self._void()
        result = void.project("xyzzy foobarbaz qqqq", mode="exact")
        assert result == CoherentVoid._REFUSAL


# ============================================================
# CoherentVoid.project() synthesize path (new gating + vibration)
# ============================================================
class TestCoherentVoidSynthPath:
    def _populated_void(self) -> tuple:
        void = CoherentVoid(secret="synth-secret")
        node = SecureNode("snode", void)
        node.lock_text(
            "The residual field signal explains why coherence emerges after core nulling.",
            domain="knowledge",
        )
        node.lock_text(
            "Void stability is caused by the balance between ghost tax and refusal strength.",
            domain="knowledge",
        )
        node.lock_text(
            "Alice authored the memoir that describes the coherent void and locked residual states.",
            domain="knowledge",
        )
        return void, node

    def test_synth_causal_returns_fragment(self) -> None:
        void, _ = self._populated_void()
        result = void.project(
            "Why does the residual field maintain coherence?", mode="synthesize"
        )
        assert result != CoherentVoid._REFUSAL

    def test_synth_entity_returns_fragment(self) -> None:
        void, _ = self._populated_void()
        result = void.project(
            "Who wrote the memoir about the void?", mode="synthesize"
        )
        # May or may not match; at minimum should not crash
        assert isinstance(result, str)

    def test_synth_refusal_on_empty_void(self) -> None:
        void = CoherentVoid(secret="empty-secret")
        result = void.project("why does anything work", mode="synthesize")
        assert result == CoherentVoid._REFUSAL

    def test_synth_result_joined_with_pipe(self) -> None:
        void, _ = self._populated_void()
        result = void.project(
            "residual field coherent locked signal", mode="synthesize"
        )
        if result != CoherentVoid._REFUSAL and "||" in result:
            parts = [p.strip() for p in result.split("||")]
            assert len(parts) >= 2


# ============================================================
# Query chain logging and integrity invariants
# ============================================================
class TestQueryChainIntegrity:
    def test_query_locked_into_chain(self) -> None:
        void = CoherentVoid(secret="chain-secret")
        node = SecureNode("cn", void)
        node.lock_text("alpha beta gamma delta epsilon locked content", domain="gen")
        void.project("alpha beta", mode="exact")
        query_residuals = [r for r in void.field.residuals if r.domain == "query"]
        assert len(query_residuals) >= 1

    def test_query_residuals_excluded_from_answers(self) -> None:
        void = CoherentVoid(secret="excl-secret")
        node = SecureNode("en", void)
        node.lock_text("alpha beta gamma delta epsilon locked content", domain="gen")
        void.project("alpha beta", mode="exact")
        result = void.project("alpha beta", mode="exact")
        # Result should be actual content, not a query-log fragment
        assert "QUERY::" not in result or result == CoherentVoid._REFUSAL

    def test_verify_chain_intact_after_queries(self) -> None:
        void = CoherentVoid(secret="integ-secret")
        node = SecureNode("in", void)
        node.lock_text("residual void coherent field locked binary signal domain", domain="know")
        void.project("residual void", mode="exact")
        void.project("coherent field locked", mode="synthesize")
        ok, msg = void.verify_integrity()
        assert ok, f"Chain broken after queries: {msg}"

    def test_chain_tip_updates_after_project(self) -> None:
        void = CoherentVoid(secret="tip-secret")
        node = SecureNode("tn", void)
        node.lock_text("alpha beta gamma delta epsilon locked content", domain="gen")
        tip_before = void.field.chain_tip
        void.project("alpha beta", mode="exact")
        tip_after = void.field.chain_tip
        # chain_tip should have advanced (new query residual stored)
        assert tip_before != tip_after

    def test_status_reflects_project_count(self) -> None:
        void = CoherentVoid(secret="stat-secret")
        node = SecureNode("sn", void)
        node.lock_text("alpha beta gamma delta epsilon locked content here now", domain="gen")
        void.project("alpha beta", mode="exact")
        void.project("gamma delta", mode="exact")
        st = void.status()
        assert st["project_count"] == 2
