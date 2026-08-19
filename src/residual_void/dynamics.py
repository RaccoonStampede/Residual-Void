from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Optional, Sequence, Tuple, Union


LINEAR_RESPONSE_COEFFICIENT = 0.56748
MODULAR_LYAPUNOV_EXPONENT = math.pi**2 / (6.0 * math.log(2.0))
MODULAR_WINDOW_LOW = 0.055
MODULAR_WINDOW_HIGH = 0.060

Number = Union[int, float]
VectorInput = Union[Number, Sequence[Number]]


@dataclass(frozen=True, slots=True)
class PureHarnessConfig:
    """Validated controls for the effective Pure-Harness continuum model.

    The model is separate from retrieval by default. ``enabled`` permits
    multi-pair evolution through the runtime API. Exact is never changed;
    Synthesize receives a bounded phase tie-breaker only when
    ``synthesize_phase_signal_enabled`` is explicitly enabled as well.
    """

    enabled: bool = False
    synthesize_phase_signal_enabled: bool = False
    synthesize_phase_signal_max_bonus: float = 0.06
    synthesize_phase_signal_tie_window: float = 0.06
    linear_response_coefficient: float = LINEAR_RESPONSE_COEFFICIENT
    modular_lyapunov_exponent: float = MODULAR_LYAPUNOV_EXPONENT
    modular_window_low: float = MODULAR_WINDOW_LOW
    modular_window_high: float = MODULAR_WINDOW_HIGH
    max_oscillation_amplitude: float = 0.01
    default_decay_strength: float = 1.0
    default_ghost_tax_floor: float = 0.05
    default_floor_strength: float = 0.5
    locking_variance_ratio: float = 0.01
    max_interaction_strength: float = 10.0
    max_abs_residual: float = 1_000_000.0
    max_steps: int = 100_000

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(self.synthesize_phase_signal_enabled, bool):
            raise ValueError("synthesize_phase_signal_enabled must be a boolean")
        if (
            isinstance(self.synthesize_phase_signal_max_bonus, bool)
            or not isinstance(self.synthesize_phase_signal_max_bonus, (int, float))
            or not math.isfinite(self.synthesize_phase_signal_max_bonus)
            or not 0.0 < self.synthesize_phase_signal_max_bonus <= 0.06
        ):
            raise ValueError(
                "synthesize_phase_signal_max_bonus must be within (0, 0.06]"
            )
        if (
            isinstance(self.synthesize_phase_signal_tie_window, bool)
            or not isinstance(self.synthesize_phase_signal_tie_window, (int, float))
            or not math.isfinite(self.synthesize_phase_signal_tie_window)
            or not 0.0 < self.synthesize_phase_signal_tie_window <= 0.25
        ):
            raise ValueError(
                "synthesize_phase_signal_tie_window must be within (0, 0.25]"
            )
        finite_positive = {
            "linear_response_coefficient": self.linear_response_coefficient,
            "modular_lyapunov_exponent": self.modular_lyapunov_exponent,
            "modular_window_low": self.modular_window_low,
            "modular_window_high": self.modular_window_high,
            "max_oscillation_amplitude": self.max_oscillation_amplitude,
            "default_decay_strength": self.default_decay_strength,
            "default_floor_strength": self.default_floor_strength,
            "locking_variance_ratio": self.locking_variance_ratio,
            "max_interaction_strength": self.max_interaction_strength,
            "max_abs_residual": self.max_abs_residual,
        }
        for name, value in finite_positive.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0.0
            ):
                raise ValueError(f"{name} must be a finite positive number")
        if (
            isinstance(self.default_ghost_tax_floor, bool)
            or not isinstance(self.default_ghost_tax_floor, (int, float))
            or not math.isfinite(self.default_ghost_tax_floor)
        ):
            raise ValueError("default_ghost_tax_floor must be finite")
        if self.modular_window_low >= self.modular_window_high:
            raise ValueError("modular_window_low must be less than modular_window_high")
        if self.locking_variance_ratio > 1.0:
            raise ValueError("locking_variance_ratio must be at most 1")
        if (
            isinstance(self.max_steps, bool)
            or not isinstance(self.max_steps, int)
            or self.max_steps <= 0
        ):
            raise ValueError("max_steps must be a positive integer")


@dataclass(frozen=True, slots=True)
class ResidualFlowResult:
    """JSON-safe summary of one deterministic multi-pair evolution."""

    initial_values: Tuple[float, ...]
    final_values: Tuple[float, ...]
    gamma_start: float
    gamma_end: float
    steps: int
    control_direction: float
    collective_mean: float
    pure_envelope_mean: float
    collective_floor_delta: float
    initial_variance: float
    final_variance: float
    variance_ratio: Optional[float]
    variance_ratio_status: str
    locked: bool
    modular_state: str
    in_modular_window: bool
    threshold_crossed: bool

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["initial_values"] = list(self.initial_values)
        payload["final_values"] = list(self.final_values)
        return payload


class PureHarnessDynamics:
    """Deterministic effective dynamics derived from the note's explicit laws."""

    def __init__(self, config: Optional[PureHarnessConfig] = None) -> None:
        self.config = config or PureHarnessConfig()

    def configured(self, **overrides: Any) -> "PureHarnessDynamics":
        """Return a new evaluator with validated immutable configuration."""
        return PureHarnessDynamics(replace(self.config, **overrides))

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "coupled_to_retrieval": (
                self.config.enabled
                and self.config.synthesize_phase_signal_enabled
            ),
            "law": "R0 / (1 + gamma) + beta * sin(gamma * n + phase)",
            "linear_response_coefficient": self.config.linear_response_coefficient,
            "modular_lyapunov_exponent": self.config.modular_lyapunov_exponent,
            "modular_window": [
                self.config.modular_window_low,
                self.config.modular_window_high,
            ],
            "default_ghost_tax_floor": self.config.default_ghost_tax_floor,
            "max_oscillation_amplitude": self.config.max_oscillation_amplitude,
            "synthesize_phase_signal_enabled": (
                self.config.synthesize_phase_signal_enabled
            ),
            "synthesize_phase_signal_max_bonus": (
                self.config.synthesize_phase_signal_max_bonus
            ),
            "synthesize_phase_signal_tie_window": (
                self.config.synthesize_phase_signal_tie_window
            ),
        }

    def linear_response(self, epsilon: Number) -> float:
        epsilon_value = self._finite_float(epsilon, "epsilon")
        return self.config.linear_response_coefficient * epsilon_value

    def response(
        self,
        initial_residual: Number,
        gamma: Number,
        *,
        oscillation_amplitude: Number = 0.0,
        oscillation_index: Number = 1.0,
        phase: Number = 0.0,
    ) -> float:
        """Evaluate R0/(1+gamma) plus a bounded sinusoidal correction."""
        r0 = self._finite_float(initial_residual, "initial_residual")
        gamma_value = self._nonnegative_float(gamma, "gamma")
        beta = self._bounded_amplitude(oscillation_amplitude)
        index = self._finite_float(oscillation_index, "oscillation_index")
        phase_value = self._finite_float(phase, "phase")
        value = (
            r0 / (1.0 + gamma_value)
            + beta * math.sin(gamma_value * index + phase_value)
        )
        self._ensure_state((value,))
        return value

    def diagnose(self, residuals: Sequence[Number]) -> Dict[str, Any]:
        values = self._vector(residuals, "residuals")
        magnitudes = tuple(abs(value) for value in values)
        low = self.config.modular_window_low
        high = self.config.modular_window_high
        inside = tuple(low <= value <= high for value in magnitudes)
        if all(inside):
            state = "inside"
        elif all(value < low for value in magnitudes):
            state = "below"
        elif all(value > high for value in magnitudes):
            state = "above"
        else:
            state = "mixed"
        return {
            "state": state,
            "in_modular_window": all(inside),
            "minimum_magnitude": min(magnitudes),
            "maximum_magnitude": max(magnitudes),
            "window": [low, high],
            "lyapunov_exponent": self.config.modular_lyapunov_exponent,
        }

    def evolve(
        self,
        residuals: Sequence[Number],
        *,
        gamma_start: Number = 0.0,
        gamma_end: Number = 1.0,
        step_size: Number = 0.01,
        decay_strengths: Optional[VectorInput] = None,
        interaction_matrix: Optional[Sequence[Sequence[Number]]] = None,
        oscillation_amplitudes: Optional[VectorInput] = None,
        angular_frequencies: Optional[VectorInput] = None,
        phases: Optional[VectorInput] = None,
        ghost_tax_floors: Optional[VectorInput] = None,
        floor_strength: Optional[Number] = None,
        control_direction: Number = 1.0,
        modular_threshold: Optional[Number] = None,
        threshold_gain: Number = 0.0,
    ) -> ResidualFlowResult:
        """Advance the note's effective multi-pair system with bounded RK4.

        ``control_direction=1`` applies the forward decay drive and ``-1``
        reverses that drive. Signed residuals are never clamped, preserving
        bidirectional trajectories.
        """
        if not self.config.enabled:
            raise RuntimeError("pure_harness_disabled")

        initial = self._vector(residuals, "residuals")
        count = len(initial)
        start = self._nonnegative_float(gamma_start, "gamma_start")
        end = self._nonnegative_float(gamma_end, "gamma_end")
        if end < start:
            raise ValueError("gamma_end must be greater than or equal to gamma_start")
        requested_step = self._positive_float(step_size, "step_size")
        direction = self._finite_float(control_direction, "control_direction")
        if direction < -1.0 or direction > 1.0 or direction == 0.0:
            raise ValueError("control_direction must be in [-1, 1] and non-zero")

        alpha = self._expand(
            decay_strengths,
            count,
            self.config.default_decay_strength,
            "decay_strengths",
            minimum=0.0,
        )
        beta = self._expand(
            oscillation_amplitudes,
            count,
            0.0,
            "oscillation_amplitudes",
            maximum_abs=self.config.max_oscillation_amplitude,
        )
        omega = self._expand(
            angular_frequencies,
            count,
            1.0,
            "angular_frequencies",
        )
        phase_values = self._expand(phases, count, 0.0, "phases")
        floors = self._expand(
            ghost_tax_floors,
            count,
            self.config.default_ghost_tax_floor,
            "ghost_tax_floors",
        )
        kappa = (
            self.config.default_floor_strength
            if floor_strength is None
            else self._nonnegative_float(floor_strength, "floor_strength")
        )
        interactions = self._interaction_matrix(interaction_matrix, count)
        threshold = (
            None
            if modular_threshold is None
            else self._nonnegative_float(modular_threshold, "modular_threshold")
        )
        threshold_gain_value = self._nonnegative_float(
            threshold_gain, "threshold_gain"
        )

        boundaries = [start]
        if threshold is not None and start < threshold < end:
            boundaries.append(threshold)
        boundaries.append(end)
        segments = list(zip(boundaries, boundaries[1:]))
        segment_steps = [
            0
            if segment_end == segment_start
            else math.ceil((segment_end - segment_start) / requested_step)
            for segment_start, segment_end in segments
        ]
        steps = sum(segment_steps)
        if steps > self.config.max_steps:
            raise ValueError(
                f"integration requires {steps} steps; max_steps is {self.config.max_steps}"
            )
        values = initial
        gamma_value = start

        def derivative(point: Tuple[float, ...], at_gamma: float) -> Tuple[float, ...]:
            result = []
            for i, residual in enumerate(point):
                decay = -direction * alpha[i] * residual / (1.0 + at_gamma)
                interaction = sum(
                    interactions[i][j] * residual * point[j]
                    for j in range(count)
                )
                oscillation = beta[i] * math.sin(
                    omega[i] * at_gamma + phase_values[i]
                )
                restoring = -kappa * (residual - floors[i])
                expansion = 0.0
                if threshold is not None and at_gamma > threshold:
                    expansion = (
                        threshold_gain_value
                        * (at_gamma - threshold)
                        * residual
                    )
                result.append(
                    decay + interaction + oscillation + restoring + expansion
                )
            return tuple(result)

        for (segment_start, segment_end), count_steps in zip(
            segments, segment_steps
        ):
            gamma_value = segment_start
            dt = (
                0.0
                if count_steps == 0
                else (segment_end - segment_start) / count_steps
            )
            for _ in range(count_steps):
                k1 = derivative(values, gamma_value)
                k2_point = self._add_scaled(values, k1, dt / 2.0)
                self._ensure_state(k2_point)
                k2 = derivative(k2_point, gamma_value + dt / 2.0)
                k3_point = self._add_scaled(values, k2, dt / 2.0)
                self._ensure_state(k3_point)
                k3 = derivative(k3_point, gamma_value + dt / 2.0)
                k4_point = self._add_scaled(values, k3, dt)
                self._ensure_state(k4_point)
                k4 = derivative(k4_point, gamma_value + dt)
                values = tuple(
                    value
                    + (dt / 6.0)
                    * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i])
                    for i, value in enumerate(values)
                )
                self._ensure_state(values)
                gamma_value += dt
            gamma_value = segment_end

        initial_variance = self._variance(initial)
        final_variance = self._variance(values)
        if initial_variance <= 1e-18:
            variance_ratio = 0.0 if final_variance <= 1e-18 else None
            variance_ratio_status = (
                "defined"
                if final_variance <= 1e-18
                else "indeterminate_uniform_start"
            )
        else:
            variance_ratio = final_variance / initial_variance
            variance_ratio_status = "defined"
        locked = (
            final_variance <= 1e-18
            if initial_variance <= 1e-18
            else (
                variance_ratio is not None
                and variance_ratio <= self.config.locking_variance_ratio
            )
        )
        pure_values = tuple(
            self.response(
                initial[i],
                end,
                oscillation_amplitude=beta[i],
                oscillation_index=omega[i],
                phase=phase_values[i],
            )
            for i in range(count)
        )
        collective_mean = sum(values) / count
        pure_mean = sum(pure_values) / count
        modular = self.diagnose(values)
        threshold_crossed = bool(
            threshold is not None and start <= threshold < end
        )

        return ResidualFlowResult(
            initial_values=initial,
            final_values=values,
            gamma_start=start,
            gamma_end=end,
            steps=steps,
            control_direction=direction,
            collective_mean=collective_mean,
            pure_envelope_mean=pure_mean,
            collective_floor_delta=collective_mean - pure_mean,
            initial_variance=initial_variance,
            final_variance=final_variance,
            variance_ratio=variance_ratio,
            variance_ratio_status=variance_ratio_status,
            locked=locked,
            modular_state=str(modular["state"]),
            in_modular_window=bool(modular["in_modular_window"]),
            threshold_crossed=threshold_crossed,
        )

    @staticmethod
    def _finite_float(value: Number, name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be numeric")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not math.isfinite(result):
            raise ValueError(f"{name} must be finite")
        return result

    @classmethod
    def _nonnegative_float(cls, value: Number, name: str) -> float:
        result = cls._finite_float(value, name)
        if result < 0.0:
            raise ValueError(f"{name} must be non-negative")
        return result

    @classmethod
    def _positive_float(cls, value: Number, name: str) -> float:
        result = cls._finite_float(value, name)
        if result <= 0.0:
            raise ValueError(f"{name} must be positive")
        return result

    def _bounded_amplitude(self, value: Number) -> float:
        result = self._finite_float(value, "oscillation_amplitude")
        if abs(result) > self.config.max_oscillation_amplitude:
            raise ValueError(
                "oscillation_amplitude exceeds max_oscillation_amplitude"
            )
        return result

    def _vector(self, values: Sequence[Number], name: str) -> Tuple[float, ...]:
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{name} must be a non-empty numeric sequence")
        try:
            result = tuple(self._finite_float(value, name) for value in values)
        except TypeError as exc:
            raise ValueError(f"{name} must be a non-empty numeric sequence") from exc
        if not result:
            raise ValueError(f"{name} must be a non-empty numeric sequence")
        self._ensure_state(result)
        return result

    def _expand(
        self,
        values: Optional[VectorInput],
        count: int,
        default: float,
        name: str,
        *,
        minimum: Optional[float] = None,
        maximum_abs: Optional[float] = None,
    ) -> Tuple[float, ...]:
        if values is None:
            result = (float(default),) * count
        elif isinstance(values, (int, float)) and not isinstance(values, bool):
            result = (self._finite_float(values, name),) * count
        else:
            result = self._vector(values, name)  # type: ignore[arg-type]
            if len(result) != count:
                raise ValueError(f"{name} must contain exactly {count} values")
        if minimum is not None and any(value < minimum for value in result):
            raise ValueError(f"{name} values must be at least {minimum}")
        if maximum_abs is not None and any(
            abs(value) > maximum_abs for value in result
        ):
            raise ValueError(f"{name} exceeds the configured bound")
        return result

    def _interaction_matrix(
        self,
        matrix: Optional[Sequence[Sequence[Number]]],
        count: int,
    ) -> Tuple[Tuple[float, ...], ...]:
        if matrix is None:
            return tuple((0.0,) * count for _ in range(count))
        try:
            rows = tuple(tuple(row) for row in matrix)
        except TypeError as exc:
            raise ValueError("interaction_matrix must be a square numeric matrix") from exc
        if len(rows) != count or any(len(row) != count for row in rows):
            raise ValueError(f"interaction_matrix must be {count}x{count}")
        result = tuple(
            tuple(
                self._finite_float(value, "interaction_matrix")
                for value in row
            )
            for row in rows
        )
        if any(
            abs(value) > self.config.max_interaction_strength
            for row in result
            for value in row
        ):
            raise ValueError("interaction_matrix exceeds max_interaction_strength")
        return result

    def _ensure_state(self, values: Sequence[float]) -> None:
        if any(
            not math.isfinite(value) or abs(value) > self.config.max_abs_residual
            for value in values
        ):
            raise ArithmeticError("residual_flow_out_of_bounds")

    @staticmethod
    def _add_scaled(
        values: Tuple[float, ...],
        derivative: Tuple[float, ...],
        scale: float,
    ) -> Tuple[float, ...]:
        return tuple(
            value + scale * derivative[index]
            for index, value in enumerate(values)
        )

    @staticmethod
    def _variance(values: Tuple[float, ...]) -> float:
        mean = sum(values) / len(values)
        return sum((value - mean) ** 2 for value in values) / len(values)