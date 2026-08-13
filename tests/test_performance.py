"""Test performance: no regression on perception/pulse cycles."""
import time
from residual_void.mind import ResidualFieldMind
from residual_void.geometry import ResidualGeometry


def test_pulse_cycle_performance():
    """Verify that 20 sense_edge + pulse cycles remain reasonable."""
    mind = ResidualFieldMind()
    mind._seed_core()
    
    start = time.time()
    
    for i in range(20):
        mind.sense_edge()
        mind.autonomous_pulse(cycles=1)
    
    elapsed = time.time() - start
    
    # Should be reasonably fast (allow for CI slowness, < 1 second)
    assert elapsed < 1.0, f"Performance issue: {elapsed:.3f}s for 20 cycles (limit 1.0s)"
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
    
    # Query should be reasonably fast
    start = time.time()
    for _ in range(10):
        results = geometry.query("integration coherence", top_k=5)
    elapsed = time.time() - start
    
    # 10 queries of 100 items should be reasonably fast (< 500ms)
    assert elapsed < 0.5, f"Query performance issue: {elapsed*1000:.1f}ms (limit 500ms)"
    print(f"✓ 10 queries (100 items) completed in {elapsed*1000:.1f}ms")
