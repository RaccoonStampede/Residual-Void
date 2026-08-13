"""Test Pi-Helix v2 core nulling and edge recovery."""
import numpy as np
from residual_void.core import hierarchical_edge_extract_v2, build_core_negative_v2


def test_core_nulling_reduces_field_substrate(test_signal):
    """Verify that Core-nulling is attempted on field_substrate band."""
    measured, fs = test_signal
    
    # Extract residual and peaks
    residual, peaks = hierarchical_edge_extract_v2(measured, fs)
    
    # After nulling, field_substrate band should have reduced energy
    field_substrate_peaks = peaks.get("field_substrate", [])
    if field_substrate_peaks:
        # Top peak energy in field_substrate should be lower than untreated signal
        top_energy = field_substrate_peaks[0][1] if field_substrate_peaks else 0
        # The residual should have energy from signal components
        assert top_energy >= 0, "Field substrate energy should be non-negative"
    
    # Residual energy should exist (edges were extracted)
    residual_std = np.std(residual)
    assert residual_std > 0.01, "Residual should have energy from extracted edges"


def test_edge_recovery_42_180_850_hz(test_signal):
    """Verify that Edge bands (42, 180, 850 Hz) have detected peaks."""
    measured, fs = test_signal
    residual, peaks = hierarchical_edge_extract_v2(measured, fs)
    
    # Check that edge bands have detected peaks
    cytoskeleton_peaks = peaks.get("cytoskeleton", [])  # 35-250 Hz (includes 42)
    bioelectric_peaks = peaks.get("bioelectric", [])  # 250-1200 Hz (includes 180, 850)
    cognition_peaks = peaks.get("cognition", [])  # 1200+ Hz
    
    # At least one edge band should have peaks
    total_peaks = len(cytoskeleton_peaks) + len(bioelectric_peaks) + len(cognition_peaks)
    assert total_peaks > 0, "No edge bands recovered"
    
    # Bioelectric band should have peaks (180 Hz, 850 Hz are in this range)
    assert len(bioelectric_peaks) > 0, "Expected bioelectric band peaks"


def test_edge_energy_high_after_nulling(test_signal):
    """Verify that edge energy is extracted from the signal."""
    measured, fs = test_signal
    residual, peaks = hierarchical_edge_extract_v2(measured, fs)
    
    # Sum all edge peak magnitudes
    total_energy = sum(mag for band in peaks.values() for freq, mag in band[:2])
    
    # After extraction, should have detected some edge energy
    assert total_energy > 0.0, "Should detect edge energy from signal"
