"""Multi-residual intents must return List[str] in BOTH exact and synthesize modes.

Task acceptance: LIST / COMPARE / STEPS / SUMMARIZE (and RELATE) queries return
full multi-item answers in synthesize mode, matching exact-mode behaviour.
"""
import pytest

from residual_void.core import CoherentVoid, SecureNode
from residual_void.merged import ResidualVoid


def _seed(void: CoherentVoid) -> None:
    node = SecureNode("seed", void)
    frags = [
        # LIST items — engine components
        "DOC::ENGINE_PARTS_LIST_ITEM::The core lattice is one engine component that stores residual frequencies.",
        "DOC::ENGINE_PARTS_2_LIST_ITEM::The carrier driver is one engine component that vibrates residuals toward the query phase.",
        "DOC::ENGINE_PARTS_3_LIST_ITEM::The bellman ranker is one engine component that scores residual value over time.",
        # STEPS — locking procedure
        "DOC::LOCK_STEP_1::Step 1 sign the payload with the shared secret before locking.",
        "DOC::LOCK_STEP_2::Step 2 verify the signature and store the residual in the field.",
        "DOC::LOCK_STEP_3::Step 3 confirm the lock and update the hash chain.",
        # COMPARE targets — definitions
        "DOC::CORE_LATTICE_DEFINITION::The core lattice is the storage layer that keeps every locked residual.",
        "DOC::CARRIER_DRIVER_DEFINITION::The carrier driver is the retrieval layer that aligns residuals with a query.",
        # RELATION
        "DOC::LATTICE_DRIVER_RELATION::The core lattice and the carrier driver are linked because retrieval reads what storage locks.",
        # background noise
        "DOC::GHOST_TAX_WHY::Ghost tax exists because perfect phase lock would freeze the field.",
    ]
    for f in frags:
        assert node.lock_text(f, domain="doc") == "locked", f"failed to lock: {f}"


@pytest.fixture()
def void() -> CoherentVoid:
    v = CoherentVoid(secret="multibody-test-secret-key-123456")
    _seed(v)
    return v


@pytest.mark.parametrize("mode", ["exact", "synthesize"])
def test_list_query_returns_all_items(void: CoherentVoid, mode: str) -> None:
    result = void.project("List the engine components", mode=mode)
    assert isinstance(result, list), f"{mode}: expected List[str], got {type(result)}: {result!r}"
    assert len(result) >= 3, f"{mode}: expected >=3 list items, got {result!r}"
    joined = " ".join(result).lower()
    for part in ("core lattice", "carrier driver", "bellman ranker"):
        assert part in joined, f"{mode}: missing list item {part!r} in {result!r}"


@pytest.mark.parametrize("mode", ["exact", "synthesize"])
def test_steps_query_returns_ordered_steps(void: CoherentVoid, mode: str) -> None:
    result = void.project("What are the steps to lock a residual?", mode=mode)
    assert isinstance(result, list), f"{mode}: expected List[str], got {result!r}"
    assert len(result) == 3, f"{mode}: expected 3 steps, got {result!r}"
    assert "step 1" in result[0].lower()
    assert "step 2" in result[1].lower()
    assert "step 3" in result[2].lower()


@pytest.mark.parametrize("mode", ["exact", "synthesize"])
def test_compare_query_returns_two_items(void: CoherentVoid, mode: str) -> None:
    result = void.project(
        "What is the difference between the core lattice and the carrier driver?", mode=mode
    )
    assert isinstance(result, list), f"{mode}: expected List[str], got {result!r}"
    assert len(result) == 2, f"{mode}: expected 2 compare items, got {result!r}"
    joined = " ".join(result).lower()
    assert "core lattice" in joined and "carrier driver" in joined


@pytest.mark.parametrize("mode", ["exact", "synthesize"])
def test_relate_query_returns_matched_items(void: CoherentVoid, mode: str) -> None:
    result = void.project("How does the core lattice relate to the carrier driver?", mode=mode)
    assert isinstance(result, list), f"{mode}: expected List[str], got {result!r}"
    assert 1 <= len(result) <= 2, f"{mode}: expected 1-2 relate items, got {result!r}"
    assert "linked" in " ".join(result).lower() or "lattice" in " ".join(result).lower()


@pytest.mark.parametrize("mode", ["exact", "synthesize"])
def test_summarize_query_returns_multiple_items(void: CoherentVoid, mode: str) -> None:
    result = void.project("Summarize the engine components", mode=mode)
    assert isinstance(result, list), f"{mode}: expected List[str], got {result!r}"
    assert len(result) >= 2, f"{mode}: expected multi-item summary, got {result!r}"


@pytest.mark.parametrize("mode", ["exact", "synthesize"])
def test_facade_wraps_multi_items_as_separate_results(mode: str) -> None:
    rt = ResidualVoid(secret="facade-multibody-secret-abcdef12")
    _seed(rt.void)
    out = rt.project("List the engine components", mode=mode)
    assert out["source"] == "void"
    assert len(out["results"]) >= 3, f"{mode}: facade should expose one result per item: {out!r}"
