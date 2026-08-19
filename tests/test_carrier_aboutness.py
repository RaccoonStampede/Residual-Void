"""Carrier-aboutness gate: same-frame wrong-carrier residuals must not win.

The frame gate stops MECHANISM from answering DEFINITION queries; this gate
stops a high-Bellman MECHANISM residual about carrier A from answering a HOW
query about carrier B when both survive the frame gate.
"""

from residual_void.core import (
    CoherentVoid,
    _carrier_aboutness,
    _extract_action_stems,
    _extract_carrier_target,
)

DOCS = [
    "DOC::GHOST_TAX_HOW::Harness Mode suppresses the ghost tax by raising the epsilon floor.",
    "DOC::ENTRAINMENT_HOW::Entrainment works by locking phase coupling between oscillating fields.",
    "DOC::EMPATHY_HOW::Empathy works by mirroring another field's carrier wave until resonance forms.",
    "DOC::CARRIER_HOW::The carrier wave works by projecting a reference oscillation across the void.",
]


def _build_void(weights):
    void = CoherentVoid()
    for doc, n in zip(DOCS, weights):
        for _ in range(n):
            void.field.store(doc, domain="doc")
    return void


def test_carrier_target_extraction():
    stems = _extract_action_stems("How does entrainment work?")
    assert _extract_carrier_target("How does entrainment work?", stems) == "entrainment"
    stems = _extract_action_stems("How do you suppress the ghost tax?")
    assert _extract_carrier_target("How do you suppress the ghost tax?", stems) == "ghost tax"


def test_aboutness_grades():
    # Primary subject (opens body)
    assert _carrier_aboutness("entrainment", DOCS[1].split("::", 2)[2]) == 2
    # Acted upon in the lead clause
    assert _carrier_aboutness("ghost tax", DOCS[0].split("::", 2)[2]) == 2
    # Possessive incidental mention is NOT primary subject
    assert _carrier_aboutness("carrier wave", DOCS[2].split("::", 2)[2]) < 2
    # Absent
    assert _carrier_aboutness("entrainment", DOCS[0].split("::", 2)[2]) == 0


def test_each_carrier_wins_its_own_how_query():
    void = _build_void([3, 3, 3, 3])
    # Skew Bellman weight heavily toward the ghost-tax residual
    for _ in range(10):
        void.project("How do you suppress the ghost tax?", mode="exact")

    assert "Entrainment works" in void.project("How does entrainment work?", mode="exact")
    assert "Empathy works" in void.project("How does empathy work?", mode="exact")
    # Incidental "carrier wave" mention in the empathy body must not win
    assert "carrier wave works" in void.project("How does the carrier wave work?", mode="exact")
    assert "ghost tax" in void.project("How do you suppress the ghost tax?", mode="exact")


def test_original_8x4_scenario():
    void = _build_void([8, 4, 0, 0])
    for _ in range(8):
        void.project("How do you suppress the ghost tax?", mode="exact")
    assert "Entrainment works" in void.project("How does entrainment work?", mode="exact")


def test_absent_carrier_refuses():
    void = _build_void([8, 4, 0, 0])
    out = void.project("How do you suppress the flux capacitor?", mode="exact")
    assert out == void._REFUSAL


def test_incidental_possessive_mention_refuses():
    # Corpus has the empathy residual (possessive incidental "carrier wave"
    # mention) but NO genuine carrier-wave residual — must refuse, not answer.
    void = _build_void([3, 3, 3, 0])
    for _ in range(6):
        void.project("How does empathy work?", mode="exact")
    assert void.project("How does the carrier wave work?", mode="exact") == void._REFUSAL
    assert void.project("How does the carrier wave function?", mode="exact") == void._REFUSAL


def test_incidental_prepositional_mention_refuses():
    void = CoherentVoid()
    doc = ("DOC::COUPLING_HOW::Phase locking works by tightening coupling "
           "between the carrier wave and the local field oscillator.")
    for _ in range(4):
        void.field.store(doc, domain="doc")
    assert void.project("How does the carrier wave work?", mode="exact") == void._REFUSAL


def test_common_prepositions_are_incidental():
    # Every common prepositional attachment must grade as incidental (1), not subject (2)
    for prep in ("for", "in", "on", "at", "by", "about", "with", "from", "to"):
        body = f"Empathy works {prep} the carrier wave until resonance forms."
        assert _carrier_aboutness("carrier wave", body) == 1, prep
    # Direct-object after a verb stays grade 2
    assert _carrier_aboutness("ghost tax", "Harness Mode suppresses the ghost tax daily.") == 2
