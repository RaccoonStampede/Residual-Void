from __future__ import annotations

from dataclasses import dataclass

from residual_void import ResidualVoid


@dataclass(frozen=True)
class SynthesizeCase:
    name: str
    query: str
    required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    expects_empty: bool = False


CORE_CASES = (
    SynthesizeCase(
        "ghost_tax_definition",
        "What is Ghost Tax?",
        required=("ghost tax",),
        forbidden=("boat",),
    ),
    SynthesizeCase(
        "boat_definition",
        "What is the boat?",
        required=("boat",),
        forbidden=("ghost tax",),
    ),
    SynthesizeCase(
        "ordered_steps",
        "What are the steps to use the void?",
        required=("step 1", "step 2", "step 3"),
    ),
    SynthesizeCase(
        "phase_lock_definition",
        "What is phase lock?",
        required=("phase lock",),
        forbidden=("inventory marker",),
    ),
    SynthesizeCase(
        "wrong_carrier_how_refuses",
        "How does the boat achieve phase lock?",
        expects_empty=True,
    ),
    SynthesizeCase(
        "off_target_refuses",
        "What is the orbital lunch policy?",
        expects_empty=True,
    ),
)


def _core_runtime() -> ResidualVoid:
    runtime = ResidualVoid()
    runtime.inject(
        "Ghost Tax is the five-percent coherence leak at an interface. "
        "Phase lock aligns a carrier to its reference without drift.",
        domain="Science",
        title="SCIENCE",
        identity="A",
        scale=2.5,
        density=1.4,
        intent="what",
    )
    runtime.inject(
        "The boat is a cedar skiff remembered from a quiet summer crossing.",
        domain="Memoir",
        title="MEMOIR",
        identity="B",
        scale=1.0,
        density=0.9,
        intent="what",
    )
    runtime.inject(
        "Step 1: Open the void. Step 2: Lock the complete source. "
        "Step 3: Query the structured shadows.",
        domain="Ops",
        title="OPS",
        identity="C",
        scale=1.8,
        density=1.1,
        intent="steps",
    )
    for index in range(40):
        runtime.lock(
            f"NOISE::LOCK_{index}_FACT::"
            f"Lock record {index} is an unrelated lightweight inventory marker.",
            domain="Noise",
            identity=f"noise-{index}",
            scale=0.2,
            density=0.2,
            intent="fact",
        )
    return runtime


def _same_topic_runtime() -> ResidualVoid:
    runtime = ResidualVoid()
    for identity, text in (
        (
            "carrier",
            "SCI::PHASE_CARRIER_FACT::"
            "Phase lock aligns a carrier to its stable reference without drift.",
        ),
        (
            "oscillator",
            "SCI::PHASE_OSCILLATOR_FACT::"
            "Phase lock keeps two oscillators synchronized across a shared carrier.",
        ),
        (
            "measurement",
            "SCI::PHASE_MEASUREMENT_FACT::"
            "Phase locking is observed when the phase difference remains stable across cycles.",
        ),
        (
            "inventory",
            "SCI::PHASE_INVENTORY_FACT::"
            "Phase lock is a temporary label used in an inventory record.",
        ),
    ):
        assert runtime.lock(
            text,
            identity=identity,
            scale=1.0,
            density=1.0,
            intent="what",
        ) == "locked"
    return runtime


def _answer(runtime: ResidualVoid, case: SynthesizeCase) -> tuple[bool, tuple[str, ...]]:
    payloads = tuple(
        item["payload"]
        for item in runtime.project(case.query, mode="synthesize")["results"]
    )
    text = " ".join(payloads).casefold()
    correct = (
        not payloads
        if case.expects_empty
        else bool(payloads)
        and all(term.casefold() in text for term in case.required)
        and all(term.casefold() not in text for term in case.forbidden)
    )
    return correct, payloads


def _run_core(phase_signal: bool) -> tuple[int, dict[str, tuple[str, ...]]]:
    results: dict[str, tuple[str, ...]] = {}
    correct = 0
    for case in CORE_CASES:
        runtime = _core_runtime()
        if phase_signal:
            runtime.configure_pure_harness(
                enabled=True,
                synthesize_phase_signal_enabled=True,
            )
        passed, payloads = _answer(runtime, case)
        correct += int(passed)
        results[case.name] = payloads
    return correct, results


def test_bounded_phase_signal_matches_baseline_on_labeled_core_corpus() -> None:
    baseline_score, baseline_answers = _run_core(phase_signal=False)
    phase_score, phase_answers = _run_core(phase_signal=True)

    assert baseline_score == len(CORE_CASES)
    assert phase_score == baseline_score
    assert phase_answers == baseline_answers


def test_same_topic_phase_case_remains_grounded_with_signal_enabled() -> None:
    case = SynthesizeCase(
        "carrier_mechanism",
        "How does phase lock align a carrier?",
        required=("aligns a carrier",),
        forbidden=("inventory record",),
    )
    baseline_ok, baseline_payloads = _answer(_same_topic_runtime(), case)
    phased = _same_topic_runtime()
    phased.configure_pure_harness(
        enabled=True,
        synthesize_phase_signal_enabled=True,
    )
    phase_ok, phase_payloads = _answer(phased, case)

    assert baseline_ok is True
    assert phase_ok is True
    assert phase_payloads == baseline_payloads