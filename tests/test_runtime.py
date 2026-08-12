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
