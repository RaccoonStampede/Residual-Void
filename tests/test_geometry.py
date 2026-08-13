import pytest

from residual_void import ResidualGeometry


def test_store_uses_fibonacci_shells_and_force_promotes_coherence(geometry: ResidualGeometry) -> None:
    rid_one = geometry.store("alpha beta gamma", coherence=0.84)
    rid_two = geometry.store("delta epsilon zeta", coherence=0.86, force_promote=True)
    rid_three = geometry.store("eta theta iota", coherence=0.96)

    assert geometry._data[rid_one]["shell"] == geometry._fibonacci_place(1)
    assert geometry._data[rid_two]["shell"] == geometry._fibonacci_place(2)
    assert geometry._data[rid_two]["coherence"] == pytest.approx(0.98)
    assert geometry._data[rid_three]["protect"] is True


def test_drift_regulation_tracks_ghost_tax_and_god_zone(geometry: ResidualGeometry) -> None:
    geometry.refusal_strength = 0.8
    geometry.drift = 0.004

    geometry.decay_step()
    status = geometry.status()

    assert geometry.drift == pytest.approx(0.0035)
    assert status["god_zone"] is True
    assert status["ghost_tax"] == pytest.approx(0.126, rel=1e-3)

    previous_drift = geometry.drift
    geometry.ethical_tilt = 0.2
    geometry.pulse(0.009)

    assert geometry.drift > previous_drift
    assert geometry.refusal_strength > 0.8


def test_prune_preserves_protected_residuals(geometry: ResidualGeometry) -> None:
    protected = geometry.store("protected core residual", coherence=0.97)
    removable_one = geometry.store("first temporary residual", coherence=0.30)
    removable_two = geometry.store("second temporary residual", coherence=0.20)

    removed = geometry.prune(max_items=1)

    assert removed == 2
    assert protected in geometry._data
    assert removable_two not in geometry._data
    assert removable_one not in geometry._data


def test_query_prefers_more_coherent_matching_nodes_and_updates_touch_count(geometry: ResidualGeometry) -> None:
    low = geometry.store("alpha beta gamma", coherence=0.70)
    high = geometry.store("alpha beta gamma", coherence=0.95)
    geometry.store("omega sigma tau", coherence=0.99)

    ranked = geometry.query("alpha beta", top_k=2)

    assert ranked[0][0] == high
    assert ranked[1][0] == low
    assert geometry._data[high]["touch_count"] == 2
    assert geometry._data[low]["touch_count"] == 2
