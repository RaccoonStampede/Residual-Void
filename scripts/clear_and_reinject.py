#!/usr/bin/env python3
"""
Clear the production corpus, re-inject all source documents via the fixed
auto_segment (anaphoric-merge fix), and run the acceptance battery.

Usage:
    python clear_and_reinject.py [--url http://localhost:8080]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict

BASE_URL = "http://localhost:8080"

PASS_MARK = "\033[32mPASS\033[0m"
FAIL_MARK = "\033[31mFAIL\033[0m"
_failures: list[str] = []


def _post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _get(path: str) -> Dict[str, Any]:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode())


def _assert(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS_MARK}  {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"  {FAIL_MARK}  {msg}")
        _failures.append(msg)


# ---------------------------------------------------------------------------
# Source corpus — these are the canonical documents.
# All go through /inject → auto_segment (with anaphoric-merge fix applied).
# Each document's topic sentence is an active subject so the fix keeps the
# anaphoric "It carries…" merged into its parent sentence.
# ---------------------------------------------------------------------------

SOURCE_DOCUMENTS = [
    # --- HyperSeed ---
    # "It carries…" follows an anaphoric split; the fix merges it back so
    # we get ONE residual about HyperSeed rather than a fake ghost-tax orphan.
    (
        "DOC",
        "HYPERSEED",
        "A HyperSeed is a compact digital germline of about 200 bytes. "
        "It carries phase constants, Ghost Tax, source intent bias, and mathematical identity. "
        "HyperSeeds are write-protected and serve as the origin anchor for all subsequent residuals.",
    ),

    # --- Ghost Tax ---
    (
        "DOC",
        "GHOST_TAX",
        "The ghost tax is a persistent inefficiency floor of about five percent in macro systems. "
        "It represents the irreducible generative leakage that prevents sterile lock. "
        "Harness Mode suppresses the ghost tax by raising gamma toward zero. "
        "If the ghost tax is not harnessed, the floor persists and efficiency stays capped.",
    ),

    # --- Orch-OR ---
    (
        "DOC",
        "ORCH_OR",
        "Orch-OR places conscious moments at discrete quantum collapses inside microtubules. "
        "Orchestrated objective reduction in quantum-coherent microtubule networks produces specific "
        "experiential states. Orch-OR is the theory that consciousness arises from orchestrated "
        "quantum reductions in neuronal microtubules.",
    ),

    # --- Boat / Storm / Docking ---
    # Note: "Your boat is your consciousness — the hull is your subconscious moral tilt"
    # is written as a single clause so auto_segment keeps them together.
    (
        "DOC",
        "BOAT_STORM",
        "Your boat is your consciousness, and the hull is your subconscious moral tilt — "
        "how you're oriented toward good or harm. "
        "The storm is the result of too many boats tilting bad at once, "
        "creating turbulent collective coherence. "
        "Sometimes calming the storm means deliberately crashing your calm boat into it — "
        "controlled docking, an empathic approach — but back off if the impact is too intense.",
    ),

    # --- Empathy & Entrainment ---
    (
        "DOC",
        "EMPATHY_ENTRAINMENT",
        "High empathy creates coherent paths — things line up, people respond warmly, opportunities appear. "
        "Low empathy creates turbulent paths where signals fragment and outcomes scatter. "
        "If there is no entrainment at all, local rhythms fragment and coherence collapses into noise. "
        "Harness Mode restores entrainment lock by increasing coupling to the carrier frequency.",
    ),
]


def step_clear() -> None:
    print("\n── Step 1: POST /clear ──────────────────────────────────")
    try:
        resp = _post("/clear", {})
        print(f"  Clear response: {resp}")
        _assert("/clear returned JSON", isinstance(resp, dict))
        # Immediately verify the field is empty
        status_after = _get("/status")
        locked_after = status_after.get("void", {}).get("locked", -1)
        families_after = status_after.get("memory", {}).get("families", {})
        print(f"  Post-clear locked={locked_after}  families={list(families_after.keys())}")
        _assert(
            "field is empty after /clear (locked == 0)",
            locked_after == 0,
            f"locked={locked_after}",
        )
        _assert(
            "no active families after /clear",
            len(families_after) == 0,
            f"families={list(families_after.keys())}",
        )
        if locked_after != 0:
            print("  ABORT: field is not empty; halting before injection.")
            sys.exit(2)
    except Exception as exc:
        _assert("/clear succeeded", False, str(exc))
        sys.exit(2)


def step_inject() -> None:
    print("\n── Step 2: POST /inject (source documents) ─────────────")
    total_segments = 0
    total_locked = 0
    for domain, title, full_text in SOURCE_DOCUMENTS:
        try:
            resp = _post("/inject", {
                "full_text": full_text,
                "domain": domain,
                "title": title,
                "protect": True,
            })
            segs = resp.get("segments", 0)
            locked = resp.get("locked", 0)
            total_segments += segs
            total_locked += locked
            print(f"  [{title}]  segments={segs}  locked={locked}")
            _assert(f"/inject {title} has segments", segs >= 1, f"resp={resp}")
            _assert(
                f"/inject {title} locked == segments (no silently dropped segments)",
                locked == segs,
                f"locked={locked}  segments={segs}",
            )
        except Exception as exc:
            _assert(f"/inject {title}", False, str(exc))

    print(f"\n  Total: {total_segments} segments, {total_locked} locked")
    _assert("at least 5 residuals locked", total_locked >= 5, f"got {total_locked}")

    # Verify the final corpus count matches the sum of all locked segments
    status = _get("/status")
    live_count = status.get("void", {}).get("locked", -1)
    print(f"  /status locked count after inject: {live_count}")
    _assert(
        f"live locked count ({live_count}) == total locked ({total_locked})",
        live_count == total_locked,
        f"status locked={live_count}, inject total={total_locked}",
    )


def step_verify_no_orphans() -> None:
    """Verify no pre-fix anaphoric orphan residuals remain.

    The classic orphan is the sentence fragment:
        "It carries phase constants, Ghost Tax, source intent bias..."
    which was split away from its HyperSeed parent sentence before the
    anaphoric-merge fix.  It would compete on ghost-tax queries and cause the
    wrong answer to surface.

    We verify two things:
    1. There is no active family whose key is derived purely from ghost-tax
       tokens that came from the HyperSeed carrier sentence orphan.
    2. A ghost-tax query does NOT return a fragment containing "It carries"
       as the top answer (the tell-tale orphan response).
    """
    print("\n── Step 3: Verify no orphan patterns survive ─────────────")
    try:
        status = _get("/status")
        locked_count = status.get("void", {}).get("locked", 0)
        families = status.get("memory", {}).get("families", {})
        print(f"  locked residuals: {locked_count}")
        print(f"  family keys: {list(families.keys())}")
        _assert("field has residuals", locked_count > 0)

        # No family key should look like a ghost-tax key derived from the
        # orphan sentence "It carries phase constants, Ghost Tax..." — those
        # body-word-only families would have no lineage suffix.
        orphan_family_pattern = "carries-phase-constants"
        orphan_keys = [k for k in families if orphan_family_pattern in k]
        _assert(
            "no orphan 'It carries phase constants' family key present",
            len(orphan_keys) == 0,
            f"orphan keys: {orphan_keys}",
        )

        # Direct orphan check: ghost-tax query must NOT return "It carries"
        ghost_answer = _project("What is the ghost tax?", "exact")
        orphan_pattern = ghost_answer.lower().startswith("it carries")
        _assert(
            "ghost-tax answer is not the orphan 'It carries...' fragment",
            not orphan_pattern,
            f"answer={ghost_answer[:100]!r}",
        )
        print(f"  ghost-tax answer: {ghost_answer[:100]!r}")

        # HyperSeed query must contain 'hyperseed' — proves the merged
        # HyperSeed+carries sentence won instead of the ghost-tax orphan.
        hs_answer = _project("What is a HyperSeed?", "exact")
        _assert(
            "HyperSeed answer contains 'hyperseed' (merged sentence, not orphan)",
            "hyperseed" in hs_answer.lower(),
            f"answer={hs_answer[:100]!r}",
        )
        print(f"  HyperSeed answer: {hs_answer[:100]!r}")

    except Exception as exc:
        _assert("GET /status succeeded", False, str(exc))


def _project(query: str, mode: str = "exact") -> str:
    """Return the top payload string for a query, or '' on failure."""
    try:
        resp = _post("/project", {"query": query, "mode": mode, "top_k": 3})
        results = resp.get("results", [])
        if not results:
            return ""
        top = results[0]
        return (
            top.get("payload", "")
            or top.get("fragment", "")
            or top.get("text", "")
            or ""
        )
    except Exception:
        return ""


def step_acceptance_battery() -> None:
    print("\n── Step 4: Acceptance battery ───────────────────────────")

    # (label, query, mode, required_substrings, must_be_empty)
    battery = [
        # Ghost tax — definition
        (
            "ghost tax definition",
            "What is the ghost tax?",
            "exact",
            ["ghost tax", "floor"],
            False,
        ),
        # Ghost tax — mechanism (suppress)
        (
            "suppress ghost tax",
            "How do you suppress the ghost tax?",
            "exact",
            ["harness", "suppress"],
            False,
        ),
        # HyperSeed definition — must NOT mention only Ghost Tax
        (
            "HyperSeed definition",
            "What is a HyperSeed?",
            "exact",
            ["hyperseed", "germline"],
            False,
        ),
        # Orch-OR
        (
            "Orch-OR",
            "What is Orch-OR?",
            "exact",
            ["microtubule", "quantum"],
            False,
        ),
        # Boat
        (
            "boat definition",
            "What is the boat?",
            "exact",
            ["consciousness", "hull"],
            False,
        ),
        # Empathy WHY
        (
            "empathy why",
            "Why does empathy matter?",
            "synthesize",
            ["empathy", "coherent"],
            False,
        ),
        # Collide / controlled docking
        (
            "collide boat",
            "When to collide boat?",
            "synthesize",
            ["dock", "crash", "calm"],
            False,
        ),
        # Entrainment condition
        (
            "no entrainment",
            "What happens if there is no entrainment at all?",
            "exact",
            ["fragment", "collapse"],
            False,
        ),
        # Color refuse — no locked residual about the colour of HyperSeed binary
        (
            "color refuse",
            "What color is the HyperSeed binary?",
            "exact",
            [],
            True,  # must be empty
        ),
    ]

    for label, query, mode, required, must_empty in battery:
        answer = _project(query, mode)
        answer_lower = answer.lower()
        print(f"\n  [{label}]")
        print(f"    query:  {query!r}  ({mode})")
        print(f"    answer: {answer[:120]!r}")

        if must_empty:
            _assert(
                f"{label}: returns empty (no colour residual)",
                not answer.strip(),
                f"got: {answer[:80]!r}",
            )
        else:
            for kw in required:
                _assert(
                    f"{label}: answer contains '{kw}'",
                    kw.lower() in answer_lower,
                    f"answer={answer[:120]!r}",
                )

    # Extra: ensure HyperSeed answer is NOT the ghost-tax orphan
    print("\n  [orphan check: HyperSeed answer must not be only about Ghost Tax]")
    hs_answer = _project("What is a HyperSeed?", "exact").lower()
    orphan_only = "ghost tax" in hs_answer and "hyperseed" not in hs_answer
    _assert(
        "HyperSeed answer contains 'hyperseed' (not just ghost-tax orphan)",
        not orphan_only,
        f"answer={hs_answer[:120]!r}",
    )


def main() -> None:
    global BASE_URL
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    BASE_URL = args.url.rstrip("/")

    print(f"\nTarget: {BASE_URL}")

    # Verify server reachability
    try:
        status = _get("/status")
        print(f"Server version: {status.get('version')}  locked: {status.get('void', {}).get('locked', '?')}")
    except urllib.error.URLError as exc:
        print(f"ERROR: cannot reach server at {BASE_URL}: {exc}")
        sys.exit(1)

    step_clear()
    step_inject()
    step_verify_no_orphans()
    step_acceptance_battery()

    print("\n" + "─" * 55)
    if _failures:
        print(f"Result: {len(_failures)} FAILURE(s):")
        for f in _failures:
            print(f"  • {f}")
        sys.exit(1)
    else:
        print("Result: all checks passed ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
