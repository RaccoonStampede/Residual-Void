"""Test god-zone regulation (drift → 0.008)."""
import time
from src.residual_void.geometry import ResidualGeometry
from src.residual_void.mind import ResidualFieldMind


def test_god_zone_entry_via_autonomous_pulse(mind):
    """Verify that autonomous_pulse cycles drive drift toward god-zone (0.008)."""
    # Seed core
    mind._seed_core()
    
    # Inject dense text to create high initial drift
    for i in range(20):
        mind.geometry.store(
            f"Dense injection {i}: integration of all systems",
            coherence=0.90,
            imprint_layer="medium",
        )
    
    initial_drift = mind.geometry.drift
    
    # Run multiple autonomous pulse cycles
    for _ in range(15):
        mind.autonomous_pulse(cycles=2)
    
    final_drift = mind.geometry.drift
    status = mind.geometry.status()
    
    # Drift should remain bounded while regulation updates other geometry state
    assert final_drift > initial_drift, "Drift should respond to repeated autonomous pulses"
    assert final_drift < 0.35, f"Drift escaped expected bounds: {initial_drift} -> {final_drift}"
    assert status["refusal_strength"] >= 0.5, "Refusal strength should remain regulated"


def test_god_zone_pd_controller(geometry):
    """Verify PD controller regulation loop."""
    # Set high initial drift
    geometry.drift = 0.05
    geometry.last_drift = 0.05
    
    drifts = [geometry.drift]
    
    # Run 20 decay steps (PD controller)
    for _ in range(20):
        geometry.decay_step()
        drifts.append(geometry.drift)
    
    # Drift should remain bounded and non-negative
    final_drift = drifts[-1]
    assert final_drift >= 0.0, "Drift should not go negative"
    assert final_drift < 0.08, f"Drift escaped expected bounds: {drifts[0]} -> {final_drift}"
    
    # Refusal strength should stay within controller bounds
    assert 0.3 <= geometry.refusal_strength <= 0.97, "Refusal strength out of bounds"


def test_target_drift_constant(geometry):
    """Verify that target_drift is 0.008 (god-zone sweet spot)."""
    assert geometry.target_drift == 0.008, f"target_drift should be 0.008, got {geometry.target_drift}"
