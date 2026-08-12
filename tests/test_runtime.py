from residual_void import ResidualGeometry, ResidualNetworkManager, ResidualVoid, SecureNode


def test_auth_failure_on_wrong_signature() -> None:
    runtime = ResidualVoid(secret="alpha")
    packet = SecureNode.lock_payload("secure payload", secret="wrong")
    lock_id = runtime.authenticated_ingest_lock(packet)
    assert lock_id is None


def test_lock_and_project_happy_path() -> None:
    runtime = ResidualVoid(secret="alpha")
    packet = SecureNode.lock_payload("coherent hello world", secret="alpha")
    lock_id = runtime.authenticated_ingest_lock(packet)
    assert lock_id is not None
    residual = runtime.confirm(lock_id)
    assert residual is not None

    projected = runtime.project("hello")
    assert projected["results"]


def test_network_isolation_between_secrets() -> None:
    manager = ResidualNetworkManager()
    net_a = manager.create_network("a", "secret-a")
    manager.create_network("b", "secret-b")

    assert manager.get_network("a", "secret-a") is net_a
    assert manager.get_network("a", "secret-b") is None
    assert manager.status("b", "secret-a").get("error") == "network not found or unauthorized"


def test_geometry_store_query_smoke() -> None:
    geometry = ResidualGeometry()
    geometry.store("alpha beta gamma")
    geometry.store("delta epsilon")

    ranked = geometry.query("alpha")
    assert ranked
    assert ranked[0][1] >= 0.0


def test_signed_envelope_contains_nonce_and_timing_claims() -> None:
    packet = SecureNode.lock_payload("release candidate", secret="alpha")

    assert "nonce" in packet
    assert "iat" in packet
    assert "exp" in packet
    assert "kid" in packet
    assert SecureNode.verify_payload(packet, "alpha")


def test_network_replay_protection_rejects_duplicate_nonce() -> None:
    manager = ResidualNetworkManager()
    manager.create_network("a", "secret-a")

    packet = SecureNode.lock_payload("coherence replay check", secret="secret-a")
    assert manager.validate_message("a", "secret-a", packet) is True
    assert manager.validate_message("a", "secret-a", packet) is False
