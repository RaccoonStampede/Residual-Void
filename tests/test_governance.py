"""Tests for task-14: active/latent engram governance visibility.

Covers:
- Same-family replacement demotes the prior residual to latent.
- /lock metadata: tagged fragments expose family + active; untagged do not expose family.
- /status memory.families: only tag-derived families appear; per-family active/latent counts correct.
- _is_safe_external_family_key validates the safe-identifier grammar.
- Thread-local lock info is per-thread (basic assertion that attribute exists after a lock).
"""
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from residual_void.merged import ResidualVoid
from residual_void.core import (
    CoherentField,
    _derive_family_key,
    _is_safe_external_family_key,
    _store_result_local,
)


# ---------------------------------------------------------------------------
# _is_safe_external_family_key
# ---------------------------------------------------------------------------

class TestSafeFamilyKeyGrammar:
    def test_valid_known_lineage_suffix_what(self):
        assert _is_safe_external_family_key("ghost-tax-what") is True

    def test_valid_known_lineage_suffix_how(self):
        assert _is_safe_external_family_key("hyperseed-how") is True

    def test_valid_known_lineage_suffix_why(self):
        assert _is_safe_external_family_key("zero-drift-why") is True

    def test_valid_two_word_lineage_list_item(self):
        assert _is_safe_external_family_key("content-list-item") is True

    def test_unknown_lineage_suffix_rejected(self):
        assert _is_safe_external_family_key("ghost-tax-unknown") is False

    def test_consecutive_hyphens_rejected(self):
        assert _is_safe_external_family_key("ghost--tax-what") is False

    def test_no_lineage_suffix_rejected(self):
        # "intro-full" has no recognised lineage at the end
        assert _is_safe_external_family_key("intro-full") is False

    def test_uppercase_rejected(self):
        assert _is_safe_external_family_key("GHOST-TAX-WHAT") is False

    def test_spaces_rejected(self):
        assert _is_safe_external_family_key("ghost tax what") is False

    def test_leading_hyphen_rejected(self):
        assert _is_safe_external_family_key("-ghost-what") is False


# ---------------------------------------------------------------------------
# _derive_family_key
# ---------------------------------------------------------------------------

class TestDeriveFamilyKey:
    def test_topic_lineage_format_tagged(self):
        slug, tagged = _derive_family_key("GHOST_TAX::WHAT::A HyperSeed is a 200-byte packet.")
        assert slug == "ghost-tax-what"
        assert tagged is True

    def test_domain_tag_format_tagged(self):
        slug, tagged = _derive_family_key("DOC::ZERO_DRIFT_WHY::body text here")
        assert slug == "zero-drift-why"
        assert tagged is True

    def test_hyperseed_how_format_tagged(self):
        slug, tagged = _derive_family_key("HYPERSEED::HOW::carrier wave explanation")
        assert slug == "hyperseed-how"
        assert tagged is True

    def test_untagged_body_not_tagged(self):
        slug, tagged = _derive_family_key("SensitiveCorpusContent is the secret phrase.")
        assert tagged is False  # body-word fallback — never safe to expose

    def test_no_lineage_suffix_not_tagged(self):
        # INTRO_FULL has no recognised lineage suffix → not safe to expose
        _, tagged = _derive_family_key("DOC::INTRO_FULL::no lineage tag here")
        assert tagged is False


# ---------------------------------------------------------------------------
# Active / latent governance via CoherentField
# ---------------------------------------------------------------------------

class TestActiveLatentGovernance:
    def _make_field(self):
        f = CoherentField()
        return f

    def test_first_residual_is_active(self):
        f = self._make_field()
        f.store("GHOST_TAX::WHAT::A HyperSeed is a 200-byte resonance packet.", node_id="n")
        r = f.residuals[-1]
        assert r.active is True
        assert r.family == "ghost-tax-what"
        assert r.family_tagged is True

    def test_second_same_family_demotes_first(self):
        f = self._make_field()
        f.store("GHOST_TAX::WHAT::First definition of HyperSeed.", node_id="n")
        first = f.residuals[-1]
        f.store("GHOST_TAX::WHAT::Second, more precise HyperSeed definition.", node_id="n")
        second = f.residuals[-1]

        # Second is now active; first is latent.
        assert first.active is False, "First residual must be latent after replacement"
        assert second.active is True, "Second residual must be active after lock"
        assert first.family == second.family == "ghost-tax-what"

    def test_different_lineages_are_independent_families(self):
        f = self._make_field()
        f.store("GHOST_TAX::WHAT::HyperSeed is a packet.", node_id="n")
        f.store("GHOST_TAX::HOW::HyperSeed is propagated via carrier waves.", node_id="n")
        what_r = f.residuals[-2]
        how_r = f.residuals[-1]

        # Different family slugs → neither demotes the other.
        assert what_r.family == "ghost-tax-what"
        assert how_r.family == "ghost-tax-how"
        assert what_r.active is True
        assert how_r.active is True

    def test_untagged_body_family_not_externally_tagged(self):
        f = self._make_field()
        f.store("SensitiveBodyWord is a secret phrase no one should see.", node_id="n")
        r = f.residuals[-1]
        # Governance still assigns a family key for internal deduplication,
        # but it must NOT be marked as safe for external exposure.
        assert r.family_tagged is False


# ---------------------------------------------------------------------------
# status() memory summary — correctness and no content leak
# ---------------------------------------------------------------------------

class TestStatusMemorySummary:
    def _make_runtime(self):
        return ResidualVoid(secret="test-governance-secret-xyz789")

    def test_status_shows_correct_per_family_counts(self):
        rv = self._make_runtime()
        rv.lock("GHOST_TAX::WHAT::First definition.", domain="general")
        rv.lock("GHOST_TAX::WHAT::Second definition (supersedes first).", domain="general")

        st = rv.status()
        families = st["memory"]["families"]

        assert "ghost-tax-what" in families, f"Expected 'ghost-tax-what' in {families}"
        counts = families["ghost-tax-what"]
        assert counts["active"] == 1, f"Expected 1 active, got {counts}"
        assert counts["latent"] == 1, f"Expected 1 latent, got {counts}"

    def test_status_does_not_expose_untagged_body_families(self):
        rv = self._make_runtime()
        rv.lock("SensitiveCorpusContent is the secret phrase no one should see.", domain="general")

        st = rv.status()
        families = st["memory"]["families"]
        # The body-word family must not appear in the external status.
        for key in families:
            assert "sensitivecorpuscontent" not in key.lower(), (
                f"Body-derived word leaked into status families: {key!r}"
            )

    def test_status_multiple_families_each_reported(self):
        rv = self._make_runtime()
        rv.lock("GHOST_TAX::WHAT::HyperSeed definition.", domain="general")
        rv.lock("HYPERSEED::HOW::Carrier-wave propagation method.", domain="general")

        st = rv.status()
        families = st["memory"]["families"]
        assert "ghost-tax-what" in families
        assert "hyperseed-how" in families

    def test_status_latent_count_and_active_count_accurate_after_multiple_replacements(self):
        rv = self._make_runtime()
        # Lock three revisions of the same family:
        rv.lock("GHOST_TAX::WHAT::Version one.", domain="general")
        rv.lock("GHOST_TAX::WHAT::Version two.", domain="general")
        rv.lock("GHOST_TAX::WHAT::Version three.", domain="general")

        st = rv.status()
        counts = st["memory"]["families"]["ghost-tax-what"]
        assert counts["active"] == 1
        assert counts["latent"] == 2


# ---------------------------------------------------------------------------
# lock() response metadata
# ---------------------------------------------------------------------------

class TestLockResponseMetadata:
    def _make_runtime(self):
        return ResidualVoid(secret="test-lock-meta-secret-abc123")

    def test_tagged_lock_exposes_family_and_active(self):
        rv = self._make_runtime()
        rv.lock("GHOST_TAX::WHAT::A HyperSeed is a 200-byte resonance packet.", domain="general")
        info = rv.last_locked_info()

        assert info is not None
        assert info["family"] == "ghost-tax-what", f"Unexpected family: {info['family']!r}"
        assert info["active"] is True
        assert info["family_tagged"] is True

    def test_untagged_lock_suppresses_family(self):
        rv = self._make_runtime()
        rv.lock("SensitiveCorpusContent is the secret phrase no one should see.", domain="general")
        info = rv.last_locked_info()

        assert info is not None
        # family_tagged must be False so server omits 'family' from the response
        assert info["family_tagged"] is False

    def test_same_family_second_lock_is_active(self):
        rv = self._make_runtime()
        rv.lock("GHOST_TAX::WHAT::First definition.", domain="general")
        rv.lock("GHOST_TAX::WHAT::Second definition.", domain="general")
        info = rv.last_locked_info()

        assert info is not None
        assert info["active"] is True
        assert info["family"] == "ghost-tax-what"
        assert info["family_tagged"] is True

    def test_thread_local_is_per_thread(self):
        """Each thread gets its own lock info; concurrent locks don't cross-contaminate."""
        rv = self._make_runtime()
        results = {}

        def lock_and_capture(tag, key):
            rv.lock(f"{tag}::WHAT::Body for {tag.lower()}.", domain="general")
            results[key] = rv.last_locked_info()

        t1 = threading.Thread(target=lock_and_capture, args=("ALPHA_TOPIC", "t1"))
        t2 = threading.Thread(target=lock_and_capture, args=("BETA_TOPIC", "t2"))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Each thread should have captured its own lock info (different families).
        assert results["t1"]["family"] == "alpha-topic-what"
        assert results["t2"]["family"] == "beta-topic-what"
