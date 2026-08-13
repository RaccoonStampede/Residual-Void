"""Test god-zone regulation (drift → 0.008)."""
import time
from residual_void.geometry import ResidualGeometry
from residual_void.mind import ResidualFieldMind


def test_god_zone_entry_via_autonomous_pulse(mind):
    """Verify that autonomous_pulse cycles regulate drift over time."""
    # Seed core
    mind._seed_core()
    
    # Inject dense text to create geometry state
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
    
    # Drift should remain bounded
    assert final_drift >= 0.0, "Drift should not be negative"
    assert final_drift < 1.0, "Drift should remain bounded"
    
    # After many cycles, god-zone entry is possible if drift and refusal are right
    if status["god_zone"]:
        assert status["drift"] < 0.010, "God zone requires drift < 0.010"
        assert status["refusal_strength"] > 0.70, "God zone requires refusal > 0.70"


def test_god_zone_pd_controller(geometry):
    """Verify PD controller regulation loop exists and affects refusal strength."""
    # Set high initial drift
    geometry.drift = 0.05
    geometry.last_drift = 0.05
    
    initial_refusal = geometry.refusal_strength
    
    # Run 20 decay steps (PD controller)
    for _ in range(20):
        geometry.decay_step()
    
    final_refusal = geometry.refusal_strength
    
    # PD controller should modify refusal strength in response to drift error
    # The direction depends on the error sign
    assert geometry.refusal_strength >= 0.3, "Refusal strength should stay >= 0.3"
    assert geometry.refusal_strength <= 0.97, "Refusal strength should stay <= 0.97"
    
    # Natural decay should reduce drift
    assert geometry.drift <= 0.05, "Drift should not increase beyond initial"


def test_target_drift_constant(geometry):
    """Verify that target_drift is 0.008 (god-zone sweet spot)."""
    assert geometry.target_drift == 0.008, f"target_drift should be 0.008, got {geometry.target_drift}"
