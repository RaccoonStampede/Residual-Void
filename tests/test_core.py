import numpy as np
import pytest

from residual_void.core import (
    CoherentField,
    CoherentVoid,
    SecureNode,
    bytes_to_bits,
    hamming_sim,
    hierarchical_edge_extract_v2,
    hmac_sign,
    hmac_verify,
    schumann_carrier,
    sign_packet,
    verify_signature,
)


def test_hierarchical_edge_extraction_nulls_schumann_and_recovers_higher_bands() -> None:
    fs = 8000
    t = np.linspace(0, 1.0, int(fs), endpoint=False)
    measured = (
        0.55 * schumann_carrier(t)
        + 0.09 * np.sin(2 * np.pi * 42 * t)
        + 0.07 * np.sin(2 * np.pi * 180 * t)
        + 0.05 * np.sin(2 * np.pi * 850 * t)
        + 0.03 * np.sin(2 * np.pi * 1500 * t)
    )

    residual, peaks = hierarchical_edge_extract_v2(measured, fs)

    assert abs(float(np.mean(residual))) < 1e-10
    assert np.std(residual) == pytest.approx(1.0, rel=1e-6)
    assert peaks["field_substrate"] == []
    assert [round(freq) for freq, _ in peaks["cytoskeleton"][:2]] == [42, 180]
    assert round(peaks["bioelectric"][0][0]) == 850
    assert round(peaks["cognition"][0][0]) == 1500


def test_hmac_signing_and_binary_secure_payload_verification() -> None:
    secret = "alpha"
    message = "residual-payload"
    signature = hmac_sign(secret, message)

    assert hmac_verify(secret, message, signature) is True
    assert hmac_verify(secret, message + "-tampered", signature) is False

    payload = b"\x00\x01residual"
    raw_signature = sign_packet(payload, secret.encode("utf-8"))
    assert verify_signature(payload, raw_signature, secret.encode("utf-8")) is True
    assert verify_signature(payload + b"x", raw_signature, secret.encode("utf-8")) is False

    packet = SecureNode.lock_payload(payload, secret=secret, metadata={"type": "binary"})
    assert packet["kind"] == "binary"
    assert SecureNode.verify_payload(packet, secret) is True

    tampered = dict(packet, payload="tampered")
    assert SecureNode.verify_payload(tampered, secret) is False


def test_bit_signatures_and_hamming_similarity_cover_binary_payloads() -> None:
    sig_a = bytes_to_bits(b"\x00\x01abc")
    sig_b = bytes_to_bits(b"\x00\x01abc")
    sig_c = bytes_to_bits(b"\x00\x02xyz")

    assert sig_a.dtype == np.uint8
    assert len(sig_a) == 256
    assert hamming_sim(sig_a, sig_b) == 1.0
    assert 0.0 <= hamming_sim(sig_a, sig_c) < 1.0


def test_coherent_field_hash_chain_and_rank() -> None:
    """Lean CoherentField: store returns (ok, reason), verify_chain passes, rank works."""
    field = CoherentField()

    ok1, reason1 = field.store("alpha beta gamma delta", domain="test")
    ok2, reason2 = field.store("alpha beta delta epsilon omega", domain="test")
    ok3, reason3 = field.store("omega psi chi lambda sigma", domain="test")
    # duplicate should be rejected
    ok_dup, reason_dup = field.store("alpha beta gamma delta", domain="test")

    assert ok1 is True and reason1 == "locked"
    assert ok2 is True
    assert ok3 is True
    assert ok_dup is False and reason_dup == "duplicate"

    chain_ok, chain_msg = field.verify_chain()
    assert chain_ok is True, chain_msg
    assert "3 residuals" in chain_msg

    ranked = field.rank("alpha beta")
    assert ranked, "Expected ranked results"
    top_frag = ranked[0][0].fragment
    assert "alpha" in top_frag.lower() or "beta" in top_frag.lower()


def test_coherent_void_lock_and_project_via_secure_node() -> None:
    """Lean CoherentVoid: SecureNode.lock_text ingests, project returns the fragment."""
    void = CoherentVoid(secret="alpha")
    node = SecureNode("test_node", void)

    result = node.lock_text("USER::ALICE::locked residual payload text", domain="secure")
    assert result == "locked", f"Expected 'locked', got {result!r}"

    projected = node.project("USER::ALICE", mode="exact")
    assert "locked residual payload text" in projected or "USER" in projected

    ok, msg = void.verify_integrity()
    assert ok is True, msg


def test_coherent_void_refuses_low_scoring_projection() -> None:
    void = CoherentVoid(secret="alpha")
    node = SecureNode("n", void)

    result = node.lock_text("alpha beta gamma delta epsilon locked content here", domain="general")
    assert result == "locked"

    refused = void.project("something completely unrelated xyz abc qqq", mode="exact")
    assert refused == CoherentVoid._REFUSAL
