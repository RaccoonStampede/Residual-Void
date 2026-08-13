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


def test_network_lock_and_project_lean(network_manager: ResidualNetworkManager) -> None:
    """Lock text via a network node and project back through lean void."""
    runtime = network_manager.create_network("lean_net", "lean-secret-abc123")
    node = network_manager.add_node("lean_net", "node_a")

    result = node.lock_text("Lean network residual payload content alpha", domain="general")
    assert result == "locked", f"Expected 'locked', got {result!r}"

    projected = runtime.project("lean network residual", mode="exact")
    assert projected["results"], "Expected project results"
    assert "Lean network residual" in projected["results"][0]["payload"]
