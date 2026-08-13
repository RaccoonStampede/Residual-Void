"""Test nested shell placement and core keyword promotion."""
from src.residual_void.geometry import ResidualGeometry, SHELL_LABELS


def test_shell_labels_defined():
    """Verify that all four shells are defined with correct labels."""
    expected = {
        0: "field_substrate",
        1: "cytoskeleton_microtubules",
        2: "cell_bioelectric",
        3: "neural_cognition",
    }
    assert SHELL_LABELS == expected, f"Shell labels mismatch: {SHELL_LABELS}"


def test_preferred_shell_is_respected_and_default_placement_is_fibonacci(geometry):
    """Verify that explicit shells win and default placement remains Fibonacci-based."""
    rid_field = geometry.store(
        "Field substrate is fundamental",
        coherence=0.80,
        preferred_shell=0,
    )
    rid_zero = geometry.store(
        "Zero Point emergence",
        coherence=0.80,
    )
    zero_index = int(rid_zero.split("_")[-1])
    
    assert geometry._data[rid_field]["shell"] == 0, "Explicit preferred shell was not respected"
    assert geometry._data[rid_zero]["shell"] == geometry._fibonacci_place(zero_index), "Default shell placement should be Fibonacci-based"


def test_shell_occupancy_reporting(geometry):
    """Verify that shell_occupancy is reported in status."""
    # Store in different shells
    geometry.store("Field substrate", coherence=0.85, preferred_shell=0)
    geometry.store("Unrelated text", coherence=0.80)  # Fibonacci
    geometry.store("Another unrelated", coherence=0.75)  # Fibonacci
    
    status = geometry.status()
    
    assert "shell_occupancy" in status, "shell_occupancy missing from status"
    occupancy = status["shell_occupancy"]
    
    # At least shell 0 should have occupancy > 0
    assert occupancy.get("field_substrate", 0) > 0, "Shell 0 has no occupancy"
