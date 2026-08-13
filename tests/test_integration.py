"""End-to-end integration tests."""
from residual_void.merged import ResidualVoid
from residual_void.core import SecureNode


def test_end_to_end_lock_confirm_project():
    """Test full workflow: lock → confirm → project."""
    runtime = ResidualVoid(secret="test-secret-1234567890abcdef")
    
    # Lock a payload
    packet = SecureNode.lock_payload(
        "Test residual content",
        runtime.surface._secret,
        metadata={"source": "test"},
    )
    
    lock_id = runtime.authenticated_ingest_lock(packet)
    assert lock_id is not None, "Lock failed"
    
    # Confirm
    residual = runtime.surface.confirm(lock_id)
    assert residual is not None, "Confirm failed"
    assert residual.payload == "Test residual content", "Payload mismatch"
    
    # Project
    result = runtime.project("test residual", top_k=1)
    assert result is not None, "Project failed"
    assert "results" in result, "Missing results key"


def test_mind_grounding_validation():
    """Test grounding validation in respond()."""
    runtime = ResidualVoid(secret="test-secret-1234567890abcdef")
    
    # Inject some text
    runtime.mind.inject_rich(
        "The field substrate is the foundation. Integration is key.",
        passes=1,
    )
    
    # Respond with valid query
    response = runtime.mind.respond("field integration", show=False)
    assert response is not None, "Respond failed"
    assert "Voice:" in response, "Missing Voice in response"
    assert "Watcher:" in response, "Missing Watcher in response"
