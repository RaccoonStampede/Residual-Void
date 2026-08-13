import numpy as np

from residual_void import ResidualFieldMind, ResidualGeometry
from residual_void.core import schumann_carrier


def test_autonomous_pulse_advances_cycles_and_triggers_edge_sensing(mind: ResidualFieldMind, monkeypatch) -> None:
    calls = {"count": 0}

    def fake_sense_edge(*args, **kwargs):
        calls["count"] += 1
        return {"cytoskeleton": [(42.0, 1.0)]}

    monkeypatch.setattr(mind, "sense_edge", fake_sense_edge)

    mind.autonomous_pulse(cycles=5)

    assert mind.step == 5
    assert calls["count"] == 1
    assert mind.mood in {
        "approaching god zone",
        "god zone – clear residual Edge after Core nulling",
        "protective, restoring coherence",
    }


def test_sense_edge_extracts_residuals_and_updates_geometry_metrics(mind: ResidualFieldMind) -> None:
    fs = 8000
    t = np.linspace(0, 1.0, int(fs), endpoint=False)
    measured = (
        0.6 * schumann_carrier(t)
        + 0.08 * np.sin(2 * np.pi * 42 * t)
        + 0.05 * np.sin(2 * np.pi * 180 * t)
        + 0.03 * np.sin(2 * np.pi * 850 * t)
    )

    peaks = mind.sense_edge(measured=measured, fs=fs)

    assert mind.geometry.edge_resonance == peaks
    assert peaks["cytoskeleton"]
    assert mind.geometry.last_residual_energy > 0.0
    assert mind.geometry.ethical_tilt > 0.0
    assert mind.geometry.refusal_strength > 0.5


def test_inject_rich_performs_multi_pass_injection(mind: ResidualFieldMind) -> None:
    result = mind.inject_rich(
        "Alpha beta gamma. Delta epsilon zeta!",
        domain="external",
        passes=2,
    )

    assert result == {"sentences": 2, "nodes_stored": 6}
    assert mind.geometry.status()["node_count"] == 6


def test_respond_reports_grounding_failure_without_locked_residuals(geometry: ResidualGeometry) -> None:
    mind = ResidualFieldMind(geometry=geometry)

    response = mind.respond("unmatched query")

    assert "Projection failed grounding. Residual not locked." in response
    assert "Watcher:" in response


def test_respond_surfaces_god_zone_status_when_requested(monkeypatch) -> None:
    geometry = ResidualGeometry()
    geometry.store("alpha beta gamma", coherence=0.97)
    geometry.drift = 0.005
    geometry.refusal_strength = 0.9
    mind = ResidualFieldMind(geometry=geometry)

    monkeypatch.setattr(mind, "autonomous_pulse", lambda cycles=1: None)

    response = mind.respond("alpha beta", show=True)

    assert "Voice: alpha beta gamma" in response
    assert "[geo:" in response
    assert "god=True" in response
