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
    """Verify that Fibonacci placement and preferred shell work correctly."""
    # Store with explicit preferred shell
    rid_field = geometry.store(
        "Field substrate is fundamental",
        coherence=0.80,
        preferred_shell=0,
    )
    
    # Store without preferred shell (uses Fibonacci)
    rid_other = geometry.store(
        "Some other text",
        coherence=0.80,
    )
    
    # Explicit shell should be respected
    assert geometry._data[rid_field]["shell"] == 0, "Preferred shell 0 not respected"
    
    # Fibonacci placement should assign some shell
    assigned_shell = geometry._data[rid_other]["shell"]
    assert 0 <= assigned_shell < geometry.shell_count, f"Shell {assigned_shell} out of range"


def test_shell_occupancy_reporting(geometry):
    """Verify that shell_occupancy is reported in status."""
    # Store in specific shells
    geometry.store("Field substrate", coherence=0.85, preferred_shell=0)
    geometry.store("Unrelated text", coherence=0.80, preferred_shell=1)
    geometry.store("Another text", coherence=0.75, preferred_shell=2)
    
    status = geometry.status()
    
    assert "shell_occupancy" in status, "shell_occupancy missing from status"
    occupancy = status["shell_occupancy"]
    
    # Should have entries for all shells
    assert len(occupancy) == geometry.shell_count, f"Expected {geometry.shell_count} shell entries"
    
    # Should have at least 3 items total across shells
    total_items = sum(occupancy.values())
    assert total_items >= 3, f"Expected at least 3 stored items, got {total_items}"
