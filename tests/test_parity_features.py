from __future__ import annotations

import pytest

from residual_void import PersistentVoid, ResidualNetworkManager, ResidualVoid, SecureNode
from residual_void.ingestion import _SENTENCE_TARGET_MAX, auto_segment


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


def test_auto_segment_sentence_fallback_for_plain_text() -> None:
    text = (
        "Plain ingestion text should still split into sensible residual chunks even without structural markers. "
        "The fallback should group nearby sentences together so each chunk stays readable and useful for retrieval. "
        "This sample intentionally avoids headers and blank lines while keeping enough content to trigger the sentence-based path. "
        "Each sentence contributes more detail about segmentation quality, retrieval stability, and downstream locking behavior. "
        "The resulting residuals should no longer collapse into one oversized wall of text during ingestion."
    )
    segments = auto_segment(text, min_len=40)
    assert len(segments) >= 2
    assert all(segment.count("::") >= 2 for segment in segments)
    bodies = [segment.split("::", 2)[2] for segment in segments]
    assert all(body.strip() and len(body) <= _SENTENCE_TARGET_MAX for body in bodies)


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
