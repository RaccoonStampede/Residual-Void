"""Test protected residual handling and safe pruning."""
from src.residual_void.geometry import ResidualGeometry


def test_protected_residuals_survive_pruning(geometry):
    """Verify that protected residuals are never removed during pruning."""
    # Store protected core residuals
    core_ids = [
        geometry.store(
            "Protected core 0",
            coherence=0.98,
            protect=True,
            domain="core",
            preferred_shell=0,
        ),
        geometry.store(
            "Protected core 1",
            coherence=0.97,
            protect=True,
            domain="core",
            preferred_shell=0,
        ),
    ]
    
    # Store unprotected residuals to fill up storage
    for i in range(50):
        geometry.store(
            f"Unprotected residual {i}",
            coherence=0.60,
            protect=False,
            domain="ingested",
        )
    
    initial_protected = sum(1 for item in geometry._data.values() if item["protect"])
    assert initial_protected >= 2, "Core residuals not stored"
    
    # Prune to max 30 items
    removed = geometry.prune(max_items=30)
    assert removed > 0, "Pruning should remove items"
    
    # Check protected count after pruning
    final_protected = sum(1 for item in geometry._data.values() if item["protect"])
    assert final_protected >= initial_protected, "Protected residuals were removed!"
    
    # Core IDs should still exist
    for cid in core_ids:
        assert cid in geometry._data, f"Protected residual {cid} was pruned"


def test_high_coherence_protection(geometry):
    """Verify that high-coherence residuals (>= 0.95) are auto-protected."""
    rid = geometry.store(
        "High coherence text",
        coherence=0.95,  # Will be auto-protected
        protect=False,
        domain="core",
    )
    
    assert geometry._data[rid]["protect"] is True, "High-coherence should be auto-protected"
