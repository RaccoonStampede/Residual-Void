from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

import pytest

from residual_void import PersistentVoid, ResidualVoid
from residual_void.server import create_http_server


def _payloads(result: dict) -> list[str]:
    return [item["payload"] for item in result["results"]]


def _acceptance_void() -> ResidualVoid:
    void = ResidualVoid()
    void.inject(
        "Ghost Tax is the five-percent coherence leak at an interface. "
        "Phase lock aligns a carrier to its reference without drift.",
        domain="Science",
        title="SCIENCE",
        identity="A",
        scale=2.5,
        density=1.4,
        intent="what",
    )
    void.inject(
        "The boat is a cedar skiff remembered from a quiet summer crossing.",
        domain="Memoir",
        title="MEMOIR",
        identity="B",
        scale=1.0,
        density=0.9,
        intent="what",
    )
    void.inject(
        "Step 1: Open the void. Step 2: Lock the complete source. "
        "Step 3: Query the structured shadows.",
        domain="Ops",
        title="OPS",
        identity="C",
        scale=1.8,
        density=1.1,
        intent="steps",
    )
    return void


def test_each_lock_creates_one_source_and_linked_shadows() -> None:
    void = ResidualVoid()
    result = void.lock(
        "Complete cobalt archive source. "
        "Amber index is the ranked voice record.",
        identity="Lab",
        scale=2.0,
        density=1.5,
        intent="what",
        shadow_texts=[
            "LAB::AMBER_INDEX_DEFINITION::Amber index is the ranked voice record."
        ],
    )
    assert result == "locked"

    residuals = void.void.field.residuals
    source = next(residual for residual in residuals if residual.layer == "source")
    shadow = next(residual for residual in residuals if residual.layer == "shadow")
    assert source.fragment == (
        "Complete cobalt archive source. "
        "Amber index is the ranked voice record."
    )
    assert source.source_id == shadow.source_id
    assert source.seed_identity == shadow.seed_identity == "Lab"
    assert source.seed_mass == shadow.seed_mass == 6.0
    assert source.protect is True
    assert source.imprint_layer == "deep"
    assert source.value == 0.0
    with pytest.raises(AttributeError, match="immutable_source"):
        source.fragment = "mutated source"
    with pytest.raises(AttributeError):
        source.content_set.add("invented")
    source_bits = source.bits()
    with pytest.raises(ValueError):
        source_bits[0] = 1 - source_bits[0]
    with pytest.raises(AttributeError, match="immutable_layer"):
        shadow.layer = "source"

    # Exact never enters the opinionated ranker and can only hear Source.
    original_rank = void.void.field.rank

    def fail_rank(*_args, **_kwargs):
        raise AssertionError("Exact mode called the Shadow ranker")

    void.void.field.rank = fail_rank  # type: ignore[method-assign]
    try:
        assert void.void.project("Complete cobalt archive source.", mode="exact") == source.fragment
    finally:
        void.void.field.rank = original_rank  # type: ignore[method-assign]

    assert _payloads(void.project("What is amber index?", mode="exact")) == [
        source.fragment
    ]
    assert _payloads(void.project("What is amber index?", mode="synthesize")) == [
        "Amber index is the ranked voice record."
    ]
    assert _payloads(void.project("What is cobalt archive?", mode="synthesize")) == []


def test_pair_write_rejects_ungrounded_shadows_and_rolls_back_failures() -> None:
    void = ResidualVoid()
    result = void.lock(
        "Complete cobalt archive source.",
        identity="Lab",
        shadow_texts=[
            "LAB::AMBER_INDEX_DEFINITION::Amber index is unrelated material."
        ],
    )
    assert result == "ungrounded_shadow"
    assert void.void.field.residuals == []

    original_store = void.void.field.store

    def fail_shadow(payload, *args, **kwargs):
        if kwargs.get("layer") == "shadow":
            return False, "forced_shadow_failure"
        return original_store(payload, *args, **kwargs)

    void.void.field.store = fail_shadow  # type: ignore[method-assign]
    try:
        assert void.lock("Atomic cobalt archive source.") == "forced_shadow_failure"
    finally:
        void.void.field.store = original_store  # type: ignore[method-assign]
    assert void.void.field.residuals == []
    assert void.void.field.chain_tip == "GENESIS"


def test_duplicate_grounded_shadows_are_deduplicated() -> None:
    void = ResidualVoid()
    shadow = "LAB::COBALT_FACT::Cobalt archive is complete."
    assert void.lock(
        "Cobalt archive is complete.",
        identity="Lab",
        shadow_texts=[shadow, shadow],
    ) == "locked"
    layers = [residual.layer for residual in void.void.field.residuals]
    assert layers.count("source") == 1
    assert layers.count("shadow") == 1


def test_three_seed_six_case_acceptance_battery() -> None:
    void = _acceptance_void()

    for index in range(40):
        assert void.lock(
            f"NOISE::LOCK_{index}_FACT::"
            f"Lock record {index} is an unrelated lightweight inventory marker.",
            domain="Noise",
            identity=f"noise-{index}",
            scale=0.2,
            density=0.2,
            intent="fact",
        ) == "locked"

    for mode in ("exact", "synthesize"):
        ghost_tax = _payloads(void.project("What is Ghost Tax?", mode=mode))
        assert ghost_tax and all("Ghost Tax" in payload for payload in ghost_tax)
        assert all("boat" not in payload.lower() for payload in ghost_tax)

        boat = _payloads(void.project("What is the boat?", mode=mode))
        assert boat and all("boat" in payload.lower() for payload in boat)
        assert all("Ghost Tax" not in payload for payload in boat)

        steps = _payloads(
            void.project("What are the steps to use the void?", mode=mode)
        )
        joined_steps = " ".join(steps)
        assert "Step 1" in joined_steps
        assert "Step 2" in joined_steps
        assert "Step 3" in joined_steps
        assert joined_steps.index("Step 1") < joined_steps.index("Step 2")
        assert joined_steps.index("Step 2") < joined_steps.index("Step 3")

        assert _payloads(
            void.project("How does the boat achieve phase lock?", mode=mode)
        ) == []

        phase_lock = _payloads(void.project("What is phase lock?", mode=mode))
        assert phase_lock
        assert all("phase lock" in payload.lower() for payload in phase_lock)
        assert all("inventory marker" not in payload for payload in phase_lock)

        assert _payloads(
            void.project("What is the orbital lunch policy?", mode=mode)
        ) == []

    status = void.status()["void"]
    assert status["lock_count"] == 43
    assert status["seeds"]["A"]["mass"] == 8.75
    assert status["seeds"]["B"]["mass"] == 0.9
    assert status["seeds"]["C"]["mass"] == 1.8 * 1.8 * 1.1
    assert status["layers"]["source"] == 43
    assert status["layers"]["shadow"] >= 46
    assert void.verify_integrity()[0] is True


def test_mass_breaks_equal_grounding_ties_without_creating_relevance() -> None:
    void = ResidualVoid()
    void.lock(
        "SCI::PHASE_LOCK_DEFINITION::"
        "Phase lock aligns a carrier to its stable reference.",
        identity="A-heavy",
        scale=2.5,
        density=1.4,
        intent="what",
    )
    void.lock(
        "NOISE::PHASE_LOCK_DEFINITION::"
        "Phase lock is a disposable lightweight label.",
        identity="Z-light",
        scale=0.2,
        density=0.2,
        intent="what",
    )
    answer = _payloads(void.project("What is phase lock?", mode="synthesize"))
    assert answer == ["Phase lock aligns a carrier to its stable reference."]
    assert _payloads(void.project("What is lunar basil?", mode="synthesize")) == []


def test_snapshot_and_persistent_replay_preserve_pairs_and_seed_metadata(
    tmp_path,
) -> None:
    facade = _acceptance_void()
    facade.snapshot("seeded")
    facade.clear()
    assert facade.restore("seeded") is True
    restored = facade.status()["void"]
    assert restored["layers"]["source"] == 3
    assert restored["layers"]["shadow"] == 6
    assert restored["seeds"]["A"]["mass"] == 8.75
    assert facade.verify_integrity()[0] is True

    storage = tmp_path / "hyperseed-chain.jsonl"
    persistent = PersistentVoid(storage_path=str(storage))
    assert persistent.lock(
        "OPS::RESTART_FACT::Restart replay keeps the HyperSeed ownership.",
        domain="Ops",
        identity="restart-seed",
        scale=1.8,
        density=1.1,
        intent="what",
    ) == "locked"
    replayed = PersistentVoid(storage_path=str(storage))
    replay_status = replayed.status()["void"]
    assert replay_status["layers"]["source"] == 1
    assert replay_status["layers"]["shadow"] == 1
    assert replay_status["seeds"]["restart-seed"]["mass"] == 1.8 * 1.8 * 1.1
    assert replayed.verify_integrity()[0] is True
    assert _payloads(replayed.project("What does restart replay keep?", mode="exact"))


def test_http_lock_and_status_round_trip_hyperseed_metadata() -> None:
    runtime = ResidualVoid()
    server = create_http_server(host="127.0.0.1", port=0, runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        body = json.dumps(
            {
                "text": "HTTP::SEED_FACT::The API carries seed ownership.",
                "domain": "Ops",
                "identity": "http-seed",
                "scale": 2.0,
                "density": 1.25,
                "intent": "what",
            }
        ).encode("utf-8")
        request = Request(
            f"{base}/lock",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            locked = json.loads(response.read().decode("utf-8"))
        assert locked["result"] == "locked"
        assert locked["source_id"]
        assert locked["seed"]["identity"] == "http-seed"

        with urlopen(f"{base}/status", timeout=5) as response:
            status = json.loads(response.read().decode("utf-8"))
        assert status["void"]["layers"]["source"] == 1
        assert status["void"]["layers"]["shadow"] == 1
        assert status["void"]["seeds"]["http-seed"]["mass"] == 5.0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)