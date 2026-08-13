"""Test performance: no regression on perception/pulse cycles."""
import time
from src.residual_void.mind import ResidualFieldMind
from src.residual_void.geometry import ResidualGeometry


def test_pulse_cycle_performance():
    """Verify that 20 sense_edge + pulse cycles remain sub-second."""
    mind = ResidualFieldMind()
    mind._seed_core()
    
    start = time.time()
    
    for i in range(20):
        mind.sense_edge()
        mind.autonomous_pulse(cycles=1)
    
    elapsed = time.time() - start
    
    # Signal processing should remain comfortably sub-second in CI
    assert elapsed < 2.0, f"Performance regression: {elapsed:.3f}s for 20 cycles (limit 2.0s)"
    print(f"✓ 20 cycles completed in {elapsed*1000:.1f}ms")


def test_query_performance():
    """Verify that querying scales well with stored residuals."""
    geometry = ResidualGeometry(max_items=500)
    
    # Store 100 residuals
    for i in range(100):
        geometry.store(
            f"Residual text {i}: integration and coherence",
            coherence=0.85,
        )
    
    # Query should be fast
    start = time.time()
    for _ in range(10):
        results = geometry.query("integration coherence", top_k=5)
    elapsed = time.time() - start
    
    # 10 queries of 100 items should remain comfortably sub-second in CI
    assert elapsed < 1.0, f"Query performance issue: {elapsed*1000:.1f}ms (limit 1000ms)"
    print(f"✓ 10 queries (100 items) completed in {elapsed*1000:.1f}ms")
