"""Test multi-timescale imprint layers (fast, medium, deep)."""
from src.residual_void.geometry import ResidualGeometry
from src.residual_void.mind import ResidualFieldMind


def test_imprint_layer_tracking(geometry):
    """Verify that imprint layers are tracked separately."""
    # Store in each layer
    geometry.store(
        "Fast imprint text",
        coherence=0.80,
        imprint_layer="fast",
    )
    geometry.store(
        "Medium imprint text",
        coherence=0.85,
        imprint_layer="medium",
    )
    geometry.store(
        "Deep imprint text",
        coherence=0.90,
        imprint_layer="deep",
    )
    
    # Check that norms are tracked
    assert geometry.imprint_fast_norm > 0, "Fast imprint norm not tracked"
    assert geometry.imprint_medium_norm > 0, "Medium imprint norm not tracked"
    assert geometry.imprint_deep_norm > 0, "Deep imprint norm not tracked"
    
    # Deep should typically have highest norm (higher coherence)
    status = geometry.status()
    assert status["imprint_deep_norm"] > 0, "Deep norm missing from status"
    assert status["imprint_medium_norm"] > 0, "Medium norm missing from status"
    assert status["imprint_fast_norm"] > 0, "Fast norm missing from status"


def test_imprint_decay_on_pulse(geometry):
    """Verify that imprint layers decay at different rates on pulse."""
    # Store in all layers
    for layer in ["fast", "medium", "deep"]:
        geometry.store(
            f"{layer} text",
            coherence=0.85,
            imprint_layer=layer,
        )
    
    norms_before = {
        "fast": geometry.imprint_fast_norm,
        "medium": geometry.imprint_medium_norm,
        "deep": geometry.imprint_deep_norm,
    }
    
    # Run decay steps
    for _ in range(5):
        geometry.decay_step()
    
    norms_after = {
        "fast": geometry.imprint_fast_norm,
        "medium": geometry.imprint_medium_norm,
        "deep": geometry.imprint_deep_norm,
    }
    
    # All should decay, but at different rates
    assert norms_after["fast"] < norms_before["fast"], "Fast did not decay"
    assert norms_after["medium"] < norms_before["medium"], "Medium did not decay"
    assert norms_after["deep"] < norms_before["deep"], "Deep did not decay"
    
    # Deep should decay slowest: 0.99^5 ≈ 0.95, Medium ≈ 0.90, Fast ≈ 0.77
    fast_decay_rate = norms_after["fast"] / norms_before["fast"] if norms_before["fast"] > 0 else 0
    deep_decay_rate = norms_after["deep"] / norms_before["deep"] if norms_before["deep"] > 0 else 0
    
    assert deep_decay_rate > fast_decay_rate, "Deep should decay slower than fast"


def test_mind_ingest_layers(mind):
    """Verify that mind.ingest_* methods use correct imprint layers."""
    mind.ingest_text("Test text")
    status = mind.geometry.status()
    assert status["imprint_fast_norm"] > 0, "ingest_text should use fast layer"
    
    mind.ingest_binary(b"Test binary")
    status = mind.geometry.status()
    assert status["imprint_medium_norm"] > 0, "ingest_binary should use medium layer"
