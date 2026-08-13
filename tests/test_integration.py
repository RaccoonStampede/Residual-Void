from residual_void import ResidualNetworkManager, SecureNode


def test_end_to_end_lock_confirm_project_workflow(runtime) -> None:
    packet = SecureNode.lock_payload("coherent hello world", secret="alpha", metadata={"flow": "e2e"})

    lock_id = runtime.authenticated_ingest_lock(packet)
    residual = runtime.confirm(lock_id)
    projected = runtime.project("coherent hello")

    assert residual is not None
    assert projected["source"] == "surface"
    assert projected["results"][0]["payload"] == "coherent hello world"
    assert projected["results"][0]["metadata"] == {"flow": "e2e"}


def test_binary_payload_round_trip_across_surface_and_mind(runtime) -> None:
    packet = SecureNode.lock_payload(b"\x00\x01abc", secret="alpha", metadata={"format": "bin"})

    lock_id = runtime.authenticated_ingest_lock(packet)
    residual = runtime.confirm(lock_id)

    assert residual is not None
    assert residual.kind == "binary"
    assert runtime.project(residual.payload)["results"][0]["kind"] == "binary"
    assert runtime.mind.project(residual.payload)[0]["payload"] == residual.payload


def test_message_passing_coherence_propagates_across_related_surface_residuals(runtime) -> None:
    for payload in (
        "alpha beta gamma",
        "alpha beta delta",
        "alpha gamma delta",
    ):
        assert runtime.lock_and_confirm(payload) is True

    without_mp = {
        item.payload: score
        for item, score in runtime.surface.field.rank("alpha beta", use_mp=False)
    }
    with_mp = {
        item.payload: score
        for item, score in runtime.surface.field.rank("alpha beta", use_mp=True, mp_layers=2)
    }
    projected = runtime.project("alpha beta")

    assert with_mp["alpha gamma delta"] > without_mp["alpha gamma delta"]
    assert projected["source"] == "surface"
    assert projected["results"]


def test_multi_network_integration_scenario(runtime_config) -> None:
    manager = ResidualNetworkManager()
    source = manager.create_network("source", "source-secret", config=runtime_config)
    target = manager.create_network("target", "target-secret", config=runtime_config)

    packet = SecureNode.lock_payload("network bridge residual", secret="source-secret")
    lock_id = source.authenticated_ingest_lock(packet)
    source.confirm(lock_id)

    bridged = manager.cross_network_bridge(
        "source",
        "source-secret",
        "target",
        "target-secret",
        "network bridge",
    )

    assert bridged
    assert manager.get_network("target", "wrong-secret") is None
    target_projection = target.project("network bridge")
    assert target_projection["source"] == "geometry"
    assert any("network bridge residual" in item["payload"] for item in target_projection["results"])
