import base64

from residual_void import ResidualNetworkManager, SecureNode


def test_multi_network_isolation_and_node_management(network_manager: ResidualNetworkManager) -> None:
    network_manager.create_network("alpha", "secret-a", initial_nodes=["n1"])
    network_manager.create_network("beta", "secret-b")

    node = network_manager.add_node("alpha", "n2")

    assert network_manager.list_networks() == ["alpha", "beta"]
    assert network_manager.get_node("alpha", "n1") is not None
    assert network_manager.get_node("alpha", "n2") is node
    assert network_manager.get_network("alpha", "secret-a") is not None
    assert network_manager.get_network("alpha", "secret-b") is None
    assert network_manager.status("beta", "secret-a")["error"] == "network not found or unauthorized"


def test_key_rotation_with_grace_period_and_replay_protection(network_manager: ResidualNetworkManager) -> None:
    network_manager.create_network("alpha", "secret-new")
    network_manager.set_key_rotation("alpha", active_secret="secret-new", previous_secret="secret-old", grace_seconds=300)
    packet = SecureNode.lock_payload("rotated payload", secret="secret-old")

    assert network_manager.validate_message("alpha", "secret-old", packet) is True
    assert network_manager.validate_message("alpha", "secret-old", packet) is False


def test_void_and_geometry_sync_preserve_binary_payloads(network_manager: ResidualNetworkManager) -> None:
    runtime = network_manager.create_network("alpha", "secret-a")
    packet = SecureNode.lock_payload(b"\x00\x01abc", secret="secret-a")
    lock_id = runtime.authenticated_ingest_lock(packet)
    residual = runtime.confirm(lock_id)

    synced = network_manager.void_to_geometry_sync("alpha", "secret-a")
    # The regression here was base64-encoding an already base64-encoded payload.
    double_encoded = base64.b64encode(residual.payload.encode("ascii")).decode("ascii")
    mind_values = [item["value"] for item in runtime.mind.geometry._data.values()]

    assert synced == 1
    assert residual.payload in mind_values
    assert double_encoded not in mind_values


def test_geometry_to_void_sync_and_cross_network_bridge(network_manager: ResidualNetworkManager) -> None:
    source = network_manager.create_network("source", "secret-source")
    target = network_manager.create_network("target", "secret-target")

    packet = SecureNode.lock_payload("bridge signal alpha beta", secret="secret-source")
    lock_id = source.authenticated_ingest_lock(packet)
    source.confirm(lock_id)

    bridged = network_manager.cross_network_bridge(
        "source",
        "secret-source",
        "target",
        "secret-target",
        "bridge alpha",
        top_k=2,
    )

    target.mind.geometry.store("echo from geometry alpha beta", coherence=0.96, domain="sync")
    pushed = network_manager.geometry_to_void_sync("target", "secret-target", min_coherence=0.95)
    projected = target.project("echo from geometry alpha")

    assert bridged
    assert any("bridge signal alpha beta" in item["payload"] for item in bridged)
    assert pushed >= 1
    assert projected["results"]
    assert any("echo from geometry alpha beta" in item["payload"] for item in projected["results"])
