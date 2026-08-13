"""End-to-end integration tests for the lean ResidualVoid façade."""
from residual_void.merged import ResidualVoid
from residual_void.core import SecureNode, CoherentVoid, CoherentField


def test_end_to_end_lock_confirm_project():
    """Test full workflow: lock_and_confirm → project via lean façade."""
    runtime = ResidualVoid(secret="test-secret-1234567890abcdef")

    ok = runtime.lock_and_confirm("Test residual content for query matching")
    assert ok is True, "lock_and_confirm failed"

    result = runtime.project("test residual", mode="exact")
    assert result is not None, "Project returned None"
    assert "results" in result, "Missing results key"


def test_verify_integrity_after_multiple_locks():
    """Hash-chain integrity holds after several locks."""
    runtime = ResidualVoid(secret="integrity-test-secret-abcdef123")

    for text in [
        "Alpha residual – first locked fragment here",
        "Beta residual – second locked fragment here",
        "Gamma residual – third locked fragment here",
    ]:
        assert runtime.lock_and_confirm(text) is True

    ok, msg = runtime.verify_integrity()
    assert ok is True, f"Chain integrity failed: {msg}"
    assert "3 residuals" in msg


def test_hash_chain_tamper_detection():
    """Mutating a stored fragment breaks verify_chain."""
    field = CoherentField()
    field.store("alpha beta gamma delta epsilon first residual", node_id="test")
    field.store("alpha beta gamma delta epsilon second residual", node_id="test")

    ok, _ = field.verify_chain()
    assert ok is True

    # Tamper with a stored fragment
    field.residuals[0] = field.residuals[0].__class__(
        fragment="TAMPERED CONTENT",
        sig_packed=field.residuals[0].sig_packed,
        content_set=field.residuals[0].content_set,
        domain=field.residuals[0].domain,
        timestamp=field.residuals[0].timestamp,
        version=field.residuals[0].version,
        node_id=field.residuals[0].node_id,
        residual_id=field.residuals[0].residual_id,
        prev_hash=field.residuals[0].prev_hash,
        chain_hash=field.residuals[0].chain_hash,
        protect=field.residuals[0].protect,
    )

    ok_after, msg = field.verify_chain()
    assert ok_after is False, "Tampered chain should fail verify_chain"
    assert "hash mismatch" in msg or "break" in msg


def test_exact_vs_synthesize_projection():
    """Exact mode returns first precise match; synthesize mode joins top results."""
    void = CoherentVoid(secret="projection-test-secret-key-abc")
    node = SecureNode("n", void)

    node.lock_text("CMD::DEPLOY::production system active monitoring ready", domain="cmd")
    node.lock_text("CMD::STATUS::all systems online and healthy reporting green", domain="cmd")

    exact = void.project("CMD::DEPLOY", mode="exact")
    assert "CMD::DEPLOY" in exact, f"Exact mode should return deploy fragment, got: {exact!r}"

    synth = void.project("CMD", mode="synthesize")
    assert synth != CoherentVoid._REFUSAL, "Synthesize should find results for CMD"


def test_refusal_gate_on_unrelated_query():
    """Project refuses when no residual matches the query."""
    void = CoherentVoid(secret="refusal-gate-test-key-abcdef-xyz")
    node = SecureNode("n", void)
    node.lock_text("specific domain alpha beta gamma locked fragment payload", domain="test")

    refused = void.project("zzz completely unrelated qqqq xyz zyx", mode="exact")
    assert refused == CoherentVoid._REFUSAL
