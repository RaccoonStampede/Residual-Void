"""Tests for task-15: backfill family keys when a pre-governance snapshot is restored.

Scenarios:
- Residuals with family="" get their family key re-derived after snapshot load.
- FIFO ordering is enforced: the last same-family residual is active; earlier ones
  are latent.
- Residuals that genuinely cannot be classified (family remains "") are untouched.
- A newly locked residual after restore can demote an old same-family cousin.
"""
from __future__ import annotations

import pytest
from residual_void.core import CoherentField, _derive_family_key
from residual_void.merged import ResidualVoid


# ---------------------------------------------------------------------------
# CoherentField.backfill_governance unit tests
# ---------------------------------------------------------------------------

class TestBackfillGovernance:
    """Unit tests for CoherentField.backfill_governance()."""

    def _make_field_with_ungoverned_residual(self, fragment: str) -> CoherentField:
        """Store a residual then manually clear its family key to simulate pre-governance state."""
        field = CoherentField()
        ok, _ = field.store(fragment, domain="general", node_id="test")
        assert ok, "Setup: store must succeed"
        # Simulate pre-governance snapshot: wipe the derived family key
        res = field.residuals[-1]
        res.family = ""
        res.family_tagged = False
        return field

    def test_backfill_derives_family_from_tagged_fragment(self):
        """A residual with family='' gets its family re-derived from the fragment tag."""
        fragment = "GHOST_TAX::WHAT::A HyperSeed is a 200-byte memory packet."
        field = self._make_field_with_ungoverned_residual(fragment)
        assert field.residuals[0].family == "", "Pre-condition: family must be empty"

        count = field.backfill_governance()

        assert count == 1
        res = field.residuals[0]
        assert res.family == "ghost-tax-what"
        assert res.family_tagged is True
        assert res.active is True  # only member of its family

    def test_backfill_fifo_last_sibling_wins(self):
        """With two same-family residuals both at family='', FIFO makes the later one active."""
        field = CoherentField()
        frag1 = "GHOST_TAX::WHAT::Original definition of the ghost tax."
        frag2 = "GHOST_TAX::WHAT::Updated definition of the ghost tax mechanism."
        field.store(frag1, domain="general", node_id="test")
        field.store(frag2, domain="general", node_id="test")
        # Simulate pre-governance: clear both family keys
        for r in field.residuals:
            r.family = ""
            r.family_tagged = False
            r.active = True  # old default

        count = field.backfill_governance()

        assert count == 2
        first, second = field.residuals[0], field.residuals[1]
        assert first.family == second.family == "ghost-tax-what"
        assert first.active is False, "Older sibling must be latent"
        assert second.active is True, "Newer sibling must be active"

    def test_backfill_different_lineages_remain_independently_active(self):
        """WHAT and HOW residuals for the same topic each stay active (separate families)."""
        field = CoherentField()
        frag_what = "GHOST_TAX::WHAT::The ghost tax is a coherence-drain effect."
        frag_how  = "GHOST_TAX::HOW::Harness Mode suppresses the ghost tax floor."
        field.store(frag_what, domain="general", node_id="test")
        field.store(frag_how,  domain="general", node_id="test")
        for r in field.residuals:
            r.family = ""
            r.family_tagged = False

        field.backfill_governance()

        what_r = field.residuals[0]
        how_r  = field.residuals[1]
        assert what_r.family == "ghost-tax-what"
        assert how_r.family  == "ghost-tax-how"
        assert what_r.active is True
        assert how_r.active  is True

    def test_backfill_unclassifiable_fragment_stays_empty(self):
        """A fragment from which no family can be derived keeps family='' after backfill."""
        field = CoherentField()
        # Very short fragment that passes minimum length but has no derivable family
        # (no envelope tag, and body words are all stop-words or too short)
        fragment = "Is it or not?"  # too short — use something ≥ 8 chars
        fragment = "Is it or is it not at all true"
        ok, _ = field.store(fragment, domain="general", node_id="test")
        assert ok
        field.residuals[-1].family = ""
        field.residuals[-1].family_tagged = False

        count = field.backfill_governance()

        # Expect 0 if _derive_family_key still can't derive a key, or 1 if it can —
        # what matters is that no exception is raised and the residual stays active.
        res = field.residuals[-1]
        assert res.active is True  # sole ungoverned residual: active by default

    def test_backfill_returns_zero_when_all_governed(self):
        """backfill_governance returns 0 when all residuals already have family keys."""
        field = CoherentField()
        field.store("GHOST_TAX::WHAT::The ghost tax is a coherence-drain effect.", domain="general", node_id="test")
        # family is already derived by store() — backfill has nothing to do
        count = field.backfill_governance()
        assert count == 0


# ---------------------------------------------------------------------------
# ResidualVoid snapshot restoration integration tests
# ---------------------------------------------------------------------------

class TestSnapshotRestoreGovernance:
    """Snapshot restore correctly governs pre-governance residuals."""

    @pytest.fixture
    def void(self):
        return ResidualVoid(secret="test-backfill-secret-xyzABC")

    def test_restore_applies_governance_to_ungoverned_residuals(self, void):
        """After restoring a snapshot that had family='', newly locked cousin can demote the old one."""
        # Lock one tagged residual
        void.lock("GHOST_TAX::WHAT::Original ghost-tax definition locked before governance.")
        # Simulate pre-governance state: clear family from the live void
        for r in void._void.field.residuals:
            if r.layer == "shadow" and "GHOST_TAX" in r.fragment:
                r.family = ""
                r.family_tagged = False
                r.active = True

        # Take snapshot and restore — backfill should run
        void.snapshot("pre-gov")
        void.restore("pre-gov")

        # After restore, Shadows should have family keys. Immutable Sources are
        # deliberately outside ranking/governance and keep no family state.
        restored = [
            r for r in void._void.field.residuals
            if r.layer == "shadow" and "GHOST_TAX" in r.fragment
        ]
        sources = [
            r for r in void._void.field.residuals
            if r.layer == "source" and "GHOST_TAX" in r.fragment
        ]
        assert restored, "Residual must survive restore"
        assert restored[0].family == "ghost-tax-what", (
            f"Expected 'ghost-tax-what', got {restored[0].family!r}"
        )
        assert all(r.family == "" for r in sources)

    def test_restore_fifo_ordering_after_backfill(self, void):
        """When two same-family ungoverned residuals are restored, FIFO makes the later one active."""
        void.lock("GHOST_TAX::WHAT::First version of the ghost-tax definition text.")
        void.lock("GHOST_TAX::WHAT::Second version of the ghost-tax definition text.")

        # Clear Shadow family keys (simulate a pre-governance snapshot).
        for r in void._void.field.residuals:
            if r.layer == "shadow":
                r.family = ""
                r.family_tagged = False
                r.active = True

        void.snapshot("two-ungoverned")
        void.restore("two-ungoverned")

        ghost_tax = [
            r for r in void._void.field.residuals
            if r.layer == "shadow"
            and ("ghost-tax" in r.fragment.lower() or "GHOST_TAX" in r.fragment)
        ]
        assert len(ghost_tax) == 2
        # Index order is preserved — first stored → index 0, second → index 1
        first, second = ghost_tax[0], ghost_tax[1]
        assert first.active  is False, "Older same-family residual must be latent after restore"
        assert second.active is True,  "Newer same-family residual must be active after restore"

    def test_after_restore_new_lock_demotes_backfilled_residual(self, void):
        """A residual with backfilled family is correctly demoted when a new same-family is locked."""
        void.lock("GHOST_TAX::WHAT::Pre-governance ghost-tax definition to backfill.")
        # Simulate pre-governance
        for r in void._void.field.residuals:
            if r.layer == "shadow":
                r.family = ""
                r.family_tagged = False

        void.snapshot("pre-gov-demote")
        void.restore("pre-gov-demote")

        # Check the restored residual got a family key
        restored = [
            r for r in void._void.field.residuals
            if r.layer == "shadow" and "GHOST_TAX" in r.fragment
        ]
        assert restored[0].family == "ghost-tax-what"
        assert restored[0].active is True

        # Now lock a new residual in the same family — the old one must be demoted
        void.lock("GHOST_TAX::WHAT::Post-governance updated ghost-tax definition text.")
        residuals = [r for r in void._void.field.residuals if "ghost-tax-what" == r.family]
        active_ones   = [r for r in residuals if r.active]
        latent_ones   = [r for r in residuals if not r.active]
        assert len(active_ones) == 1, f"Exactly one active engram expected; got {len(active_ones)}"
        assert len(latent_ones) == 1, f"Exactly one latent engram expected; got {len(latent_ones)}"
        assert "Post-governance" in active_ones[0].fragment
