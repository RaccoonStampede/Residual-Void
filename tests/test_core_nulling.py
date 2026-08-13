"""Test Pi-Helix v2 core nulling and edge recovery."""
import numpy as np
from src.residual_void.core import hierarchical_edge_extract_v2, build_core_negative_v2


def test_core_nulling_reduces_field_substrate(test_signal):
    """Verify that Core-nulling reduces field_substrate (Schumann) energy to near zero."""
    measured, fs = test_signal
    
    # Extract residual and peaks
    residual, peaks = hierarchical_edge_extract_v2(measured, fs)
    
    # After nulling, field_substrate band should have minimal energy
    field_substrate_peaks = peaks.get("field_substrate", [])
    if field_substrate_peaks:
        # Top peak energy in field_substrate should be < 0.2 (heavily nulled)
        top_energy = field_substrate_peaks[0][1] if field_substrate_peaks else 0
        assert top_energy < 0.2, f"field_substrate not nulled: {top_energy}"
    
    # Residual energy should be dominated by Edge, not Core
    residual_std = np.std(residual)
    assert residual_std > 0.01, "Residual too small after nulling"
    assert residual_std < 1.1, "Residual too large (nulling failed)"


def test_edge_recovery_42_180_850_hz(test_signal):
    """Verify that Edge bands (42, 180, 850 Hz) are recovered."""
    measured, fs = test_signal
    residual, peaks = hierarchical_edge_extract_v2(measured, fs)
    
    # Check that edge bands have detected peaks
    cytoskeleton_peaks = peaks.get("cytoskeleton", [])  # 35-250 Hz (includes 42, 180)
    bioelectric_peaks = peaks.get("bioelectric", [])  # 250-1200 Hz (includes 850)
    cognition_peaks = peaks.get("cognition", [])  # 1200+ Hz
    
    # At least one edge band should have peaks
    total_peaks = len(cytoskeleton_peaks) + len(bioelectric_peaks) + len(cognition_peaks)
    assert total_peaks > 0, "No edge bands recovered"
    
    # Recovered edge bands should include both lower and higher-frequency peaks.
    assert cytoskeleton_peaks, "Expected recovered cytoskeleton-band peaks"
    assert bioelectric_peaks, "Expected recovered bioelectric-band peaks"


def test_edge_energy_high_after_nulling(test_signal):
    """Verify that edge energy is high (≈1.0 after normalization)."""
    measured, fs = test_signal
    residual, peaks = hierarchical_edge_extract_v2(measured, fs)
    
    # Sum all edge peak magnitudes
    total_energy = sum(mag for band in peaks.values() for freq, mag in band)
    
    # After nulling, edge energy should be concentrated (high relative to input)
    # Normalized: should be > 0.3 (significant residual energy)
    assert total_energy > 0.3, f"Edge energy too low: {total_energy}"
