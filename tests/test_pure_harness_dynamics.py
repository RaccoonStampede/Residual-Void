from __future__ import annotations

import math
import json

import pytest

from residual_void import (
    LINEAR_RESPONSE_COEFFICIENT,
    MODULAR_LYAPUNOV_EXPONENT,
    MODULAR_WINDOW_HIGH,
    MODULAR_WINDOW_LOW,
    PureHarnessConfig,
    PureHarnessDynamics,
    ResidualVoid,
)


def _enabled_dynamics(**overrides) -> PureHarnessDynamics:
    return PureHarnessDynamics(
        PureHarnessConfig(enabled=True, **overrides)
    )


def test_scalar_law_and_named_constants_match_the_note() -> None:
    dynamics = PureHarnessDynamics()
    expected = 0.06161 / 3.0 + 0.00018 * math.sin(2.0 * 0.5 + 0.2)

    assert dynamics.response(
        0.06161,
        2.0,
        oscillation_amplitude=0.00018,
        oscillation_index=0.5,
        phase=0.2,
    ) == pytest.approx(expected)
    assert dynamics.linear_response(0.25) == pytest.approx(
        LINEAR_RESPONSE_COEFFICIENT * 0.25
    )
    assert MODULAR_LYAPUNOV_EXPONENT == pytest.approx(
        math.pi**2 / (6.0 * math.log(2.0))
    )
    with pytest.raises(ValueError, match="exceeds"):
        dynamics.response(
            0.1,
            1.0,
            oscillation_amplitude=0.02,
        )


def test_modular_window_boundaries_are_inclusive_and_mixed_is_visible() -> None:
    dynamics = PureHarnessDynamics()

    inside = dynamics.diagnose([MODULAR_WINDOW_LOW, -MODULAR_WINDOW_HIGH])
    mixed = dynamics.diagnose([MODULAR_WINDOW_LOW - 0.001, MODULAR_WINDOW_HIGH])

    assert inside["state"] == "inside"
    assert inside["in_modular_window"] is True
    assert mixed["state"] == "mixed"
    assert mixed["in_modular_window"] is False


def test_multi_pair_flow_locks_toward_soft_ghost_tax_floor() -> None:
    dynamics = _enabled_dynamics(
        default_decay_strength=0.01,
        default_floor_strength=3.0,
    )

    result = dynamics.evolve(
        [0.2, 0.08, -0.04],
        gamma_end=3.0,
        step_size=0.01,
        ghost_tax_floors=0.05,
    )

    assert result.locked is True
    assert result.variance_ratio < 0.01
    assert result.collective_mean == pytest.approx(0.05, abs=0.002)
    assert result.collective_floor_delta > 0.0


def test_positive_pair_interaction_elevates_collective_floor() -> None:
    dynamics = _enabled_dynamics(
        default_decay_strength=0.05,
        default_floor_strength=2.0,
    )
    controls = {
        "gamma_end": 3.0,
        "step_size": 0.01,
        "ghost_tax_floors": [0.05, 0.05],
    }

    uncoupled = dynamics.evolve([0.12, 0.08], **controls)
    coupled = dynamics.evolve(
        [0.12, 0.08],
        interaction_matrix=[[0.0, 1.5], [1.5, 0.0]],
        **controls,
    )

    assert coupled.collective_mean > uncoupled.collective_mean


def test_reverse_control_recovers_amplitude_and_is_repeatable() -> None:
    dynamics = _enabled_dynamics(default_floor_strength=0.5)
    controls = {
        "gamma_end": 1.5,
        "step_size": 0.005,
        "floor_strength": 0.0,
        "ghost_tax_floors": 0.05,
    }

    forward = dynamics.evolve([0.06, 0.04], control_direction=1.0, **controls)
    reverse_one = dynamics.evolve(
        [0.06, 0.04],
        control_direction=-1.0,
        **controls,
    )
    reverse_two = dynamics.evolve(
        [0.06, 0.04],
        control_direction=-1.0,
        **controls,
    )

    assert reverse_one.collective_mean > 0.05
    assert reverse_one.collective_mean > forward.collective_mean
    assert reverse_one == reverse_two


def test_modular_threshold_reports_crossing_and_upturn() -> None:
    dynamics = _enabled_dynamics(default_decay_strength=0.2)
    controls = {
        "gamma_end": 1.0,
        "step_size": 0.005,
        "floor_strength": 0.0,
        "modular_threshold": 0.4,
    }

    baseline = dynamics.evolve([0.06, 0.058], threshold_gain=0.0, **controls)
    expanding = dynamics.evolve([0.06, 0.058], threshold_gain=3.0, **controls)

    assert expanding.threshold_crossed is True
    assert expanding.collective_mean > baseline.collective_mean


def test_threshold_partition_is_stable_across_step_alignment() -> None:
    dynamics = _enabled_dynamics(default_decay_strength=0.2)
    controls = {
        "gamma_end": 1.0,
        "floor_strength": 0.0,
        "modular_threshold": 0.43,
        "threshold_gain": 1.5,
    }

    aligned = dynamics.evolve([0.06, 0.058], step_size=0.05, **controls)
    unaligned = dynamics.evolve([0.06, 0.058], step_size=0.037, **controls)

    assert unaligned.final_values == pytest.approx(
        aligned.final_values,
        rel=1e-6,
        abs=1e-9,
    )


def test_diagnostics_are_strict_json_safe_for_uniform_start() -> None:
    dynamics = _enabled_dynamics()

    result = dynamics.evolve(
        [0.05, 0.05],
        gamma_end=0.5,
        ghost_tax_floors=[0.04, 0.06],
    ).as_dict()

    assert result["variance_ratio"] is None
    assert result["variance_ratio_status"] == "indeterminate_uniform_start"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"enabled": "false"}, "enabled must be a boolean"),
        ({"max_steps": True}, "max_steps must be a positive integer"),
        (
            {"synthesize_phase_signal_max_bonus": 0.061},
            r"synthesize_phase_signal_max_bonus must be within \(0, 0.06\]",
        ),
        (
            {"synthesize_phase_signal_tie_window": 0.251},
            r"synthesize_phase_signal_tie_window must be within \(0, 0.25\]",
        ),
        (
            {"default_decay_strength": True},
            "default_decay_strength must be a finite positive number",
        ),
    ],
)
def test_configuration_rejects_boolean_coercion(config, message) -> None:
    with pytest.raises(ValueError, match=message):
        PureHarnessConfig(**config)


def test_runtime_layer_is_opt_in_inspectable_and_retrieval_neutral() -> None:
    runtime = ResidualVoid()
    assert runtime.lock(
        "SCI::PHASE_LOCK_DEFINITION::Phase lock aligns a carrier to its reference."
    ) == "locked"
    exact_before = runtime.project("What is phase lock?", mode="exact")
    synthesize_before = runtime.project("What is phase lock?", mode="synthesize")

    status = runtime.status()["void"]["pure_harness"]
    assert status["enabled"] is False
    assert status["coupled_to_retrieval"] is False
    assert "R0 / (1 + gamma)" in status["law"]
    with pytest.raises(RuntimeError, match="pure_harness_disabled"):
        runtime.evolve_residual_pairs([0.06, 0.05])
    with pytest.raises(ValueError, match="enabled must be a boolean"):
        runtime.configure_pure_harness(enabled="false")

    configured = runtime.configure_pure_harness(enabled=True)
    flow = runtime.evolve_residual_pairs(
        [0.06, 0.05],
        gamma_end=0.1,
        step_size=0.01,
    )
    exact_after = runtime.project("What is phase lock?", mode="exact")
    synthesize_after = runtime.project("What is phase lock?", mode="synthesize")

    assert configured["enabled"] is True
    assert configured["coupled_to_retrieval"] is False
    assert len(flow["final_values"]) == 2
    assert exact_before["results"][0]["payload"] == exact_after["results"][0]["payload"]
    assert (
        synthesize_before["results"][0]["payload"]
        == synthesize_after["results"][0]["payload"]
    )


def test_phase_signal_is_explicit_and_bounded_after_carrier_alignment() -> None:
    runtime = ResidualVoid()
    assert runtime.lock(
        "SCI::PHASE_LOCK_FACT::Phase lock aligns a carrier to its reference."
    ) == "locked"
    assert runtime.lock(
        "SCI::PHASE_LOCK_ALT_FACT::Phase lock can preserve stable timing."
    ) == "locked"
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
        synthesize_phase_signal_max_bonus=0.06,
    )
    candidates = [
        (residual, 0.5)
        for residual in runtime.void.field.residuals
        if residual.layer == "shadow"
    ]
    runtime.void._vibrate_residuals(candidates)
    adjustments = runtime.void._pure_harness_phase_adjustments(candidates)

    assert runtime.status()["void"]["pure_harness"]["coupled_to_retrieval"] is True
    assert adjustments
    assert all(abs(value) <= 0.06 for value in adjustments.values())
    assert sum(adjustments.values()) == pytest.approx(0.0)


def test_phase_signal_changes_live_eligible_tie_without_bypassing_gates() -> None:
    runtime = ResidualVoid()
    field = runtime.void.field
    assert field.store(
        "SCI::PHASE_A_FACT::"
        "Phase signal guides the alpha carrier through a stable orbit.",
        layer="legacy",
        source_id="alpha",
        seed_identity="shared",
        seed_intent="what",
    )[0]
    assert field.store(
        "SCI::PHASE_B_FACT::"
        "Phase signal guides the beta carrier through a stable orbit.",
        layer="legacy",
        source_id="beta",
        seed_identity="shared",
        seed_intent="what",
    )[0]
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
    )

    def controlled_carrier(candidates, query_ref=1.0):
        for residual, _ in candidates:
            residual.ensure_core().phase = (
                query_ref if "beta carrier" in residual.fragment else -query_ref
            )
        return {residual.residual_id: 0.0 for residual, _ in candidates}, set()

    runtime.void._vibrate_residuals = controlled_carrier  # type: ignore[method-assign]
    answer = runtime.project("phase signal", mode="synthesize")

    assert answer["results"][0]["payload"].startswith(
        "Phase signal guides the beta carrier"
    )
    # The post-gate signal still cannot make an unrelated residual answer.
    assert runtime.project(
        "What is the orbital lunch policy?",
        mode="synthesize",
    )["results"] == []


def test_phase_signal_cannot_promote_a_below_threshold_candidate() -> None:
    runtime = ResidualVoid()
    assert runtime.lock(
        "SCI::PHASE_SIGNAL_FACT::"
        "Phase signal guides a carrier through a stable orbit."
    ) == "locked"
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
    )
    shadow = next(
        residual
        for residual in runtime.void.field.residuals
        if residual.layer == "shadow"
    )
    near_threshold = [(shadow, 0.47)]

    adjusted = runtime.void._apply_pure_harness_phase_signal(
        near_threshold,
        {"phase", "signal"},
        "phase signal",
    )

    assert runtime.void._passes_synthesize_primary_admission(
        shadow,
        0.47,
        {"phase", "signal"},
        "phase signal",
    ) is False
    assert adjusted == near_threshold


def test_phase_signal_only_runs_for_a_close_admitted_tie() -> None:
    runtime = ResidualVoid()
    assert runtime.lock(
        "SCI::PHASE_SIGNAL_FACT::"
        "Phase signal guides a carrier through a stable orbit."
    ) == "locked"
    assert runtime.lock(
        "SCI::PHASE_SIGNAL_ALT_FACT::"
        "Phase signal stabilizes a carrier against phase drift."
    ) == "locked"
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
        synthesize_phase_signal_tie_window=0.06,
    )
    residuals = [
        residual
        for residual in runtime.void.field.residuals
        if residual.layer == "shadow"
    ]
    residuals[0].ensure_core().phase = 1.0
    residuals[1].ensure_core().phase = -1.0
    qset = {"phase", "signal"}

    far_apart = runtime.void._apply_pure_harness_phase_signal(
        [(residuals[0], 0.60), (residuals[1], 0.50)],
        qset,
        "phase signal",
    )
    close_tie = runtime.void._apply_pure_harness_phase_signal(
        [(residuals[0], 0.60), (residuals[1], 0.56)],
        qset,
        "phase signal",
    )

    assert far_apart == [(residuals[0], 0.60), (residuals[1], 0.50)]
    assert close_tie != [(residuals[0], 0.60), (residuals[1], 0.56)]


def test_phase_tie_pool_uses_post_score_ranking_not_candidate_order() -> None:
    runtime = ResidualVoid()
    for index in range(4):
        assert runtime.lock(
            f"SCI::PHASE_SIGNAL_{index}_FACT::"
            f"Phase signal candidate {index} guides a carrier through a stable orbit."
        ) == "locked"
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
        synthesize_phase_signal_tie_window=0.06,
    )
    low_one, low_two, high_one, high_two = [
        residual
        for residual in runtime.void.field.residuals
        if residual.layer == "shadow"
    ]
    high_one.ensure_core().phase = 1.0
    high_two.ensure_core().phase = -1.0
    qset = {"phase", "signal"}

    # Candidate order puts a lower-ranked close pair first, but the actual
    # top-scoring pair is also close and must be the only tie pool.
    adjusted = runtime.void._apply_pure_harness_phase_signal(
        [
            (low_one, 0.60),
            (low_two, 0.59),
            (high_one, 0.90),
            (high_two, 0.88),
        ],
        qset,
        "phase signal",
    )
    scores = {residual.residual_id: score for residual, score in adjusted}

    assert scores[low_one.residual_id] == 0.60
    assert scores[low_two.residual_id] == 0.59
    assert scores[high_one.residual_id] > 0.90
    assert scores[high_two.residual_id] < 0.88


def test_phase_signal_cannot_demote_an_admitted_candidate_into_refusal() -> None:
    runtime = ResidualVoid()
    assert runtime.lock(
        "SCI::PHASE_ALPHA_FACT::"
        "Phase signal guides the alpha carrier through a stable orbit."
    ) == "locked"
    assert runtime.lock(
        "SCI::PHASE_BETA_FACT::"
        "Phase signal guides the beta carrier through a stable orbit."
    ) == "locked"
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
        synthesize_phase_signal_tie_window=0.25,
    )
    alpha, beta = [
        residual
        for residual in runtime.void.field.residuals
        if residual.layer == "shadow"
    ]
    alpha.ensure_core().phase = -1.0
    beta.ensure_core().phase = 1.0
    qset = {"phase", "signal"}
    adjusted = runtime.void._apply_pure_harness_phase_signal(
        [(alpha, 0.49), (beta, 0.60)],
        qset,
        "phase signal",
    )

    assert adjusted[0][1] == pytest.approx(0.48)
    assert runtime.void._passes_synthesize_primary_admission(
        adjusted[0][0],
        adjusted[0][1],
        qset,
        "phase signal",
    ) is True


def test_phase_signal_keeps_duplicate_fragments_isolated_by_residual_id() -> None:
    runtime = ResidualVoid()
    field = runtime.void.field
    duplicate_payload = (
        "SCI::PHASE_DUP_FACT::"
        "Phase signal guides a carrier through a stable orbit."
    )
    for identity in ("alpha", "beta"):
        assert field.store(
            duplicate_payload,
            layer="legacy",
            source_id=identity,
            seed_identity=identity,
            seed_intent="what",
        )[0]
    assert field.store(
        "SCI::PHASE_ANCHOR_FACT::"
        "Phase signal stabilizes a carrier against phase drift.",
        layer="legacy",
        source_id="anchor",
        seed_identity="anchor",
        seed_intent="what",
    )[0]
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
        synthesize_phase_signal_tie_window=0.25,
    )
    alpha, beta, anchor = runtime.void.field.residuals
    alpha.ensure_core().phase = 1.0
    beta.ensure_core().phase = -1.0
    anchor.ensure_core().phase = -1.0
    qset = {"phase", "signal"}
    ordered = [(alpha, 0.50), (beta, 0.47), (anchor, 0.60)]
    adjustments = runtime.void._pure_harness_phase_adjustments(
        [(alpha, 0.50), (anchor, 0.60)]
    )
    adjusted = runtime.void._apply_pure_harness_phase_signal(
        ordered,
        qset,
        "phase signal",
    )
    scores = {residual.residual_id: score for residual, score in adjusted}

    assert set(adjustments) == {alpha.residual_id, anchor.residual_id}
    assert beta.residual_id not in adjustments
    assert scores[alpha.residual_id] > 0.50
    assert scores[beta.residual_id] == 0.47
    assert 0.48 <= scores[anchor.residual_id] < 0.60


def test_carrier_boosts_keep_duplicate_fragments_isolated_by_residual_id() -> None:
    runtime = ResidualVoid()
    field = runtime.void.field
    payload = (
        "SCI::PHASE_DUP_FACT::"
        "Phase signal guides a carrier through a stable orbit."
    )
    for identity in ("alpha", "beta"):
        assert field.store(
            payload,
            layer="legacy",
            source_id=identity,
            seed_identity=identity,
            seed_intent="what",
        )[0]
    alpha, beta = runtime.void.field.residuals
    alpha.ensure_core().phase = 1.0
    beta.ensure_core().phase = -1.0

    boosts, in_phase = runtime.void._vibrate_residuals(
        [(alpha, 0.50), (beta, -0.50)]
    )

    assert set(boosts) == {alpha.residual_id, beta.residual_id}
    assert alpha.residual_id in in_phase
    assert beta.residual_id not in in_phase


def test_live_synthesize_keeps_duplicate_phase_candidates_distinct() -> None:
    runtime = ResidualVoid()
    field = runtime.void.field
    payload = (
        "SCI::PHASE_DUP_FACT::"
        "Phase signal guides a carrier through a stable orbit."
    )
    for identity in ("alpha", "beta"):
        assert field.store(
            payload,
            layer="legacy",
            source_id=identity,
            seed_identity="shared",
            seed_intent="what",
        )[0]
    alpha, beta = runtime.void.field.residuals
    # Isolate the phase tie-break: family governance would otherwise make only
    # the later duplicate active, so these records would not be a score tie.
    alpha.active = True
    beta.active = True
    runtime.void.boost_enabled = False
    runtime.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
        synthesize_phase_signal_tie_window=0.25,
    )
    observed: dict[str, set[str]] = {}
    original_phase_adjustments = runtime.void._pure_harness_phase_adjustments

    def controlled_carrier(candidates, query_ref=1.0):
        for residual, _ in candidates:
            residual.ensure_core().phase = (
                query_ref if residual.residual_id == alpha.residual_id else -query_ref
            )
        observed["carrier_ids"] = {residual.residual_id for residual, _ in candidates}
        return (
            {residual.residual_id: 0.0 for residual, _ in candidates},
            {alpha.residual_id},
        )

    def observe_phase_adjustments(candidates, query_ref=1.0):
        observed["phase_ids"] = {residual.residual_id for residual, _ in candidates}
        return original_phase_adjustments(candidates, query_ref)

    runtime.void._vibrate_residuals = controlled_carrier  # type: ignore[method-assign]
    runtime.void._pure_harness_phase_adjustments = observe_phase_adjustments  # type: ignore[method-assign]
    answer = runtime.project("phase signal", mode="synthesize")

    assert answer["results"]
    assert {alpha.residual_id, beta.residual_id} <= observed["carrier_ids"]
    assert {alpha.residual_id, beta.residual_id} <= observed["phase_ids"]