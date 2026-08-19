from __future__ import annotations

import pytest

import residual_void.core as core
from residual_void import ResidualVoid
from residual_void.core import classify_intent_cell


def _payloads(result: dict) -> list[str]:
    return [item["payload"] for item in result["results"]]


@pytest.mark.parametrize(
    ("query", "primary", "branches"),
    [
        ("Why does Ghost Tax exist?", "why", {"why", "mechanism"}),
        ("When can the field reach zero floor?", "when", {"when", "condition"}),
        ("How does Ghost Tax prevent sterile lock?", "how", {"how", "mechanism"}),
        ("Who built the carrier lattice?", "who", {"who", "entity"}),
        ("What is a HyperSeed?", "definition", {"definition", "what"}),
        ("Why did the carrier lattice fail?", "diagnose", {"diagnose", "why"}),
        ("Explain the mechanism of phase lock", "mechanism", {"mechanism", "how"}),
        ("Report the carrier state", "general", {"general", "fact"}),
    ],
)
def test_intent_cell_classification_exposes_compatible_branches(
    query: str,
    primary: str,
    branches: set[str],
) -> None:
    cell = classify_intent_cell(query)

    assert cell.primary == primary
    assert branches.issubset(set(cell.branch_keys))


@pytest.mark.parametrize(
    ("source", "query", "expected_body"),
    [
        (
            "SCI::GHOST_TAX_WHY::"
            "Ghost tax exists because perfect coherence would freeze the field "
            "into a sterile lock, so a five-percent leak preserves motion while "
            "preventing total phase arrest.",
            "Why does Ghost Tax exist?",
            "Ghost tax exists because perfect coherence would freeze the field "
            "into a sterile lock, so a five-percent leak preserves motion while "
            "preventing total phase arrest.",
        ),
        (
            "SCI::GHOST_TAX_MECHANISM::"
            "Ghost tax prevents sterile lock by leaking five percent of coherence "
            "at every interface, preserving enough phase motion for the field to adapt.",
            "How does Ghost Tax prevent sterile lock?",
            "Ghost tax prevents sterile lock by leaking five percent of coherence "
            "at every interface, preserving enough phase motion for the field to adapt.",
        ),
        (
            "SCI::ZERO_FLOOR_WHEN::"
            "The field can reach zero floor only when every carrier loses restorative "
            "coupling and no coherent residual remains to reseed motion.",
            "When can the field reach zero floor?",
            "The field can reach zero floor only when every carrier loses restorative "
            "coupling and no coherent residual remains to reseed motion.",
        ),
        (
            "SCI::HYPERSEED_DEFINITION::"
            "A HyperSeed is the immutable source record plus its grounded extractive "
            "Shadows, all carrying the same seed identity and ownership metadata.",
            "What is a HyperSeed?",
            "A HyperSeed is the immutable source record plus its grounded extractive "
            "Shadows, all carrying the same seed identity and ownership metadata.",
        ),
        (
            "OPS::CARRIER_LATTICE_WHO::"
            "Mara Venn built the carrier lattice after the prototype field exposed "
            "a deterministic phase gap.",
            "Who built the carrier lattice?",
            "Mara Venn built the carrier lattice after the prototype field exposed "
            "a deterministic phase gap.",
        ),
        (
            "OPS::CARRIER_LATTICE_WHAT::"
            "The carrier lattice stores complete locked sources while retrieval "
            "scores only their grounded extractive Shadows.",
            "What does the carrier lattice store?",
            "The carrier lattice stores complete locked sources while retrieval "
            "scores only their grounded extractive Shadows.",
        ),
        (
            "OPS::CARRIER_LATTICE_WHY::"
            "The carrier lattice failed because its reference phase disappeared "
            "before the final residual could restore coupling.",
            "Why did the carrier lattice fail?",
            "The carrier lattice failed because its reference phase disappeared "
            "before the final residual could restore coupling.",
        ),
    ],
)
def test_single_answer_intents_return_complete_grounded_shadow_cells(
    source: str,
    query: str,
    expected_body: str,
) -> None:
    void = ResidualVoid(secret="intent-cell-complete-secret-123456")
    assert void.lock(source, identity="intent-seed") == "locked"

    synthesize = _payloads(void.project(query, mode="synthesize"))
    exact = _payloads(void.project(expected_body, mode="exact"))

    assert synthesize == [expected_body]
    assert synthesize[0].endswith((".", "!", "?"))
    assert exact == [source]
    layers = void.status()["void"]["layers"]
    assert layers["source"] == 1
    assert layers["shadow"] == 1


def test_intent_cell_adds_no_more_than_two_complete_compatible_supports() -> None:
    primary = (
        "Ghost tax exists because a perfectly frozen phase would stop adaptation."
    )
    support_one = (
        "Ghost tax preserves motion by leaking five percent of coherence at interfaces."
    )
    support_two = (
        "Ghost tax also leaves enough residual variation for a new carrier to entrain."
    )
    extra = (
        "Ghost tax remains bounded so the field does not lose all usable coherence."
    )
    source = " ".join((primary, support_one, support_two, extra))
    void = ResidualVoid(secret="intent-cell-support-secret-123456")
    assert void.lock(
        source,
        identity="ghost-tax-seed",
        shadow_texts=[
            f"SCI::GHOST_TAX_WHY::{primary}",
            f"SCI::GHOST_TAX_WHY_SUPPORT::{support_one}",
            f"SCI::GHOST_TAX_WHY_SECONDARY::{support_two}",
            f"SCI::GHOST_TAX_WHY_EXTRA::{extra}",
        ],
    ) == "locked"

    answer = _payloads(void.project("Why does Ghost Tax exist?", mode="synthesize"))[0]

    included = [sentence for sentence in (primary, support_one, support_two, extra) if sentence in answer]
    assert 1 <= len(included) <= 3
    assert answer == " ".join(included)
    assert "Related:" not in answer
    assert " | " not in answer
    assert answer.endswith(".")


def test_intent_cell_does_not_append_incompatible_definition_or_weak_overlap() -> None:
    void = ResidualVoid(secret="intent-cell-branch-secret-123456")
    why_body = (
        "Ghost tax exists because a perfectly frozen phase would stop adaptation."
    )
    definition_body = (
        "Ghost tax is the five-percent coherence leak retained at every interface."
    )
    assert void.lock(
        f"SCI::GHOST_TAX_WHY::{why_body}",
        identity="why-seed",
    ) == "locked"
    assert void.lock(
        f"SCI::GHOST_TAX_DEFINITION::{definition_body}",
        identity="definition-seed",
    ) == "locked"

    assert _payloads(void.project("Why does Ghost Tax exist?", mode="synthesize")) == [
        why_body
    ]
    assert _payloads(
        void.project("Why does the orbital lunch policy exist?", mode="synthesize")
    ) == []


def test_exact_never_enters_synthesize_intent_cell_helpers(monkeypatch) -> None:
    void = ResidualVoid(secret="intent-cell-exact-isolation-secret-123456")
    source = (
        "SCI::GHOST_TAX_WHY::"
        "Ghost tax exists because a perfectly frozen phase would stop adaptation."
    )
    assert void.lock(source, identity="exact-seed") == "locked"

    def fail(*_args, **_kwargs):
        raise AssertionError("Exact entered Synthesize-only Intent Cell logic")

    monkeypatch.setattr(core, "classify_intent_cell", fail)
    monkeypatch.setattr(core, "_extract_synthesize_query_target", fail)

    assert _payloads(
        void.project(
            "Ghost tax exists because a perfectly frozen phase would stop adaptation.",
            mode="exact",
        )
    ) == [source]
