"""Test nested shell placement and core keyword promotion."""
from residual_void.geometry import ResidualGeometry, SHELL_LABELS


def test_shell_labels_defined():
    """Verify that all four shells are defined with correct labels."""
    expected = {
        0: "field_substrate",
        1: "cytoskeleton_microtubules",
        2: "cell_bioelectric",
        3: "neural_cognition",
    }
    assert SHELL_LABELS == expected, f"Shell labels mismatch: {SHELL_LABELS}"


def test_core_keyword_promotion(geometry):
    """Verify that core keywords (field, zero, god) are promoted to shell 0."""
    # Store with core keywords
    rid_field = geometry.store(
        "Field substrate is fundamental",
        coherence=0.80,
    )
    rid_zero = geometry.store(
        "Zero Point emergence",
        coherence=0.80,
    )
    
    # Both should be in shell 0
    assert geometry._data[rid_field]["shell"] == 0, "Core keyword 'field' not promoted to shell 0"
    assert geometry._data[rid_zero]["shell"] == 0, "Core keyword 'zero' not promoted to shell 0"


def test_shell_occupancy_reporting(geometry):
    """Verify that shell_occupancy is reported in status."""
    # Store in different shells
    geometry.store("Field substrate", coherence=0.85)  # shell 0
    geometry.store("Unrelated text", coherence=0.80)  # Fibonacci
    geometry.store("Another unrelated", coherence=0.75)  # Fibonacci
    
    status = geometry.status()
    
    assert "shell_occupancy" in status, "shell_occupancy missing from status"
    occupancy = status["shell_occupancy"]
    
    # At least shell 0 should have occupancy > 0
    assert occupancy.get("field_substrate", 0) > 0, "Shell 0 has no occupancy"
