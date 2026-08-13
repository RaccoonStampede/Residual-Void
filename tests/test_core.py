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


def test_coherent_field_message_passing_and_laplacian_spectrum() -> None:
    field = CoherentField(graph_similarity_threshold=0.45)
    for payload in (
        "alpha beta gamma",
        "alpha beta delta",
        "alpha gamma delta",
        "omega psi chi",
    ):
        field.store(payload)

    no_mp = {item.payload: score for item, score in field.rank("alpha beta", use_mp=False)}
    with_mp = {item.payload: score for item, score in field.rank("alpha beta", use_mp=True, mp_layers=2)}
    spectrum = field.compute_laplacian_spectrum()

    assert with_mp["alpha gamma delta"] > no_mp["alpha gamma delta"]
    assert max(with_mp, key=with_mp.get) in {"alpha beta gamma", "alpha beta delta"}
    assert spectrum["n"] == 4
    assert spectrum["lambda2"] > 0.0
    assert spectrum["multiplicity0"] == 1


def test_coherent_void_confirms_binary_payloads() -> None:
    void = CoherentVoid(secret="alpha")
    packet = SecureNode.lock_payload(b"\x00\x01abc", secret="alpha")

    lock_id = void.authenticated_ingest_lock(packet)
    residual = void.confirm(lock_id)

    assert residual is not None
    assert residual.kind == "binary"
    assert residual.payload == "AAFhYmM="
    projected = void.project(residual.payload, require_grounding=False)
    assert projected[0][0].payload == residual.payload
