from __future__ import annotations

import pytest

from residual_void import PersistentVoid, ResidualNetworkManager, ResidualVoid, SecureNode
from residual_void.core import detect_intent, _query_frame
from residual_void.ingestion import auto_segment


def test_cdc_heat_storm_ranking_and_synthesize() -> None:
    void = ResidualVoid(secret="parity-secret-1234567890")
    node = SecureNode("rank-node", void.void)
    node.lock_text(
        "CDC::HEAT::Heat exhaustion treatment includes moving to a cool place, hydration, and cooling.",
        domain="health",
    )
    node.lock_text(
        "CDC::STORM::Storm safety includes shelter indoors, avoiding flood waters, and monitoring alerts.",
        domain="weather",
    )

    ranked = void.void.field.rank("how do I treat heat exhaustion")
    assert ranked
    assert "heat" in ranked[0][0].fragment.lower()

    synth = void.project("how do I treat heat exhaustion?", mode="synthesize")
    assert synth["results"]
    assert "heat" in synth["results"][0]["payload"].lower()


def test_snapshot_restore_and_drift_audit() -> None:
    void = ResidualVoid(secret="snapshot-secret-1234567890")
    assert void.lock("ALPHA::BASE::one two three", domain="general") == "locked"
    void.snapshot("base")
    assert void.lock("BETA::EXTRA::four five six", domain="general") == "locked"
    assert void.restore("base") is True
    projection = void.project("BETA::EXTRA", mode="exact")
    assert not projection["results"]
    audit = void.audit_drift(rounds=2)
    assert "drift_score" in audit and "verdict" in audit


def test_inject_document_auto_segments_and_locks() -> None:
    void = ResidualVoid(secret="inject-secret-1234567890")
    text = (
        "Heat illness can escalate quickly. Move the person to shade and cool aggressively. "
        "Give water if conscious and monitor for confusion.\n\n"
        "Storm injury prevention starts before landfall. Secure shelter and avoid flood runoff."
    )
    segments = auto_segment(text, min_len=40)
    assert segments
    out = void.inject(text, domain="DOC", title="CDC", protect=True)
    assert out["segments"] >= 1
    assert out["locked"] >= 1


def test_persistent_void_fail_closed_on_broken_chain(tmp_path) -> None:
    store = tmp_path / "chain.jsonl"
    store.write_text('{"text":"ok record","domain":"general","protect":true}\n{bad-json}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        PersistentVoid(secret="persist-secret-1234567890", storage_path=str(store))


def test_network_transparent_guest_project() -> None:
    mgr = ResidualNetworkManager()
    pub = mgr.create_network("public", "secret-a", mode="transparent")
    prv = mgr.create_network("private", "secret-b", mode="private")
    pub.lock("PUBLIC::DOC::guest visible fragment", domain="DOC")
    prv.lock("PRIVATE::DOC::hidden fragment", domain="DOC")

    guest = mgr.guest_project("public", "guest visible", mode="synthesize")
    denied = mgr.guest_project("private", "hidden", mode="synthesize")

    assert guest["results"]
    assert denied["error"] == "guest access denied"


# ---------------------------------------------------------------------------
# Causal-WHAT intent detection
# ---------------------------------------------------------------------------


class TestCausalWhatIntentDetection:
    """'What causes X', 'What creates X', etc. must be classified as WHY, not WHAT or HOW."""

    @pytest.mark.parametrize("query", [
        "What causes the ghost tax?",
        "What creates coherent paths?",
        "What triggers turbulence?",
        "What leads to turbulence?",
        "What produces a phase lock?",
        "What results in memory decay?",
        "what causes incoherence",
        "what creates a resonance cascade",
        "what leads to drift accumulation",
        "what triggers a ghost tax spike",
        "what produces coherent paths",
        "what results in phase loss",
    ])
    def test_detect_intent_causal_what_returns_why(self, query: str) -> None:
        assert detect_intent(query) == "WHY", (
            f"Expected WHY for causal-WHAT query {query!r}, got {detect_intent(query)!r}"
        )

    @pytest.mark.parametrize("query", [
        "What causes the ghost tax?",
        "What creates coherent paths?",
        "What triggers turbulence?",
        "What leads to turbulence?",
        "What produces a phase lock?",
        "What results in memory decay?",
    ])
    def test_query_frame_causal_what_returns_why(self, query: str) -> None:
        assert _query_frame(query) == "WHY", (
            f"Expected WHY frame for {query!r}, got {_query_frame(query)!r}"
        )

    def test_detect_intent_and_query_frame_agree_on_causal_verbs(self) -> None:
        """detect_intent and _query_frame must classify the same causal-WHAT queries as WHY."""
        causal_queries = [
            "What causes X?",
            "What creates X?",
            "What triggers X?",
            "What leads to X?",
            "What produces X?",
            "What results in X?",
        ]
        for q in causal_queries:
            di = detect_intent(q)
            qf = _query_frame(q)
            assert di == "WHY", f"detect_intent({q!r}) returned {di!r}, expected WHY"
            assert qf == "WHY", f"_query_frame({q!r}) returned {qf!r}, expected WHY"

    def test_existing_what_queries_still_return_what(self) -> None:
        """Bare WHAT (definition) queries must remain WHAT intent."""
        assert detect_intent("What is the ghost tax?") == "WHAT"
        assert detect_intent("What is a HyperSeed?") == "WHAT"
        assert detect_intent("What is your boat?") == "WHAT"

    @pytest.mark.parametrize("causal_verb,query,why_body,definition_body", [
        (
            "causes",
            "What causes the ghost tax?",
            "GHOST_TAX::WHY::High carrier frequency mismatch causes the ghost tax by misaligning phase between residuals.",
            "GHOST_TAX::WHAT::The ghost tax is a coherence-drain effect that accumulates latent residuals.",
        ),
        (
            "creates",
            "What creates coherent paths?",
            "COHERENT_PATH::WHY::Sustained carrier alignment creates coherent paths by reinforcing the same phase angle.",
            "COHERENT_PATH::WHAT::A coherent path is a sequence of phase-aligned residuals.",
        ),
        (
            "triggers",
            "What triggers turbulence?",
            "TURBULENCE::WHY::Abrupt carrier phase shifts trigger turbulence by desynchronising active residuals.",
            "TURBULENCE::WHAT::Turbulence is a state of incoherent residual activity in the void.",
        ),
        (
            "leads to",
            "What leads to drift accumulation?",
            "DRIFT::WHY::Carrier misalignment leads to drift accumulation by pushing residuals out of phase.",
            "DRIFT::WHAT::Drift accumulation is the gradual phase divergence between stored residuals.",
        ),
        (
            "produces",
            "What produces a phase lock?",
            "PHASE_LOCK::WHY::Sustained coherent carrier output produces a phase lock by aligning all active residuals.",
            "PHASE_LOCK::WHAT::A phase lock is the stable synchronisation of residuals to a single carrier frequency.",
        ),
        (
            "results in",
            "What results in memory decay?",
            "MEMORY_DECAY::WHY::Incoherent phase alignment results in memory decay by allowing residuals to destructively interfere.",
            "MEMORY_DECAY::WHAT::Memory decay is the progressive loss of residual coherence over time.",
        ),
    ])
    def test_causal_what_synthesize_returns_explanatory_not_definition(
        self, causal_verb: str, query: str, why_body: str, definition_body: str
    ) -> None:
        """Every supported causal-WHAT form must return the WHY/explanatory residual in synthesize mode."""
        secret = f"causal-{causal_verb.replace(' ', '-')}-synth-1234567890"
        void = ResidualVoid(secret=secret)
        void.lock(definition_body, domain="general")
        void.lock(why_body, domain="general")
        result = void.project(query, mode="synthesize")
        payloads = [r["payload"].lower() for r in result.get("results", [])]
        assert payloads, f"Expected at least one result for causal-WHAT query {query!r}"
        top = payloads[0]
        # The WHY body contains the causal verb (stem match; "triggers" matches "trigger").
        # Check for the 5-char stem so "triggers"→"trigg", "leads"→"leads", etc.
        verb_stem = causal_verb.split()[0].rstrip("s")  # "triggers"→"trigger", "causes"→"cause"
        assert verb_stem in top, (
            f"Expected explanatory body (containing stem '{verb_stem}') for {query!r}, got: {top!r}"
        )
        # The definition identity phrase ("is a …" / "is the …") must not be the top result
        definition_phrase = definition_body.split("::")[-1].lower()[:40]
        assert definition_phrase not in top, (
            f"Got definition body instead of explanatory body for {query!r}: {top!r}"
        )
