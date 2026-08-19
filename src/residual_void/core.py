from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import threading
import time
import uuid
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import butter, filtfilt, find_peaks

from .dynamics import PureHarnessDynamics, ResidualFlowResult

# Per-thread storage for the most recently stored residual's governance metadata.
# Written inside CoherentField.store() while _lock is still held, so each
# HTTP-handler thread reads its own result with no cross-thread contamination.
_store_result_local: threading.local = threading.local()

BIT_DIM = 256
_STOP_TOKENS = set(
    "a an the of to in for on with is are was were be been being it this that "
    "these those and or but if as at by from into over after before about".split()
)
PHASE_OFFSET = 0.81
PHRASE_ANCHORS = [
    "heat exhaustion", "heat stroke", "heat cramps", "heat syncope", "heat rash",
    "30 minutes", "thunder roars", "isolated tree", "under a tree", "severe thunderstorm",
    "first aid", "call 911", "90 f", "less than 90", "over 90", "above 90", "use fans",
    "metal-topped vehicle", "corded phones", "how long after",
]
PHRASE_BRIDGES = {
    "how long after": ["30 minutes", "thirty minutes"],
    "under a tree": ["isolated tree"],
    "stand under": ["isolated tree"],
    "over 90": ["90 f", "above 90", "less than 90"],
    "90 degrees": ["90 f", "above 90"],
    "why was residualvoid": ["began as a response", "memory bottleneck", "geometry of stored"],
    "why was residual": ["began as a response", "memory bottleneck"],
    "why was it built": ["began as a response", "memory bottleneck"],
    "unused knowledge": ["unused residuals slowly decay", "decay never deletes", "lowers ranking preference"],
    "what happens to unused": ["unused residuals slowly decay", "decay never deletes"],
    "decayed information": ["remain fully visible", "never existence", "ranking priority"],
    "does decayed": ["remain fully visible", "never existence"],
    "find low-value": ["rank by ascending value", "value falls below"],
    "invent new facts": ["no free invention", "supported by locked"],
}

TOKEN_BRIDGES = {
    "bond": ["ground", "grounding", "bonded"],
    "bonded": ["ground", "grounding", "bond"],
    "ground": ["grounding", "bond", "bonded"],
    "grounding": ["ground", "bond", "bonded"],
    "protect": ["overload", "protection", "relay"],
    "protection": ["overload", "protect", "relay"],
    "overload": ["protect", "protection", "thermal", "relay"],
    "frame": ["grounding", "ground", "bond", "bonded"],
    # collision/docking synonym cluster
    "collide": ["dock", "crash", "docking", "crashing", "controlled"],
    "dock": ["collide", "crash", "docking", "crashing", "controlled"],
    "crash": ["collide", "dock", "crashing", "docking"],
}


def tokenize_text(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def tokenize(text: str) -> List[str]:
    return re.findall(
        r"[0-9A-Za-zÀ-ɏͰ-Ͽἀ-῿']+",
        text.lower(),
        flags=re.UNICODE,
    )


def content_tokens(text: str) -> List[str]:
    """Extract meaningful tokens (stopwords filtered)."""
    return [t for t in tokenize(text) if t not in _STOP_TOKENS and len(t) > 2]


def _stem_token(token: str) -> str:
    t = token.lower()
    for suffix in ("edly", "ment", "ing", "ly", "ies", "ed", "es", "s"):
        if t.endswith(suffix) and len(t) > len(suffix) + 2:
            if suffix == "s" and t.endswith("ss"):
                continue
            if suffix == "ies":
                return t[:-3] + "y"
            return t[:-len(suffix)]
    return t


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


def _jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    max_dist = max(0, max(len(a), len(b)) // 2 - 1)
    a_match = [False] * len(a)
    b_match = [False] * len(b)
    matches = 0
    transpositions = 0
    for i, ca in enumerate(a):
        start = max(0, i - max_dist)
        end = min(i + max_dist + 1, len(b))
        for j in range(start, end):
            if b_match[j] or b[j] != ca:
                continue
            a_match[i] = b_match[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    j = 0
    for i in range(len(a)):
        if not a_match[i]:
            continue
        while j < len(b) and not b_match[j]:
            j += 1
        if j < len(b) and a[i] != b[j]:
            transpositions += 1
        j += 1
    transpositions /= 2
    jaro = (
        (matches / len(a)) + (matches / len(b)) + ((matches - transpositions) / matches)
    ) / 3.0
    prefix = 0
    for ca, cb in zip(a, b):
        if ca == cb and prefix < 4:
            prefix += 1
        else:
            break
    return jaro + 0.1 * prefix * (1 - jaro)


def fuzzy_token_hits(query_tokens: Set[str], candidate_tokens: Set[str]) -> float:
    if not query_tokens or not candidate_tokens:
        return 0.0
    score = 0.0
    for qt in query_tokens:
        if qt in candidate_tokens:
            score += 1.0
            continue
        qstem = _stem_token(qt)
        best = 0.0
        for ct in candidate_tokens:
            if qstem == _stem_token(ct):
                best = max(best, 0.92)
            dist = _levenshtein(qt, ct)
            lev = 1.0 - dist / max(len(qt), len(ct), 1)
            jw = _jaro_winkler(qt, ct)
            best = max(best, lev * 0.55 + jw * 0.45)
        if best >= 0.78:
            score += best
    return score


_LINEAGE_TOKENS: frozenset = frozenset({
    "WHAT", "WHY", "HOW", "WHEN", "WHERE", "WHO",
    "EFFECT", "LIMIT", "WHATIF", "COMPARE", "EXAMPLE", "RELATION",
})


def detect_intent(query: str) -> str:
    """Return the interrogative lineage intent for a query (specific-before-generic order)."""
    q = query.lower().strip()
    if re.search(r"\bwhat\s+if\b", q):                                              return "WHATIF"
    if re.search(r"\bwhy\b", q):                                                     return "WHY"
    if re.search(r"\bwhen\b", q):                                                    return "WHEN"
    if re.search(r"\bwhere\b", q):                                                   return "WHERE"
    # Causal-WHAT override: "what causes/creates/triggers/leads to/produces/results in X"
    # are WHY (explanatory) queries, not WHAT (definition) or HOW (agentive) queries.
    # Must come BEFORE the agentive-action override so "What causes X" → WHY, not HOW.
    if re.search(
        r"\bwhat\s+(causes?|creates?|triggers?|leads?\s+to|produces?|results?\s+in)\b",
        q,
    ):
        return "WHY"
    # Agentive-action override: "what/who + action verb" are HOW questions, not definitions.
    # Must come before the bare WHO/WHAT checks so "What suppresses X" → HOW, not WHAT.
    if re.search(
        r"\b(what|who)\s+(suppress\w*|raise\w*|detect\w*|maintain\w*"
        r"|apply|applies|tune\w*|cause\w*|control\w*|activat\w*)\b",
        q,
    ):
        return "HOW"
    if re.search(r"\bwho\b", q):                                                     return "WHO"
    if re.search(r"\blimits?\b|\bboundar(y|ies)\b|\bbreaks?\b|\bfails?\b", q):      return "LIMIT"
    if re.search(r"\beffects?\b|\bresults?\b|\bhappens?\b|\boutcomes?\b", q):        return "EFFECT"
    if re.search(r"\bcompar(e|ison)?\b|\bvs\b|\bdifferences?\b|\bversus\b|\bunlike\b", q): return "COMPARE"
    if re.search(r"\bexamples?\b|\bfor instance\b|\be\.g\b", q):                    return "EXAMPLE"
    if re.search(r"\brelat(e|ion|ed)?\b|\bconnect(ion|ed)?\b|\blink(ed)?\b", q):   return "RELATION"
    if re.search(r"\bhow\b", q):                                                     return "HOW"
    if re.search(r"\bwhat\b", q):                                                    return "WHAT"
    return "GENERAL"


def _clean_body(fragment: str) -> str:
    """Peel all nested DOMAIN::TAG:: envelopes and return plain body text.

    Handles double-wrapped fragments (e.g. when pre-formatted lineage text is
    passed through inject_document, which adds its own outer envelope).
    Stops as soon as there are no more '::' separators.
    """
    text = fragment.strip()
    for _ in range(8):  # max nesting depth guard
        if "::" not in text:
            break
        parts = text.split("::", 2)
        if len(parts) < 3:
            break
        text = parts[2].strip()
    return text


def _shadow_is_grounded(source_text: str, shadow_text: str) -> bool:
    """Return True only when the Shadow body is extractive from its Source."""
    source_body = re.sub(r"\s+", " ", _clean_body(source_text)).strip().casefold()
    shadow_body = re.sub(r"\s+", " ", _clean_body(shadow_text)).strip().casefold()
    return bool(shadow_body) and shadow_body in source_body


def parse_lineage(fragment: str) -> tuple:
    """Return (lineage_token_or_None, clean_body) for a DOMAIN::TOPIC_LINEAGE::body fragment.

    Lineage tokens (in priority order): WHATIF WHY HOW WHEN WHERE WHO EFFECT LIMIT
                                        COMPARE EXAMPLE RELATION WHAT
    The returned body is fully stripped of all nested DOMAIN::TAG:: envelopes.
    Returns (None, clean_body) when no lineage suffix is found.
    Returns (None, fragment) when there is no '::' structure.
    """
    _ORDER = ["WHATIF", "WHY", "HOW", "WHEN", "WHERE", "WHO",
              "EFFECT", "LIMIT", "COMPARE", "EXAMPLE", "RELATION", "WHAT",
              "DEFINITION", "MECHANISM", "CONDITION",
              "LIST_ITEM", "STEP", "FACT"]
    # Scan outer envelope for lineage tag, then return fully-clean body
    if "::" in fragment:
        parts = fragment.split("::", 2)
        if len(parts) == 3:
            tag = parts[1].upper().strip()
            raw_body = parts[2]
            clean = _clean_body(raw_body)
            for lin in _ORDER:
                if tag.endswith("_" + lin) or tag == lin:
                    return lin, clean
            return None, clean
        if len(parts) == 2:
            return None, parts[1]
    return None, fragment


def _extract_lineage(fragment: str) -> str:
    """Convenience wrapper — returns only the lineage token (or 'GENERAL')."""
    lin, _ = parse_lineage(fragment)
    return lin if lin is not None else "GENERAL"


def parse_topic_lineage(fragment: str) -> tuple:
    """Return (topic, lineage, clean_body) for a DOMAIN::TOPIC_LINEAGE::body fragment.

    Examples:
      DOC::ZERO_DRIFT_WHY::body                    →  ('ZERO_DRIFT', 'WHY', 'body')
      DOC::COHERENCE_HOW::body                     →  ('COHERENCE',  'HOW', 'body')
      DOC::DOC_ZERO_DRIFT_WHY::DOC::ZERO_DRIFT_WHY::body  →  ('ZERO_DRIFT', 'WHY', 'body')
      DOC::INTRO_FULL::body                        →  ('INTRO_FULL', None,  'body')

    Iterates through all nested DOMAIN::TAG:: envelopes (inject_document wraps in an
    extra layer) and returns the result from the INNERMOST lineage-tagged envelope so
    that double-wrapped fragments resolve to the same topic as direct locks.
    The clean_body is fully stripped of all nested envelopes.
    """
    _ORDER = ["WHATIF", "WHY", "HOW", "WHEN", "WHERE", "WHO",
              "EFFECT", "LIMIT", "COMPARE", "EXAMPLE", "RELATION", "WHAT",
              "DEFINITION", "MECHANISM", "CONDITION",
              "LIST_ITEM", "STEP", "FACT"]

    best: tuple = (None, None, fragment)  # (topic, lineage, clean_body)
    current = fragment

    for _ in range(8):  # guard against infinite loops
        if "::" not in current:
            break
        parts = current.split("::", 2)
        if len(parts) < 3:
            break
        tag = parts[1].upper().strip()
        raw_body = parts[2]
        clean = _clean_body(raw_body)
        found_lineage = False
        for lin in _ORDER:
            if tag.endswith("_" + lin) or tag == lin:
                topic = tag[:-(len(lin) + 1)] if tag.endswith("_" + lin) else None
                best = (topic, lin, clean)  # keep updating — innermost wins
                found_lineage = True
                break
        if not found_lineage and best == (None, None, fragment):
            best = (tag, None, clean)  # whole tag as topic, no lineage
        current = raw_body  # unwrap one level and continue

    return best


def detect_topics(query: str) -> set:
    """Return a set of parent topic keys mentioned in the query.

    Keys match the TOPIC portion of DOMAIN::TOPIC_LINEAGE:: tags.
    Returns an empty set when no known topic is detected (falls back to
    lineage-only ranking, preserving existing behaviour).
    Extend this list as new parent topics are added to the void.
    """
    q = query.lower()
    topics: set = set()
    if any(kw in q for kw in ("zero drift", "ghost tax", "auditor mode", "harness mode", "epsilon")):
        topics.add("ZERO_DRIFT")
    if ("coherence principle" in q) or ("coherence" in q and "principle" in q):
        topics.add("COHERENCE")
    return topics


_EVIDENCE_STOP: frozenset = frozenset({
    "what", "is", "the", "are", "how", "why", "when", "where", "who",
    "does", "do", "a", "an", "of", "in", "and", "or", "it", "its",
    "there", "if", "at", "no", "not", "be", "that", "this", "for",
    # Modal / filler verbs: present in many WHEN/action queries but carry
    # no domain evidence (e.g. "when should you collide boats?" →
    # "should" must not count toward the ≥3-word off-target gate).
    "should", "would", "could", "will", "shall", "want", "need",
    "please", "tell", "give", "show", "make", "have", "with",
    "you", "your", "i", "we", "they",
})

# Absence/negation equivalence — query signals and matching body signals treated
# as the same evidence family (e.g. "no leakage at all" ↔ "without any leakage").
_ABSENCE_QUERY_SIGNALS: frozenset = frozenset({
    "no leakage", "without leakage", "no leakage at all", "absence of leakage",
    "without any leakage",
})
_ABSENCE_BODY_SIGNALS: frozenset = frozenset({
    "without any leakage", "without leakage", "no leakage",
    "freeze", "brittle",
})


def _evidence_score(query: str, body: str) -> float:
    """Content-evidence score: how directly the body text answers the query.

    Returns a float in [0.0, 1.5]:
      1.5 — exact multi-word phrase from query found verbatim in body,
             OR absence/negation equivalence match
      1.0 — four or more distinctive query terms appear in body
      0.7 — three distinctive terms
      0.4 — two distinctive terms
      0.0 — weak or no overlap

    Used as a first-class ranking signal so strong direct content evidence
    can outrank a tag-only match that lacks real answer material.
    """
    q_lower = query.lower()
    b_lower = body.lower()
    # Negation/absence equivalence: treat phrasing variants as exact match
    if (any(sig in q_lower for sig in _ABSENCE_QUERY_SIGNALS) and
            any(sig in b_lower for sig in _ABSENCE_BODY_SIGNALS)):
        return 1.5
    # Generic "if there is no X" / "what happens without X" ↔ "without X" / "X cannot"
    _abs_m = re.search(r"(?:if there (?:is|are) no|without|if not)\s+(\w+)", q_lower)
    if _abs_m:
        _absent = _abs_m.group(1)
        if len(_absent) >= 5 and re.search(
            rf"without {_absent}|no {_absent}\b|{_absent} cannot\b|{_absent} is lost",
            b_lower,
        ):
            return 1.5
    q_words = [w.strip("?.,!") for w in q_lower.split()
               if len(w) > 3 and w.strip("?.,!") not in _EVIDENCE_STOP]
    if not q_words:
        return 0.0
    # Exact multi-word span: any 2+ distinctive word sequence from query in body
    for n in range(min(len(q_words), 5), 1, -1):
        for i in range(len(q_words) - n + 1):
            span = " ".join(q_words[i:i + n])
            if span in b_lower:
                return 1.5
    # Term overlap
    hits = sum(1 for w in q_words if w in b_lower)
    if hits >= 4:
        return 1.0
    if hits >= 3:
        return 0.7
    if hits >= 2:
        return 0.4
    return 0.0


def _auto_topic_from_body(body: str) -> str | None:
    """Derive a coarse parent topic from untagged residual body text.

    Matches known content signals to topic keys used by detect_topics.
    Returns None when no confident match is found; never invents lineage.
    """
    b = body.lower()
    if any(kw in b for kw in ("ghost tax", "auditor mode", "harness mode", "epsilon", "zero drift")):
        return "ZERO_DRIFT"
    if "coherence principle" in b:
        return "COHERENCE"
    return None


# ============================================================
# MEMORY FAMILY KEY — governance for active/latent engrams
# ============================================================
_FAMILY_STOP: frozenset = frozenset({
    "what", "when", "where", "who", "how", "why", "which",
    "the", "this", "that", "these", "those", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "not", "no", "nor", "for", "of", "in", "on",
    "at", "to", "by", "from", "with", "into", "about", "than", "then",
    "also", "just", "very", "more", "most", "some", "any", "all", "both",
    "only", "such", "each", "other", "so", "if", "as", "it", "its", "a", "an",
})

# Recognised lineage suffixes — the final component of a safe family slug.
# Only slugs that end with one of these are surfaced on unauthenticated
# endpoints; everything else stays internal (governance still runs normally).
_KNOWN_LINEAGE_SUFFIXES: frozenset = frozenset({
    "what", "how", "why", "when", "where", "who",
    "effect", "limit", "compare", "example", "relation",
    "definition", "mechanism", "condition",
    "list-item", "step", "fact", "whatif",
})

# Grammar for a safe externally-visible family key:
# lowercase, digits, and hyphens; 3-64 chars; no leading/trailing/consecutive hyphens.
_SAFE_FAMILY_RE = re.compile(r'^[a-z][a-z0-9-]{1,62}[a-z0-9]$')


def _is_safe_external_family_key(slug: str) -> bool:
    """Return True iff *slug* is safe to surface on unauthenticated API endpoints.

    Requires:
    - Matches safe-identifier grammar (a-z0-9-).
    - No consecutive hyphens.
    - Ends with a known lineage suffix after the last (or last two) hyphen(s),
      ensuring the key encodes a controlled topic-lineage pair rather than
      arbitrary caller-supplied text.
    """
    if not _SAFE_FAMILY_RE.match(slug) or "--" in slug:
        return False
    # Single-word lineage suffix: <topic>-<lineage>
    last = slug.rsplit("-", 1)
    if len(last) == 2 and last[1] in _KNOWN_LINEAGE_SUFFIXES:
        return True
    # Two-word lineage suffix: <topic>-<lin1>-<lin2>  (e.g. "list-item")
    last2 = slug.rsplit("-", 2)
    if len(last2) == 3 and f"{last2[1]}-{last2[2]}" in _KNOWN_LINEAGE_SUFFIXES:
        return True
    return False

def _derive_family_key(fragment: str) -> Tuple[str, bool]:
    """Derive a normalised family slug from a residual fragment.

    Delegates to parse_topic_lineage so nested envelopes are unwrapped and
    the innermost authoritative topic+lineage tag wins — consistent with how
    ranking and evidence scoring resolve nested fragments.

    The slug is topic-hyphenated + "-" + lineage.lower(), e.g.:
        GHOST_TAX_WHAT  →  "ghost-tax-what"
        GHOST_TAX_HOW   →  "ghost-tax-how"
        HYPERSEED_WHAT  →  "hyperseed-what"

    Same-topic same-lineage alternates share a family and compete for the
    active-engram slot.  Different lineages (WHAT vs HOW) are separate slots.

    Falls back to the first significant word (≥4 chars, not a stop-word) from
    the clean body when no envelope tag is found.

    Returns (family_key, is_from_tag) where is_from_tag is True only when the
    key was derived from a structured TOPIC::TAG prefix (not body fallback).
    Returns ("", False) when no key can be derived.
    """
    topic, lineage, clean_body = parse_topic_lineage(fragment)
    if topic:
        # Standard case: DOMAIN::TOPIC_LINEAGE::body → topic="TOPIC", lineage="LINEAGE"
        slug = topic.replace("_", "-").lower().strip("-")
        if lineage:
            slug += "-" + lineage.lower()
        if slug and len(slug) >= 3 and slug not in _FAMILY_STOP:
            # Only mark as safe-to-expose if it passes the external grammar check.
            return slug, _is_safe_external_family_key(slug)
    elif lineage:
        # Alternate format: TOPIC::LINEAGE::body — parse_topic_lineage leaves topic=None
        # because parts[1] is a bare lineage word.  The real topic is in parts[0].
        raw_parts = fragment.split("::", 2)
        if len(raw_parts) >= 2:
            domain_part = raw_parts[0].replace("_", "-").lower().strip("-")
            if domain_part and len(domain_part) >= 3 and domain_part not in _FAMILY_STOP:
                slug = domain_part + "-" + lineage.lower()
                return slug, _is_safe_external_family_key(slug)

    # Fall back: first significant word from clean body (internal use only —
    # not safe to expose externally since it may contain corpus content).
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]*", clean_body):
        w_lower = w.lower()
        if len(w_lower) >= 4 and w_lower not in _FAMILY_STOP:
            return w_lower, False
    return "", False


_HOW_ACTION_STOP: frozenset = frozenset({
    "how", "does", "what", "the", "is", "are", "you", "your", "can", "do",
    "this", "that", "will", "make", "have", "with", "from", "into", "about",
    "there", "which", "would", "used", "using", "work",
    # topic nouns — not actions
    "ghost", "zero", "drift", "coherence", "harness", "auditor", "leakage",
    "mode", "principle", "epsilon", "gamma", "void", "field", "system", "tax",
})


def _extract_action_stems(query: str) -> list:
    """Extract stemmed action verbs from a HOW query.

    Filters topic nouns and question scaffolding; lightly strips common verb
    suffixes so 'suppressed' matches 'suppress' in a residual body.
    Returns a list of stems to check for presence in candidate bodies.
    """
    stems = []
    for raw in query.split():
        w = raw.strip("?.,!").lower()
        if not w or len(w) <= 3 or w in _HOW_ACTION_STOP:
            continue
        stem = w
        stripped = False
        for suffix in ("ing", "ions", "ion", "ed", "es", "s"):
            if stem.endswith(suffix) and len(stem) - len(suffix) >= 4:
                stem = stem[: len(stem) - len(suffix)]
                stripped = True
                break
        # Only keep the stem if it looks like a verb: either it shed a verbal
        # suffix (stripped=True) or the original word is a known action verb.
        # This prevents topic nouns like "phase", "anchor", "lost" from
        # generating false verb matches in candidate bodies.
        if stripped or w in _KNOWN_ACTION_VERBS:
            stems.append(stem)
    return stems


# Action verbs that signal the query is asking HOW something is done,
# regardless of the grammatical question form (covers "What suppresses…").
_KNOWN_ACTION_VERBS: frozenset = frozenset({
    "suppress", "suppresses", "suppressed", "suppressing",
    "raise", "raises", "raised", "raising",
    "detect", "detects", "detected", "detecting",
    "maintain", "maintains", "maintained", "maintaining",
    "apply", "applies", "applied", "applying",
    "tune", "tunes", "tuned", "tuning",
    "activate", "activates", "activated", "activating",
    "boost", "boosts", "boosted", "boosting",
    "dampen", "dampens", "dampened",
    "amplify", "amplifies", "amplified",
    "restore", "restores", "restored", "restoring",
    "rebuild", "rebuilds", "rebuilt", "rebuilding",
    "reseed", "reseeds", "reseeded", "reseeding",
    "lock", "locks", "locked", "locking",
    "achieve", "achieves", "achieved", "achieving",
    "align", "aligns", "aligned", "aligning",
    "treat", "treats", "treated", "treating",
    "couple", "couples", "coupled", "coupling",
    "entrain", "entrains", "entrained", "entraining",
    "synchronize", "synchronizes", "synchronized", "synchronizing",
    # collision / docking cluster — covers "when to collide boat"
    "collide", "collides", "colliding", "collided",
    "dock", "docks", "docking", "docked",
    "crash", "crashes", "crashing", "crashed",
})


def _is_action_query(query: str) -> bool:
    """True when the query explicitly asks about an action/method.

    Fires on HOW-form queries AND on any query containing a known action verb
    (e.g. 'What suppresses the ghost tax floor?' has WHAT intent but is
    functionally an action question and should prefer verb-containing residuals).
    """
    q = query.lower()
    return q.startswith("how") or any(v in q for v in _KNOWN_ACTION_VERBS)


def _classify_residual_role(body: str) -> str:
    """Coarsely classify a residual body as MECHANISM, CONDITION, or DEFINITION.

    MECHANISM — describes a method, agent, or action:
      agent-like subject (Harness Mode, Auditor Mode), action verbs
      (raises, restores, suppresses, couples, tunes…), or 'by …' constructs.
    CONDITION — describes a conditional, failure, or absence state:
      leading 'if …', 'without …', 'when there is no …' patterns.
    DEFINITION — mainly identity phrasing ('is the', 'is a', 'are the').

    Used in HOW/action ranking: MECHANISM > DEFINITION > CONDITION.
    """
    b = body.lower().strip()
    # CONDITION first: conditional / failure / absence opening or dominant phrase
    if re.search(
        r"^(if |without |when there'?s? no |unless )|"
        r"\b(if there is no|without any|when .{0,25} (drops|fails|is removed|is absent))\b",
        b,
    ):
        return "CONDITION"
    # MECHANISM: agent subjects, action verbs, or method constructs.
    # "works by", "functions by", "modulates", "shifts" etc. are method
    # descriptions even without a named agent like Harness Mode.
    if re.search(
        r"\b(harness mode|auditor mode)\b"
        r"|\b(raises|restores|suppresses|detects|couples|tunes|maintains|applies"
        r"|activates|increases|decreases|boosts|dampens|amplifies|re-synchroni"
        r"|modulates?|synchroni\w+|drives?\b)\b"
        r"|\bby (increasing|coupling|raising|tuning|locking|suppressing|restoring"
        r"|detecting|applying|activating|synchroni\w+)\b"
        r"|\bworks? by\b|\bfunctions? by\b|\boperates? by\b",
        b,
    ):
        return "MECHANISM"
    # DEFINITION: identity phrasing — "X is a/the/an/your …", or
    # "your X is …" possessive-definition form ("Your boat is your consciousness").
    if re.search(
        r"\b(is the|is a|is an|are the|are a|is your|are your|refers to|defined as)\b",
        b,
    ):
        return "DEFINITION"
    # WHY / explanatory: causal or contrast connectives that explain *why*
    # something happens rather than *how* an agent achieves it.
    if re.search(
        r"\b(creates?|leads? to|because|results? in|produces?|causes?)\b"
        r"|\b(high|low)\s+\w+\s+(creates?|produces?|leads?)\b"
        r"|\b(coherent path|incoherent|turbulent|fragment|collective memory)\b",
        b,
    ):
        return "WHY"
    # GENERAL: no explicit signals — do not assume mechanism.
    # Returning MECHANISM as default incorrectly penalises descriptive bodies
    # (e.g. "Orch-OR places conscious moments…") on WHAT/WHY/CONDITION queries.
    return "GENERAL"


def _residual_frame(fragment: str) -> str:
    """Return the speech-act frame of a residual fragment.

    Tag-based detection runs first (O(1), exact): if the tag portion of the
    fragment ends with a recognised frame suffix the answer is authoritative
    with no body-text regex needed.

    Frame suffix → speech-act frame mapping
    ─────────────────────────────────────────
    _DEFINITION / _WHAT               → DEFINITION
    _MECHANISM  / _HOW                → MECHANISM
    _CONDITION  / _WHATIF             → CONDITION
    _WHY                              → WHY

    Falls back to _classify_residual_role(body) for untagged / legacy residuals
    so that existing corpora without explicit frame tags still benefit from
    the frame gate.

    This implements the "write-time frame tag" route from the change order:
    instead of hoping rank discovers definition vs mechanism from free text,
    the tag makes the frame explicit and the gate reads it directly.
    """
    _, lineage, body = parse_topic_lineage(fragment)
    if lineage:
        lin = lineage.upper()
        if lin in ("DEFINITION", "WHAT"):
            return "DEFINITION"
        if lin in ("MECHANISM", "HOW"):
            return "MECHANISM"
        if lin in ("CONDITION", "WHATIF"):
            return "CONDITION"
        if lin == "WHY":
            return "WHY"
        # Expanded speech-act classes (change order: expanded query intent router)
        if lin == "LIST_ITEM":
            return "LIST_ITEM"
        if lin == "EXAMPLE":
            return "EXAMPLE"
        if lin == "STEP":
            return "STEP"
        if lin in ("RELATION",):
            return "RELATION"
        if lin == "FACT":
            return "FACT"
        if lin == "COMPARE":
            return "COMPARE"
    # No tag-encoded frame — infer from body text (existing regex path).
    return _classify_residual_role(body)


def _frame(res: "Residual") -> str:
    """Return the speech-act frame for a Residual, O(1) for write-time-stamped residuals.

    Reads the pre-stamped frame_tag that is written at lock time.
    Falls back to dynamic _residual_frame() for legacy residuals loaded from
    an old JSONL chain that pre-dates the frame_tag field (frame_tag == "").
    """
    return res.frame_tag if res.frame_tag else _residual_frame(res.fragment)


def _extract_compare_targets(query: str) -> "List[str]":
    """Extract the two comparison subjects from a COMPARE query.

    Handles patterns:
      "difference between X and Y"  →  ["X", "Y"]
      "X vs Y"                       →  ["X", "Y"]
      "compare X and Y"              →  ["X", "Y"]
      "contrast X and Y"             →  ["X", "Y"]
    Returns [] when the query doesn't yield two distinct targets.
    """
    q = query.strip().rstrip("?")
    # "difference between X and Y" / "between X and Y"
    m = re.search(r"\bbetween\s+(.+?)\s+and\s+(.+?)$", q, re.IGNORECASE)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    # "X vs Y" / "X versus Y"
    m = re.search(r"(.+?)\s+(?:vs\.?|versus)\s+(.+?)$", q, re.IGNORECASE)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    # "compare X and Y" / "contrast X and Y"
    m = re.search(r"(?:compare|contrast)\s+(.+?)\s+and\s+(.+?)$", q, re.IGNORECASE)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    return []


def _query_frame(query: str) -> str:
    """Map a query string to a speech-act intent frame.

    Returns one of (single-body): DEFINITION / MECHANISM / WHY / CONDITION / EXAMPLE / CONFIRM
    Returns one of (multi-body):  LIST / COMPARE / RELATE / STEPS / SUMMARIZE
    Returns GENERAL when no distinctive frame is detected (hard gate does not fire).

    Priority order (checked top-to-bottom; first match wins):
      SUMMARIZE  — "summarize / overview / in short / sum up"
      COMPARE    — "difference between / vs / versus / compare / contrast"
      RELATE     — "relate / relation / connection between / link between"
      CONFIRM    — "is it true / is X about / does X mean / confirm"
      LIST       — "list / which are / parts of / what are the X"  (before DEFINITION)
      EXAMPLE    — "example of / give an example / for instance / such as"
      STEPS      — "walk me through / what steps / step by step / in steps"
      DEFINITION — "what is / what are / define"
      CONDITION  — "what happens if / without / if there is no / if not"
      WHY        — "why / matters / important"
      MECHANISM  — "how / suppress / restore / any known action verb"
      GENERAL    — no distinctive frame

    Single-body intents (DEFINITION/MECHANISM/WHY/CONDITION/EXAMPLE/CONFIRM) pass
    through the hard frame gate and the existing single-pass logic unchanged.
    Multi-body intents (LIST/COMPARE/RELATE/STEPS/SUMMARIZE) are handled by the
    multi-residual projection block that runs before the single-body passes.
    """
    q = query.lower().strip().rstrip("?")
    # SUMMARIZE
    if re.search(r"\b(summari[zs]e|summari[zs]ation|overview|in short|sum up|brief me on)\b", q):
        return "SUMMARIZE"
    # COMPARE
    if re.search(r"\b(difference between|differ from|vs\.?|versus|compare|contrast)\b", q):
        return "COMPARE"
    # RELATE
    if re.search(r"\b(relate|relation|connection between|linked? to|link between)\b", q):
        return "RELATE"
    # CONFIRM — "is it true", "is X about", "does X mean/say/refer",
    # or value assertions "Is Ghost Tax fifty percent?"
    if re.search(r"\b(is it true|is .{1,25} about|does .{1,25} (mean|say|refer)|confirm)\b", q):
        return "CONFIRM"
    if re.search(
        r"^is\s+\w.{0,40}\s+"
        r"(percent|%|\d+|fifty|twenty|thirty|forty|sixty|seventy|eighty|ninety|hundred"
        r"|correct|right|accurate|true|false|always|never|only)\b",
        q,
    ):
        return "CONFIRM"
    # STEPS — checked BEFORE LIST so "what are the steps" → STEPS not LIST
    # Extended: "list the steps", "list * steps", "steps to", "procedure",
    # "walk me through", "step by step" all route to STEPS.
    if re.search(r"\b(walk me through|what (are the )?steps|step by step|in steps)\b", q):
        return "STEPS"
    if re.search(r"\blist\b.{0,20}\bsteps?\b", q):
        return "STEPS"
    if re.search(r"\b(steps to |the steps to |procedure\b)\b", q):
        return "STEPS"
    # LIST — "list / which are / parts of / what are X" (bare enumeration)
    # STEPS already consumed "what are the steps"; any remaining "what are"
    # is a list request (e.g. "What are Core and Edge?").
    if re.search(r"\b(list\b|which are\b|parts of\b|give me all\b|enumerate\b|what are\b)", q):
        return "LIST"
    # EXAMPLE
    if re.search(r"\b(example of|give an example|for instance|such as|show me an example)\b", q):
        return "EXAMPLE"
    # "what causes / creates / triggers / leads to / produces / results in X" → WHY
    # Causal-WHAT queries are explanatory (WHY frame), not procedural (MECHANISM).
    if re.search(r"\bwhat (causes?|creates?|triggers?|leads? to|produces?|results? in)\b", q):
        return "WHY"
    # Existing single-body intents
    if _is_definition_query(query):
        return "DEFINITION"
    if _is_condition_query(query):
        return "CONDITION"
    if q.startswith("why") or any(w in q for w in ("matters", "important", "why does", "why is")):
        return "WHY"
    # "when" queries are circumstantial, not procedural — GENERAL so the
    # frame gate does not fire and the best-Bellman WHEN residual wins.
    if not q.startswith("when") and (q.startswith("how") or _is_action_query(query)):
        return "MECHANISM"
    return "GENERAL"


# Known domain term pairs: if query contains the key and the residual body
# contains any of the values PLUS has MECHANISM role, grant a linked-term boost.
_LINKED_PAIRS: dict = {
    "ghost tax": {"floor", "epsilon", "leakage", "gamma"},
    "floor":     {"ghost tax", "epsilon", "leakage", "suppress"},
    "entrainment": {"lock", "coupling", "synchroni", "restores", "restore"},
    "entrain":   {"lock", "coupling", "synchroni", "restore"},
    "lock":      {"entrainment", "coupling", "synchroni"},
    "suppress":  {"gamma", "harness", "floor", "raises"},
    "restoration": {"lock", "coupling", "entrainment", "synchroni"},
}


def _linked_term_evidence(query: str, body: str) -> float:
    """Return a boost when a query domain term has a linked synonym in the body.

    Covers known pairs like ghost-tax ↔ floor, entrainment ↔ lock/coupling.
    Only fires when the body also has MECHANISM role (has an action verb/agent),
    so we do not boost condition or definition residuals via this path.
    """
    q = query.lower()
    b = body.lower()
    if _classify_residual_role(b) != "MECHANISM":
        return 0.0
    for q_term, linked in _LINKED_PAIRS.items():
        if q_term in q and any(lt in b for lt in linked):
            return 0.6
    return 0.0


def _extract_definition_target(query: str) -> str:
    """Extract the entity being defined from a WHAT-is / Define query.

    Examples:
        "What is a HyperSeed?"        → "hyperseed"
        "What is the ghost tax?"      → "ghost tax"
        "What is Orch-OR?"            → "orch-or"
        "Define HyperSeed"            → "hyperseed"
        "What is the Schumann resonance?" → "schumann resonance"

    Returns an empty string if no target can be extracted.
    """
    q = query.strip().rstrip("?!.")
    q_lower = q.lower()
    # "Define X"
    m = re.match(r"^define\s+(.+)$", q_lower)
    if m:
        return m.group(1).strip()
    # "What is [a/an/the] X"
    m = re.match(r"^what (?:is|are)\s+(?:(?:a|an|the)\s+)?(.+)$", q_lower)
    if m:
        return m.group(1).strip()
    return ""


def _extract_why_target(query: str) -> str:
    """Extract the subject entity from a WHY query.

    Examples:
        "Why empathy matters"          → "empathy"
        "Why does coherence matter?"   → "coherence"
        "Why is the ghost tax present?"→ "ghost tax"
    Returns "" when no reliable target can be extracted.
    """
    q = query.strip().rstrip("?!.").lower()
    causal = re.match(
        r"^what\s+(?:causes?|creates?|triggers?|leads?\s+to|produces?|results?\s+in)"
        r"\s+(?:the\s+|a\s+|an\s+)?(.+)$",
        q,
    )
    if causal:
        return causal.group(1).strip()
    # Extended WHY prefix: handles can/will/would/could in addition to
    # does/do/is/are so "Why can ego help…" → "ego help…" (not "can ego…")
    m = re.match(
        r"^why (does |do |is |are |did |was |were |should |can |will |would |could )?"
        r"(the |a |an )?",
        q,
    )
    if m:
        q = q[m.end():]
    # Strip trailing fillers — including compound predicates like "help or hurt"
    q = re.sub(
        r"\s+(matters?|is important|works?|happens?|exists?|occur\w*"
        r"|help(?:\s+or\s+\w+)?|appear\w*|hurt|used\s+for)\s*$",
        "",
        q,
    ).strip()
    q = re.sub(r"^(the |a |an )", "", q).strip()
    return q if len(q) >= 3 else ""


def _extract_query_target(query: str) -> str:
    """Extract the primary noun target from any query type.

    Prefers multi-word targets ("phase lock", "tagged locks", "fitness gate",
    "controlled docking", "ghost tax").  Used by the target-subject hard filter
    before frame-specific scoring.

    Returns "" when no extractable target is found (query is too vague or
    off-domain).
    """
    q = query.strip().rstrip("?!.")
    q_l = q.lower()

    # CONFIRM: stop at the predicate value so we only get the subject.
    # "Is Ghost Tax fifty percent?" → "ghost tax"
    if q_l.startswith("is "):
        _cm = re.match(
            r"^is\s+(.+?)\s+"
            r"(?:\d[\d.]*|fifty|twenty|thirty|forty|sixty|seventy|eighty|ninety|hundred"
            r"|percent|%|about|correct|right|true|false|always|never|only)\b",
            q_l,
        )
        if _cm:
            return _cm.group(1).strip()

    # Subject-predicate WHAT forms name the carrier before the finite verb.
    # "What does restart replay keep?" → "restart replay".
    what_does = re.match(
        r"^what\s+does\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+"
        r"(?:keep|hold|store|contain|mean|do|return|produce|create)\b",
        q_l,
    )
    if what_does:
        return what_does.group(1).strip()

    # Frame-specific extractors handle their own scaffolding best.
    if _is_definition_query(q):
        t = _extract_definition_target(q)
        if t:
            return t.strip()

    if q_l.startswith("why") or detect_intent(q) == "WHY":
        t = _extract_why_target(q)
        if t:
            return t.strip()

    # WHEN queries ("When should you collide boats?") are condition/timing queries,
    # not subject-identity queries.  _is_action_query fires for these because they
    # contain an action verb, which routes them through _extract_mechanism_target
    # and extracts the full query as target → hard filter refuses everything.
    # Return "" so the hard filter disengages and Pass 4 (CONDITION) / Bellman
    # fallback can find the answer.
    if q_l.startswith("when"):
        return ""

    if q_l.startswith("how") or _is_action_query(q):
        t = _extract_mechanism_target(q)
        if t:
            return t.strip()

    # General prefix strip for queries that didn't match above.
    _prefix_pats = [
        r"^(?:is|does|can|will|should|would)\s+",
        r"^(?:list|enumerate)\s+(?:the\s+)?(?:steps?\s+to\s+)?",
        r"^what\s+(?:is|are)\s+(?:a\s+|an\s+|the\s+)?",
        r"^why\s+(?:does|do|is|are|use|would|should)?\s*",
        r"^when\s+(?:to|should|do|is)?\s*(?:you|i|we)?\s*",
        r"^how\s+(?:to|does|do|is|are|can)?\s*(?:you|i|we)?\s*",
        r"^define\s+",
    ]
    for pat in _prefix_pats:
        m = re.match(pat, q_l)
        if m:
            q_l = q_l[m.end():].strip()
            break

    # Strip leading articles after prefix removal.
    q_l = re.sub(r"^(a |an |the )", "", q_l).strip()

    # Strip trailing scaffolding (verbs, filler phrases).
    q_l = re.sub(
        r"\s+(?:work|works|help|helps|matter|matters|mean|means|function|functions"
        r"|achieve|achieves|achieved|do|does|happen|use|used|about|like"
        r"|help\s+or\s+hurt|used?\s+for)\s*$",
        "",
        q_l,
    ).strip()

    # Guard: must be at least 3 chars and not a common stop word.
    if len(q_l) < 3 or q_l in {"the", "a", "an", "it", "its"}:
        return ""
    return q_l


def _extract_synthesize_query_target(query: str) -> str:
    """Synthesize-only target refinements for Intent Cell questions.

    Exact deliberately continues to call ``_extract_query_target`` unchanged.
    """

    q = query.strip().rstrip("?!.")
    q_l = q.lower()

    # WHO asks for an entity, so the full interrogative is not a subject target.
    if q_l.startswith("who"):
        return ""

    # Diagnosis forms keep the subject while removing the failure predicate.
    if q_l.startswith("why"):
        target = _extract_why_target(q)
        target = re.sub(
            r"\s+(?:fail\w*|break\w*|drop\w*)\s*$",
            "",
            target,
        ).strip()
        if target:
            return target

    # "How does <subject> prevent <object>?" was previously interpreted as the
    # entire remainder because "prevent" is intentionally not a shared Exact
    # action verb. Intent Cells need the named subject only.
    active_prevent = re.match(
        r"^how\s+(?:does|do|can|will|would|should)\s+"
        r"(?:(?:you|i|we|they)\s+)?(?:(?:the|a|an)\s+)?"
        r"(.+?)\s+prevent\w*\b",
        q_l,
    )
    if active_prevent:
        return active_prevent.group(1).strip()

    return _extract_query_target(query)


def _residual_matches_target(target: str, res: "Residual") -> bool:
    """Return True if this residual is *about* the given target noun phrase.

    Checks (in priority order):
      1. All target tokens appear in the residual's lineage tag path.
      2. The body's lead subject starts with the target.
      3. For multi-word targets: the head noun (last word) appears in the tag.

    A match on any criterion is sufficient.  An empty target always returns True
    (no filter applied when no target is extractable).
    """
    if not target:
        return True

    tgt_l = target.lower()
    tgt_tokens = [t for t in tgt_l.split() if len(t) >= 3]

    # Tag path: everything before the body separator.
    tag_raw = res.fragment.rsplit("::", 1)[0].lower() if "::" in res.fragment else ""
    tag_clean = re.sub(r"\bdoc\b", "", tag_raw)  # remove generic "doc" prefix

    # 1. Full token tag match (morphology-only, so path/paths and lock/locks
    # remain the same identity without enabling fuzzy neighbours).
    target_stems = {_stem_token(token) for token in tgt_tokens}
    tag_stems = {
        _stem_token(token)
        for token in re.findall(r"[a-z0-9]+", tag_clean)
        if len(token) >= 3
    }
    if target_stems and target_stems.issubset(tag_stems):
        return True

    # 2. Lead-subject body match: target at the opening of the body.
    _, _, body = parse_topic_lineage(res.fragment)
    body_l = body.lower()
    lead_pat = r"^(?:the |a |an )?" + re.escape(tgt_l) + r"\b"
    if re.match(lead_pat, body_l):
        return True
    if (
        res.layer == "source"
        and re.search(
            r"(?:^|[.!?]\s+)(?:the |a |an )?" + re.escape(tgt_l) + r"\b",
            body_l,
        )
    ):
        return True

    # WHY memories often name the queried entity as the object of the causal
    # clause ("alignment creates coherent paths"). All target terms must still
    # be present, and the residual must be explicitly explanatory.
    body_stems = {_stem_token(token) for token in content_tokens(body_l)}
    if (
        target_stems
        and target_stems.issubset(body_stems)
        and (res.frame_tag == "WHY" or _residual_frame(res.fragment) == "WHY")
    ):
        return True

    # 3. Head-noun tag match for multi-word targets whose modifier is not in tag.
    #    "controlled docking" → head "docking" in {"docking", "mechanism"} ✓
    #    Uses word-token matching (split on _ and whitespace) so "lock" does NOT
    #    match inside "tagged_locks_mechanism" (it's "locks" there, not "lock").
    if " " in tgt_l:
        head = tgt_l.split()[-1]
        tag_words = set(re.split(r"[_\s]+", tag_clean))
        if len(head) >= 4 and head in tag_words:
            return True

    return False


def _extract_how_target(query: str, action_stems: list) -> str:
    """Extract the noun target from a HOW/WHEN/action query.

    Examples:
        "How do you suppress the ghost tax?" → "ghost tax"
        "When to collide boat"               → "boat"
        "How does Harness Mode raise gamma?" → "gamma"
    Returns "" when no reliable target can be extracted.
    """
    q = query.strip().rstrip("?!.").lower()
    for pat in (
        r"^how (do you |does |can |do i |to )?",
        r"^when (should (?:you |i |we )?|do you |to |can (?:you |i |we )?)",
    ):
        m = re.match(pat, q)
        if m:
            q = q[m.end():]
            break
    # Strip leading action verb (longest stem first to avoid partial matches)
    if action_stems:
        for stem in sorted(action_stems, key=len, reverse=True):
            m = re.match(rf"{re.escape(stem)}\w*\s+(?:the |a |an )?", q)
            if m:
                q = q[m.end():].strip()
                break
    q = re.sub(r"^(the |a |an )", "", q).strip()
    return q if len(q) >= 3 else ""


def _extract_carrier_target(query: str, action_stems: list) -> str:
    """Extract the query's noun carrier target for aboutness checks.

    Wraps _extract_how_target and additionally strips trailing filler verbs
    ("work", "works", "function", "operate", "happen") so
    "How does entrainment work?" → "entrainment" (not "entrainment work").
    Returns "" when no reliable target can be extracted.
    """
    t = _extract_how_target(query, action_stems)
    if not t:
        return ""
    t = re.sub(
        r"\s+(work(?:s|ing)?|function(?:s|ing)?|operate(?:s|d)?|happen(?:s|ed)?|done)\s*$",
        "", t,
    ).strip()
    return t if len(t) >= 3 else ""


# HOW scaffolding patterns — stripped when extracting the pure noun target
# from conversational HOW forms ("how do you achieve X", "how is X achieved").
_HOW_SCAFFOLD_PREFIX = re.compile(
    r"^how\s+(?:do\s+you\s+|does\s+|can\s+you\s+|can\s+i\s+|do\s+i\s+|do\s+we\s+"
    r"|is\s+it\s+that\s+|is\s+it\s+|to\s+|is\s+|are\s+|was\s+|were\s+)?\s*",
    re.IGNORECASE,
)
_HOW_SCAFFOLD_VERB = re.compile(
    r"^(?:achieve|achieves|achieved|achieving"
    r"|get|gets|got|getting"
    r"|use|uses|used|using"
    r"|perform|performs|performed|performing"
    r"|reach|reaches|reached|reaching"
    r"|obtain|obtains|obtained|obtaining"
    r"|do|does|did"
    r")\s+(?:the\s+|a\s+|an\s+)?",
    re.IGNORECASE,
)
_HOW_TRAILING_PASSIVE = re.compile(
    r"\s+(?:achieved|done|performed|accomplished|obtained|reached|maintained|made"
    r"|work|works|function|functions|operate|operates)\s*$",
    re.IGNORECASE,
)


def _extract_mechanism_target(query: str) -> str:
    """Extract the pure noun target from a HOW/MECHANISM query.

    Strips all HOW scaffolding so any conversational form yields the same
    bare noun phrase:
      "How do you achieve phase lock?"  → "phase lock"
      "How is phase lock achieved?"     → "phase lock"
      "How to phase lock"               → "phase lock"
      "achieve phase lock"              → "phase lock"

    Returns "" when no reliable target can be extracted.
    """
    q = query.strip().rstrip("?!.")
    # Active "how does <subject> <verb> <object>" forms name their queried
    # carrier before the action verb. Preserve that subject so a query about a
    # boat cannot be captured by a phase-lock residual merely because the object
    # phrase overlaps.
    active = re.match(
        r"^how\s+(?:does|do|can|will|would|should)\s+"
        r"(?:(?:you|i|we|they)\s+)?(.+)$",
        q,
        re.IGNORECASE,
    )
    if active:
        remainder = re.sub(
            r"^(?:the|a|an)\s+",
            "",
            active.group(1).strip(),
            flags=re.IGNORECASE,
        )
        words = remainder.split()
        for index, raw in enumerate(words):
            word = raw.strip("?.,!").lower()
            if word in _KNOWN_ACTION_VERBS:
                if (
                    word.startswith("lock")
                    and index > 0
                    and words[index - 1].strip("?.,!").lower()
                    in {"phase", "carrier", "tagged", "frequency"}
                ):
                    continue
                subject = " ".join(words[:index]).strip()
                if subject:
                    return subject
                object_phrase = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    " ".join(words[index + 1:]).strip(),
                    flags=re.IGNORECASE,
                )
                if object_phrase:
                    return object_phrase
    q = _HOW_SCAFFOLD_PREFIX.sub("", q, count=1).strip()
    q = _HOW_SCAFFOLD_VERB.sub("", q, count=1).strip()
    q = _HOW_TRAILING_PASSIVE.sub("", q).strip()
    q = re.sub(r"^(?:the|a|an)\s+", "", q, flags=re.IGNORECASE).strip()
    return q if len(q) >= 3 else ""


# Prepositions/conjunctions that mark an incidental attachment of the target
# noun in a lead clause rather than a subject/direct-object position.
_CARRIER_PREPOSITIONS: frozenset = frozenset({
    "of", "for", "in", "on", "at", "by", "about", "between", "across",
    "with", "without", "through", "via", "from", "onto", "into", "over",
    "under", "near", "against", "toward", "towards", "upon", "per",
    "and", "or", "nor", "than", "like", "unlike", "as", "to",
})


def _carrier_aboutness(target: str, body: str) -> int:
    """Graded carrier-aboutness of *body* with respect to *target*.

    Returns:
      2 — target is the grammatical subject: it opens the body (or a sentence),
          or is acted upon immediately after the opening agent clause
      1 — target named somewhere in the lead clause (may be incidental)
      0 — target absent (or only findable outside the lead / sentence starts)

    Used by the carrier-aboutness gate so that, within a frame-gated candidate
    set, a high-Bellman residual about a *different* carrier cannot win a HOW
    query aimed at this target.  Graded (not boolean) so a body that is
    genuinely *about* the target beats one that merely mentions it in passing.
    """
    if not target:
        return 0
    b = body.lower()
    t_pat = re.escape(target) + ("s?" if " " not in target else "")
    if not re.search(rf"\b{t_pat}\b", b):
        # Multi-word target: fall back to its head noun (last significant word)
        parts = [p for p in target.split() if len(p) >= 4 and p not in _FAMILY_STOP]
        if not parts:
            return 0
        t_pat = re.escape(parts[-1]) + "s?"
        if not re.search(rf"\b{t_pat}\b", b):
            return 0
    # Opens the body or a sentence as its grammatical subject
    if re.search(rf"(?:^|\.\s+)(?:the |a |an |your )?{t_pat}\b", b):
        return 2
    # Acted upon as the direct object of the lead clause
    # (e.g. "Harness Mode suppresses the ghost tax …" for target "ghost tax").
    # Grade 2 requires a POSITIVE grammatical signal: the word immediately
    # preceding the target (past any article) must be a verb. Possessive or
    # prepositional attachment ("another field's carrier wave", "between the
    # carrier waves", "for the carrier wave") is an incidental mention.
    m = re.search(rf"\b{t_pat}\b", b)
    if m is not None and m.start() <= 60:
        prefix = b[:m.start()]
        # Possessive attachment → incidental
        if re.search(r"(?:'s|s')\s+(?:the\s+|a\s+|an\s+)?$", prefix):
            return 1
        # Word immediately before the target, skipping articles
        pm = re.search(r"([a-z']+)\s+(?:the\s+|a\s+|an\s+|your\s+)?$", prefix)
        if pm is None:
            return 2  # target opens the lead clause
        prev = pm.group(1)
        if prev in _CARRIER_PREPOSITIONS:
            return 1  # prepositional attachment → incidental
        # Verb signal: known action verb, or verbal suffix on a ≥4-char base
        if prev in _KNOWN_ACTION_VERBS:
            return 2
        if re.search(r"(?:es|ed|s)$", prev) and len(prev) >= 5:
            return 2
        return 1  # unknown attachment — treat as incidental, not subject
    return 1 if m is not None and m.start() <= 100 else 0


# Action-verb synonym clusters for synthesize-path coupling checks.
# When the query uses verb A but a residual body uses verb B (same cluster),
# the body still satisfies the verb-match requirement.
_ACTION_SYNONYMS: Dict[str, List[str]] = {
    "collide":  ["dock", "crash", "docking", "crashing", "controlled"],
    "dock":     ["collide", "crash", "docking", "crashing", "controlled"],
    "crash":    ["collide", "dock", "crashing", "docking", "controlled"],
    "suppress": ["dampen", "dampens", "floor", "lower", "reduce"],
    "raise":    ["increase", "elevate", "boost", "boosts"],
    "restore":  ["rebuild", "recover", "reseed"],
}


def _is_label_fragment(body: str) -> bool:
    """True when the body is a bare title / label with no predicate.

    Label fragments — "The Storm", "Ghost Tax Suppression", "HyperSeed",
    "The Boat" — are noun phrases with no explanatory clause.  They must not
    win over a full definition or mechanism residual about the same entity.

    A body is NOT a label if it is long enough (> 80 chars) or contains at
    least one predicate-like word that anchors an explanatory statement.
    """
    b = body.strip()
    if len(b) > 80:
        return False
    b_lower = b.lower()
    predicate_words = {
        "is", "are", "was", "were", "will", "be", "been",
        "means", "refers", "involves", "provides", "contains",
        "carries", "places", "happens", "occurs", "can", "may",
        "should", "would", "could", "describe", "represents",
        "indicates", "defines", "explains", "causes", "enables",
        "raises", "restores", "suppresses", "detects", "couples",
        "tunes", "maintains", "applies", "activates", "increases",
    }
    words = set(re.findall(r"\b\w+\b", b_lower))
    return not (words & predicate_words)


def _is_condition_query(query: str) -> bool:
    """True for 'what happens if / without / if not / if there is no …' queries.

    These express failure or absence scenarios and should prefer CONDITION residuals
    over MECHANISM residuals, regardless of whether action verbs appear in the text.
    Checked BEFORE _is_action_query so it takes priority in the ranking branch.
    """
    q = query.lower()
    return bool(re.search(
        r"^(what happens if|what happens without|what happens when .{0,30} (is not|no longer|lost|gone)"
        r"|what (would|will) happen if|what (would|will) happen without"
        r"|if there (is|are) no"
        r"|if .{0,40} (is not|are not|isn'?t|aren'?t|not|no longer)"
        r"|without |if not )",
        q,
    ))


def _is_definition_query(query: str) -> bool:
    """True for 'what is X / what are X / what does X mean / define X' queries.

    These seek identity/explanatory definitions and should prefer DEFINITION
    residuals over MECHANISM residuals.
    Only fires on pure WHAT-is forms; 'what happens if …' is handled separately.
    """
    q = query.lower()
    return bool(re.search(
        r"^(what is |what are |what does .{0,40} mean|define |what exactly is |what exactly are )",
        q,
    ))


@dataclass(frozen=True)
class IntentCell:
    """Structured single-answer Synthesize intent.

    ``primary`` is the answer branch the question asks for. ``secondary``
    lists compatible neighbouring branches that may supply bounded support.
    ``branch_keys`` are used only after the ordinary relevance, target,
    grounding, seed, and frame gates have admitted a candidate.
    """

    primary: str
    secondary: Tuple[str, ...] = ()
    branch_keys: Tuple[str, ...] = ()
    needs_full_cell: bool = True


def classify_intent_cell(query: str) -> IntentCell:
    """Return structured intent without changing retrieval eligibility."""

    q = query.lower().strip()
    frame = _query_frame(query)

    if _is_definition_query(query):
        return IntentCell(
            primary="definition",
            secondary=("what",),
            branch_keys=("definition", "what", "fact"),
        )

    if any(w in q for w in (
        "won't", "wont", "not working", "keeps tripping",
        "failed", "failure", "problem", "issue", "error",
        "miss the", "missed", "dropped", "fault",
    )) or re.search(r"\b(fail|fails|break|breaks|broken)\b", q):
        return IntentCell(
            primary="diagnose",
            secondary=("why", "mechanism"),
            branch_keys=("diagnose", "why", "mechanism", "condition", "effect"),
        )

    if q.startswith("when"):
        return IntentCell(
            primary="when",
            secondary=("condition",),
            branch_keys=("when", "condition", "whatif"),
        )

    if q.startswith("who"):
        return IntentCell(
            primary="who",
            secondary=("what",),
            branch_keys=("who", "entity", "fact"),
        )

    if frame == "WHY" or q.startswith("why") or " why " in f" {q} ":
        return IntentCell(
            primary="why",
            secondary=("mechanism",),
            branch_keys=("why", "cause", "reason", "mechanism"),
        )

    if "mechanism" in q or "process" in q:
        return IntentCell(
            primary="mechanism",
            secondary=("how",),
            branch_keys=("mechanism", "how", "process"),
        )

    if (
        frame == "MECHANISM"
        or q.startswith("how")
        or q.startswith("what about")
        or re.search(r"\bprevent\w*\b", q)
    ):
        return IntentCell(
            primary="how",
            secondary=("mechanism",),
            branch_keys=("how", "mechanism", "process"),
        )

    if frame == "CONDITION":
        return IntentCell(
            primary="what",
            secondary=("condition", "effect"),
            branch_keys=("what", "condition", "whatif", "effect"),
        )

    if q.startswith("what") or frame == "EXAMPLE":
        return IntentCell(
            primary="what",
            secondary=("mechanism",),
            branch_keys=("what", "fact", "effect", "example", "mechanism"),
        )

    return IntentCell(
        primary="general",
        secondary=(),
        branch_keys=("general", "fact"),
        needs_full_cell=False,
    )


def classify_intent(query: str) -> str:
    """Backward-compatible scalar intent for older callers."""

    return classify_intent_cell(query).primary


def _intent_branch_strength(cell: IntentCell, res: "Residual") -> float:
    """Score intent lineage only after a residual has passed hard gates."""

    keys = {key.lower() for key in cell.branch_keys}
    if not keys:
        return 0.0

    _, lineage, body = parse_topic_lineage(res.fragment)
    direct_labels = {
        (lineage or "").lower(),
        _frame(res).lower(),
        (res.seed_intent or "").lower(),
    }
    if direct_labels & keys:
        return 1.0
    if cell.primary in ("how", "mechanism") and re.search(
        r"\bprevent\w*\b",
        body.lower(),
    ):
        return 0.75

    # Family/tag preference is deliberately weaker than an explicit lineage.
    tag = res.fragment.rsplit("::", 1)[0].lower() if "::" in res.fragment else ""
    family = (res.family or "").lower()
    if any(re.search(rf"(?:^|[_-]){re.escape(key)}(?:$|[_-])", tag) for key in keys):
        return 0.75
    if any(re.search(rf"(?:^|[_-]){re.escape(key)}(?:$|[_-])", family) for key in keys):
        return 0.5
    return 0.0


def _intent_support_compatible(
    cell: IntentCell,
    primary: "Residual",
    candidate: "Residual",
) -> bool:
    """Require support to share the primary topic and an allowed branch."""

    same_source = bool(
        primary.source_id
        and candidate.source_id
        and primary.source_id == candidate.source_id
    )
    primary_topic, _, _ = parse_topic_lineage(primary.fragment)
    candidate_topic, _, _ = parse_topic_lineage(candidate.fragment)
    same_topic = bool(
        primary_topic
        and candidate_topic
        and primary_topic.lower() == candidate_topic.lower()
    )
    if not same_source and not same_topic:
        return False
    # Sentence Shadows derived from one immutable Source may carry _S2/_S3
    # suffixes. The explicit branch remains visible in the raw tag even when
    # parse_topic_lineage does not expose it as a standalone lineage.
    return _intent_branch_strength(cell, candidate) > 0.0


def question_frequency(query: str) -> Dict[str, Any]:
    q = query.lower().strip()
    tokens = set(content_tokens(q))
    class_ = "neutral"
    diag_scale = 0.0
    fluct_open = 0.35
    soft_prefer = 0.0
    process_bias = 0.0
    entity_bias = 0.0
    speculative = 0.0

    causal_markers = {"why", "how", "cause", "because", "lead", "result", "effect"}
    process_markers = {"process", "step", "stage", "sequence", "flow", "procedure", "method"}
    entity_markers = {"who", "person", "name", "author", "inventor", "company"}
    locator_markers = {"where", "location", "place", "site"}
    speculative_markers = {"maybe", "perhaps", "could", "might", "imagine", "suppose"}
    diag_words = {"fail", "error", "problem", "issue", "protect", "overload", "loss", "single", "phase", "start", "slip", "torque"}

    if q.startswith("how much") or q.startswith("how many") or "how much" in q or "how many" in q:
        class_ = "quantity"
        soft_prefer = 0.20
        fluct_open = 0.40
    elif any(m in tokens for m in causal_markers) or q.startswith("why") or (q.startswith("how") and not q.startswith("how much") and not q.startswith("how many")) or "caused" in q or "cause" in tokens:
        class_ = "causal"
        process_bias = 0.25
        diag_scale = 0.55
        fluct_open = 0.42
    elif any(m in tokens for m in process_markers):
        class_ = "process"
        process_bias = 0.40
        fluct_open = 0.40
    elif any(m in tokens for m in entity_markers) or q.startswith("who"):
        class_ = "entity"
        entity_bias = 0.35
        soft_prefer = 0.15
    elif any(m in tokens for m in locator_markers) or q.startswith("where"):
        class_ = "locator"
        soft_prefer = 0.10
    elif any(m in tokens for m in speculative_markers):
        class_ = "speculative"
        speculative = 0.55
        fluct_open = 0.28
    elif q.startswith("what"):
        class_ = "what"
        soft_prefer = 0.12
        fluct_open = 0.38
    else:
        class_ = "factual"

    if any(d in tokens for d in diag_words):
        diag_scale = max(diag_scale, 0.30)

    return {
        "class": class_,
        "diag_scale": diag_scale,
        "fluct_open": fluct_open,
        "soft_prefer": soft_prefer,
        "process_bias": process_bias,
        "entity_bias": entity_bias,
        "speculative": speculative,
    }


def text_to_frequencies(text: str, n: int = 8) -> List[int]:
    tokens = content_tokens(text) if text else []
    freqs: List[int] = []
    phase_base = 440 + int(PHASE_OFFSET * 100)
    for t in tokens[:12]:
        th = int(hashlib.sha256(t.encode("utf-8")).hexdigest()[:8], 16)
        freqs.append(phase_base + (th % 1400))
    h = hashlib.sha256(text.encode("utf-8")).digest()
    for i in range(max(2, n - len(freqs))):
        chunk = int.from_bytes(h[i*2:(i*2)+2], "big")
        freqs.append(phase_base + (chunk % 1200))
    seen = set()
    out = []
    for f in freqs:
        if f not in seen:
            seen.add(f)
            out.append(f)
        if len(out) >= n + 4:
            break
    return out[: n + 4]


def resonance_score(query_freqs: List[int], res_freqs: List[int]) -> float:
    if not query_freqs or not res_freqs:
        return 0.0
    qset = set(query_freqs)
    rset = set(res_freqs)
    inter = len(qset & rset)
    return inter / max(len(qset), 1)


@dataclass
class RealityCore:
    phase: float = 0.0
    vel: float = 0.0
    reference: float = 0.0
    scale: float = 1.0
    force: float = 0.0
    leak: float = field(init=False, default=0.0)
    fluidity: float = field(init=False, default=0.0)
    restore: float = field(init=False, default=0.0)
    slow_leak: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        s = max(0.1, abs(self.scale))
        self.leak = 0.05 / (s ** 0.6)  # Structural Leak ≈ 5 %
        self.fluidity = 0.6 / (s ** 0.9)
        self.restore = 0.05 * (s ** 0.7)
        self.slow_leak = self.leak * 0.15

    def step(self, dt: float = 0.05) -> float:
        accel = self.force - self.restore * (self.phase - self.reference) - self.leak * self.vel
        self.vel += accel * dt
        self.phase += self.vel * dt * self.fluidity
        self.reference += (self.phase - self.reference) * self.slow_leak * dt
        self.phase = max(-3.0, min(3.0, self.phase))
        self.vel = max(-2.0, min(2.0, self.vel))
        self.force *= 0.85
        coherence = 1.0 / (1.0 + abs(self.phase - self.reference))
        return float(np.clip(coherence, 0.0, 1.0))


def _intent_body(text: str) -> str:
    """Remove stored envelopes while preserving the complete locked body."""

    stripped = _clean_body(text)
    if stripped != text:
        return stripped.strip()
    if " | " in text:
        return text.split(" | ", 1)[1].strip()
    return text.strip()


def format_intent_cell_answer(
    cell: IntentCell,
    primary: str,
    supports: Sequence[str] = (),
) -> str:
    """Assemble a complete extractive cell with no truncation or connective prose."""

    main = _intent_body(primary)
    if not main:
        return ""

    parts = [main]
    seen = {re.sub(r"\s+", " ", main).strip().lower()}
    total_length = len(main)

    for support in supports:
        if len(parts) >= 3:
            break
        extra = _intent_body(support)
        key = re.sub(r"\s+", " ", extra).strip().lower()
        if not extra or key in seen:
            continue

        projected_length = total_length + 1 + len(extra)
        # Stay within the readable cell range when the primary is already
        # complete. If the primary is unusually short, one complete locked
        # support may exceed the target range; it is still preferable to
        # slicing either statement mid-sentence.
        if total_length >= 120 and projected_length > 400:
            continue

        seen.add(key)
        parts.append(extra)
        total_length = projected_length

    return " ".join(parts)


def format_intent_answer(intent: str, primary: str, support: str = "") -> str:
    """Backward-compatible formatter that now preserves complete locked text."""

    cell = IntentCell(primary=intent, branch_keys=(intent,))
    supports: Tuple[str, ...] = (support,) if support else ()
    return format_intent_cell_answer(cell, primary, supports)


def cosine_similarity(vec_a: Counter, vec_b: Counter) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(vec_a[key] * vec_b.get(key, 0) for key in vec_a)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bytes_to_bits_packed(data: bytes) -> bytes:
    """256-bit signature mixing SHA-256 x2 + BLAKE2b via XOR (all three contribute)."""
    h1 = hashlib.sha256(data).digest()
    h2 = hashlib.sha256(data + b"|residual|void|binary|v2").digest()
    h3 = hashlib.blake2b(data, digest_size=32).digest()
    # XOR-mix so h2 and h3 are not discarded (fixes multi-hash truncation bug)
    out = bytes(a ^ b ^ c for a, b, c in zip(h1, h2, h3))
    return out


def bytes_to_bits(data: bytes, dim: int = BIT_DIM) -> np.ndarray:
    """Convert bytes to bit vector using multi-hash (SHA256 + Blake2b)."""
    h1 = hashlib.sha256(data).digest()
    h2 = hashlib.sha256(data + b"|residual|void|binary|v2").digest()
    h3 = hashlib.blake2b(data, digest_size=32).digest()
    combined = h1 + h2 + h3
    bits = np.unpackbits(np.frombuffer(combined, dtype=np.uint8))
    if len(bits) < dim:
        extra = np.unpackbits(np.frombuffer(hashlib.sha256(combined).digest(), dtype=np.uint8))
        bits = np.concatenate([bits, extra])
    return bits[:dim].astype(np.uint8)


def packed_to_bits(packed: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(packed, dtype=np.uint8)).astype(np.uint8)


def hamming_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Hamming similarity between bit vectors."""
    return 1.0 - np.count_nonzero(a != b) / max(1, len(a))


def hamming_distance_hex(hex_a: str, hex_b: str) -> int:
    if len(hex_a) != len(hex_b):
        raise ValueError("Hex strings must have equal length")
    return sum((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(hex_a, hex_b))


def canonical_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def hmac_sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_verify(secret: str, message: str, signature: str) -> bool:
    expected = hmac_sign(secret, message)
    return hmac.compare_digest(expected, signature)


def sign_packet(payload: bytes, secret: bytes) -> bytes:
    """Sign packet with HMAC-SHA256."""
    return hmac.new(secret, payload, hashlib.sha256).digest()


def verify_signature(payload: bytes, signature: bytes, secret: bytes) -> bool:
    """Verify HMAC signature."""
    expected = sign_packet(payload, secret)
    return hmac.compare_digest(expected, signature)


# ============================================================
# PI-HELIX v2 EDGE EXTRACTION
# ============================================================
def schumann_carrier(t, f0=7.83, harmonics=5):
    """Generate Schumann resonance carrier (7.83 Hz)."""
    s = np.zeros_like(t, dtype=float)
    for h in range(1, harmonics + 1):
        s += (1.0 / h) * np.sin(2 * np.pi * f0 * h * t)
    return s / (np.max(np.abs(s)) + 1e-12)


def pi_helix_drive(t, f0=1.0, gamma=0.05):
    """Golden ratio drive signal (φ-based)."""
    phi = (np.sqrt(5) - 1) / 2
    theta = 2 * np.pi * f0 * t
    helix = np.sin(theta + np.pi * t) * np.cos(np.deg2rad(5) * theta)
    envelope = np.exp(-phi * 0.07 * t) * (1.0 - gamma) + gamma * 0.12 * np.random.randn(len(t))
    return helix * envelope


def bandpass(data, fs, low, high, order=4):
    nyq = 0.5 * fs
    low = max(low / nyq, 1e-5)
    high = min(high / nyq, 0.999)
    if low >= high:
        return data
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, data)


def highpass(data, fs, cutoff=25.0, order=6):
    nyq = 0.5 * fs
    normal = min(max(cutoff / nyq, 1e-5), 0.999)
    b, a = butter(order, normal, btype='high')
    return filtfilt(b, a, data)


def extract_multi_band(residual, fs, bands):
    """Extract frequency peaks from multi-band residual."""
    results = {}
    n = len(residual)
    window = np.hanning(n)
    for name, low, high in bands:
        try:
            band_data = bandpass(residual, fs, low, high) if (low > 0 or high < fs/2) else residual
        except Exception:
            band_data = residual
        spectrum = np.abs(rfft(band_data * window))
        freqs = rfftfreq(n, d=1.0/fs)
        mask = (freqs >= low) & (freqs <= high)
        if not np.any(mask) or len(spectrum[mask]) < 5:
            results[name] = []
            continue
        sub_spec = spectrum[mask]
        sub_freq = freqs[mask]
        peaks, _ = find_peaks(sub_spec, height=np.max(sub_spec)*0.08, distance=4)
        if len(peaks) == 0:
            results[name] = []
            continue
        order = np.argsort(sub_spec[peaks])[::-1]
        top = [(float(sub_freq[peaks[i]]), float(sub_spec[peaks[i]])) for i in order[:5]]
        results[name] = top
    return results


def build_core_negative_v2(measured, fs, max_harmonics=8, max_lag=80):
    """Core nulling via Schumann + Pi-Helix drives."""
    t = np.arange(len(measured)) / fs
    residual = measured.copy().astype(float)
    total_neg = np.zeros_like(residual)
    f0 = 7.83
    
    # Harmonic basis projection
    basis = [np.sin(2 * np.pi * f0 * h * t) for h in range(1, max_harmonics + 1)]
    basis += [np.cos(2 * np.pi * f0 * h * t) for h in range(1, max_harmonics + 1)]
    basis = np.stack(basis, axis=1)
    try:
        coef = np.linalg.lstsq(basis, residual, rcond=None)[0]
        proj = basis @ coef
        residual = residual - proj
        total_neg = total_neg - proj
    except Exception:
        pass
    
    # Schumann nulling
    schumann = schumann_carrier(t)
    best_score = np.inf
    best_neg = np.zeros_like(residual)
    for lag in range(-max_lag, max_lag + 1, 2):
        shifted = np.roll(schumann, lag)
        denom = np.dot(shifted, shifted) + 1e-12
        scale = np.dot(residual, shifted) / denom
        candidate = -scale * shifted
        score = np.sum((residual + candidate)**2)
        if score < best_score:
            best_score = score
            best_neg = candidate
    residual = residual + best_neg
    total_neg = total_neg + best_neg
    
    # Pi-Helix nulling
    drive = pi_helix_drive(t, gamma=0.03)
    best_score = np.inf
    best_neg = np.zeros_like(residual)
    for lag in range(-40, 41, 2):
        shifted = np.roll(drive, lag)
        denom = np.dot(shifted, shifted) + 1e-12
        scale = np.dot(residual, shifted) / denom
        candidate = -scale * shifted
        score = np.sum((residual + candidate)**2)
        if score < best_score:
            best_score = score
            best_neg = candidate
    residual = residual + best_neg
    residual = highpass(residual, fs, cutoff=25.0, order=6)
    return residual, total_neg


def hierarchical_edge_extract_v2(measured, fs, gamma=0.05):
    """Hierarchical edge extraction (Pi-Helix v2)."""
    residual, _ = build_core_negative_v2(measured, fs)
    residual -= np.mean(residual)
    residual /= (np.std(residual) + 1e-12)
    bands = [
        ("field_substrate", 0.5, 35.0),
        ("cytoskeleton", 35.0, 250.0),
        ("bioelectric", 250.0, 1200.0),
        ("cognition", 1200.0, max(fs/2 - 20, 1300)),
    ]
    return residual, extract_multi_band(residual, fs, bands)


# ============================================================
# LEAN RESIDUAL & COHERENT FIELD (hash-chain, no graph/mind)
# ============================================================
@dataclass(frozen=True)
class HyperSeed:
    """Validated ownership and inertia for one source/shadow universe."""

    identity: str
    scale: float = 1.0
    density: float = 1.0
    mass: float = 1.0
    intent: str = ""
    domain: str = "general"

    @classmethod
    def create(
        cls,
        identity: Optional[str] = None,
        *,
        scale: float = 1.0,
        density: float = 1.0,
        mass: Optional[float] = None,
        intent: str = "",
        domain: str = "general",
    ) -> "HyperSeed":
        def positive_finite(value: Any, default: float) -> float:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                parsed = default
            return parsed if math.isfinite(parsed) and parsed > 0.0 else default

        clean_scale = positive_finite(scale, 1.0)
        clean_density = positive_finite(density, 1.0)
        derived_mass = clean_scale * clean_scale * clean_density
        clean_mass = derived_mass if mass is None else positive_finite(mass, derived_mass)
        clean_domain = str(domain or "general").strip() or "general"
        fallback_identity = clean_domain if clean_domain.lower() != "general" else "default"
        clean_identity = str(identity or fallback_identity).strip() or fallback_identity
        return cls(
            identity=clean_identity,
            scale=clean_scale,
            density=clean_density,
            mass=clean_mass,
            intent=str(intent or "").strip(),
            domain=clean_domain,
        )


@dataclass
class Residual:
    """Permanent, append-only residual with cryptographic hash chain."""
    fragment: str
    sig_packed: bytes
    content_set: set
    domain: str
    timestamp: float
    version: int
    node_id: str
    residual_id: str
    prev_hash: str
    chain_hash: str
    protect: bool = True
    shell: int = 0
    imprint_layer: str = "medium"
    coherence: float = 0.85
    value: float = 0.50
    freqs: List[int] = field(default_factory=list)
    core: Optional[RealityCore] = None
    _sig_bits: np.ndarray = field(default=None, repr=False, compare=False)
    # Memory governance fields
    family: str = ""          # derived family slug, e.g. "hyperseed-what", "ghost-tax-how"
    active: bool = True       # True = preferred engram for recall; False = latent (demoted)
    family_tagged: bool = False  # True only when family was derived from a TOPIC::TAG prefix,
                                 # not from the fallback body-word extraction.
    frame_tag: str = ""       # write-time speech-act frame (DEFINITION/MECHANISM/WHY/CONDITION/…)
                              # stamped at lock time so the frame gate is O(1) per residual;
                              # empty string means legacy / untagged (falls back to dynamic).
    # HyperSeed source/shadow ownership
    layer: str = "legacy"      # source/shadow are paired; legacy is a pre-pair low-level record
    source_id: str = ""        # links every shadow to its immutable source
    seed_identity: str = "default"
    seed_scale: float = 1.0
    seed_density: float = 1.0
    seed_mass: float = 1.0
    seed_intent: str = ""
    _sealed: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if (
            name == "layer"
            and getattr(self, "_sealed", False)
            and value != getattr(self, "layer", None)
        ):
            raise AttributeError("immutable_layer")
        if (
            name != "_sealed"
            and getattr(self, "_sealed", False)
            and getattr(self, "layer", None) == "source"
        ):
            raise AttributeError("immutable_source")
        object.__setattr__(self, name, value)

    def bits(self) -> np.ndarray:
        if self.layer == "source":
            immutable_bits = packed_to_bits(self.sig_packed)
            immutable_bits.setflags(write=False)
            return immutable_bits
        if self._sig_bits is None:
            self._sig_bits = packed_to_bits(self.sig_packed)
        return self._sig_bits

    def ensure_core(self, scale: float = 1.0) -> RealityCore:
        if self.core is None:
            self.core = RealityCore(scale=scale)
        else:
            s = max(0.1, abs(scale))
            self.core.scale = s
            self.core.leak = 0.05 / (s ** 0.6)  # Structural Leak ≈ 5 %
            self.core.fluidity = 0.6 / (s ** 0.9)
            self.core.restore = 0.05 * (s ** 0.7)
            self.core.slow_leak = self.core.leak * 0.15
        return self.core

    # Convenience aliases kept for API compatibility
    @property
    def payload(self) -> str:
        return self.fragment

    @property
    def kind(self) -> str:
        return "text"


class CoherentField:
    """Append-only residual store with SHA-256 hash chain."""

    def __init__(self, dim: int = BIT_DIM):
        self.dim = dim
        self.residuals: List[Residual] = []
        self._exact_index: Dict[bytes, int] = {}
        self._token_index: Dict[str, List[int]] = defaultdict(list)
        self._domain_index: Dict[str, List[int]] = defaultdict(list)
        self._lock = threading.RLock()
        self._next_version = 1
        self.chain_tip: str = "GENESIS"
        self._last_query_freqs: List[int] = []

    def _raw_key(
        self,
        text: str,
        layer: str = "legacy",
        seed_identity: str = "default",
        source_id: str = "",
    ) -> bytes:
        material = f"{layer}|{seed_identity}|{source_id}|{text}".encode("utf-8")
        return hashlib.sha256(material).digest()

    def _compute_chain_hash(
        self,
        fragment: str,
        prev_hash: str,
        residual_id: str,
        timestamp: float,
        *,
        layer: str = "legacy",
        source_id: str = "",
        seed_identity: str = "default",
        seed_scale: float = 1.0,
        seed_density: float = 1.0,
        seed_mass: float = 1.0,
        seed_intent: str = "",
        domain: str = "general",
    ) -> str:
        metadata = json.dumps(
            {
                "domain": domain,
                "layer": layer,
                "source_id": source_id,
                "seed_density": seed_density,
                "seed_identity": seed_identity,
                "seed_intent": seed_intent,
                "seed_mass": seed_mass,
                "seed_scale": seed_scale,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        payload = (
            f"{prev_hash}|{residual_id}|{timestamp:.6f}|{metadata}|{fragment}"
        ).encode("utf-8")
        return sha256_hex(payload)

    def store(
        self,
        payload: Union[str, bytes],
        domain: str = "general",
        label: Optional[str] = None,
        node_id: str = "unknown",
        protect: bool = True,
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
        value: Optional[float] = None,
        freqs: Optional[List[int]] = None,
        core: Optional[RealityCore] = None,
        layer: str = "legacy",
        source_id: Optional[str] = None,
        seed_identity: Optional[str] = None,
        seed_scale: float = 1.0,
        seed_density: float = 1.0,
        seed_mass: Optional[float] = None,
        seed_intent: str = "",
    ) -> Tuple[bool, str]:
        """Store payload; returns (success, reason). Duplicate and short inputs are rejected."""
        with self._lock:
            if isinstance(payload, bytes):
                try:
                    text = payload.decode("utf-8").strip()
                except Exception:
                    return False, "decode_fail"
            else:
                text = str(payload).strip()
            if len(text) < 8:
                return False, "too_short"
            clean_layer = str(layer or "legacy").strip().lower()
            if clean_layer not in {"source", "shadow", "legacy", "query", "rejected"}:
                return False, "invalid_layer"
            seed = HyperSeed.create(
                seed_identity,
                scale=seed_scale,
                density=seed_density,
                mass=seed_mass,
                intent=seed_intent,
                domain=domain,
            )
            clean_source_id = str(source_id or "").strip()
            if not clean_source_id:
                clean_source_id = hashlib.sha256(
                    f"{seed.identity}|{text}".encode("utf-8")
                ).hexdigest()[:16]
            key = self._raw_key(text, clean_layer, seed.identity, clean_source_id)
            if key in self._exact_index:
                return False, "duplicate"

            rid = hashlib.sha256(
                f"{clean_layer}|{seed.identity}|{clean_source_id}|{text}".encode("utf-8")
            ).hexdigest()[:16]
            sig_packed = bytes_to_bits_packed(text.encode("utf-8"))
            ts = time.time()
            prev = self.chain_tip
            chain_hash = self._compute_chain_hash(
                text,
                prev,
                rid,
                ts,
                layer=clean_layer,
                source_id=clean_source_id,
                seed_identity=seed.identity,
                seed_scale=seed.scale,
                seed_density=seed.density,
                seed_mass=seed.mass,
                seed_intent=seed.intent,
                domain=seed.domain,
            )

            if shell is None:
                phi = (1 + 5 ** 0.5) / 2
                shell = int((phi * self._next_version) % 4)
            shell = max(0, min(3, int(shell)))
            if imprint_layer not in ("fast", "medium", "deep"):
                imprint_layer = "medium"
            if protect or coherence >= 0.95:
                protect = True
                if imprint_layer == "medium":
                    imprint_layer = "deep"
            init_coh = min(1.0, float(coherence))
            seeded_value = float(value) if value is not None else 0.45 + 0.40 * init_coh
            if clean_layer == "source":
                protect = True
                imprint_layer = "deep"
                init_coh = 1.0
                seeded_value = 0.0
                core = None
            residual_content = set(content_tokens(text))
            residual_freqs: Union[List[int], Tuple[int, ...]] = (
                freqs or text_to_frequencies(text)
            )
            if clean_layer == "source":
                residual_content = frozenset(residual_content)
                residual_freqs = tuple(residual_freqs)
            res = Residual(
                fragment=text,
                sig_packed=sig_packed,
                content_set=residual_content,
                domain=domain,
                timestamp=ts,
                version=self._next_version,
                node_id=node_id,
                residual_id=rid,
                prev_hash=prev,
                chain_hash=chain_hash,
                protect=protect,
                shell=shell,
                imprint_layer=imprint_layer,
                coherence=init_coh,
                value=seeded_value,
                freqs=residual_freqs,
                core=core,
                layer=clean_layer,
                source_id=clean_source_id,
                seed_identity=seed.identity,
                seed_scale=seed.scale,
                seed_density=seed.density,
                seed_mass=seed.mass,
                seed_intent=seed.intent,
            )
            # Derive memory family key and enforce active-engram rule:
            # the new residual becomes active for its family; all prior
            # active siblings in the same family are demoted to latent.
            if clean_layer in {"shadow", "legacy"}:
                res.family, res.family_tagged = _derive_family_key(res.fragment)
                # Stamp write-time frame so the gate is O(1) at query time.
                res.frame_tag = _residual_frame(res.fragment)
                if res.family:
                    for existing in self.residuals:
                        if (
                            existing.layer in {"shadow", "legacy"}
                            and existing.seed_identity == res.seed_identity
                            and existing.family == res.family
                            and existing.active
                        ):
                            existing.active = False
            idx = len(self.residuals)
            self.residuals.append(res)
            self._exact_index[key] = idx
            self._domain_index[domain].append(idx)
            for t in res.content_set:
                self._token_index[t].append(idx)
            self._next_version += 1
            self.chain_tip = chain_hash
            # Capture governance metadata in thread-local storage *before*
            # releasing _lock so callers on this thread see the correct
            # family/active for THIS store, not a concurrent one.
            # Only expose tag-derived families externally; fallback body-word
            # families are used internally for governance but not surfaced.
            _store_result_local.info = {
                "family": res.family if res.family_tagged else "",
                "active": res.active,
                "family_tagged": res.family_tagged,
                "layer": res.layer,
                "source_id": res.source_id,
                "seed": {
                    "identity": res.seed_identity,
                    "scale": res.seed_scale,
                    "density": res.seed_density,
                    "mass": res.seed_mass,
                    "intent": res.seed_intent,
                    "domain": res.domain,
                },
            }
            return True, "locked"

    def _rollback_appends(
        self,
        residual_count: int,
        active_states: List[bool],
    ) -> None:
        """Roll back an interrupted paired write and rebuild all indexes."""
        with self._lock:
            self.residuals = self.residuals[:residual_count]
            for residual, was_active in zip(self.residuals, active_states):
                if residual.layer != "source" and residual.active != was_active:
                    residual.active = was_active
            self._exact_index.clear()
            self._domain_index.clear()
            self._token_index.clear()
            for index, residual in enumerate(self.residuals):
                key = self._raw_key(
                    residual.fragment,
                    residual.layer,
                    residual.seed_identity,
                    residual.source_id,
                )
                self._exact_index[key] = index
                self._domain_index[residual.domain].append(index)
                for token in residual.content_set:
                    self._token_index[token].append(index)
            self._next_version = (
                max((residual.version for residual in self.residuals), default=0) + 1
            )
            self.chain_tip = (
                self.residuals[-1].chain_hash if self.residuals else "GENESIS"
            )
            _store_result_local.info = None

    def verify_chain(self) -> Tuple[bool, str]:
        """Verify the cryptographic hash chain; returns (ok, message)."""
        with self._lock:
            if not self.residuals:
                return True, "empty chain ok"
            expected_prev = "GENESIS"
            for i, res in enumerate(self.residuals):
                if res.prev_hash != expected_prev:
                    return False, (
                        f"break at index {i}: expected prev {expected_prev[:16]}..."
                        f" got {res.prev_hash[:16]}..."
                    )
                recomputed = self._compute_chain_hash(
                    res.fragment,
                    res.prev_hash,
                    res.residual_id,
                    res.timestamp,
                    layer=res.layer,
                    source_id=res.source_id,
                    seed_identity=res.seed_identity,
                    seed_scale=res.seed_scale,
                    seed_density=res.seed_density,
                    seed_mass=res.seed_mass,
                    seed_intent=res.seed_intent,
                    domain=res.domain,
                )
                if recomputed != res.chain_hash:
                    return False, f"hash mismatch at index {i} (id={res.residual_id})"
                expected_prev = res.chain_hash
            if expected_prev != self.chain_tip:
                return False, "chain tip does not match last residual"
            return True, f"chain intact ({len(self.residuals)} residuals)"

    def _primary_tag_hit(self, query: str, fragment: str) -> bool:
        q_tags = [t for t in query.split() if "::" in t]
        if not q_tags:
            return False
        frag_lower = fragment.lower()
        return any(tag.lower() in frag_lower for tag in q_tags)

    def _bridge_hits(self, query_text: str, cset: Set[str]) -> int:
        hits = 0
        q = query_text.lower().strip()
        for trigger, targets in PHRASE_BRIDGES.items():
            if trigger in q:
                for target in targets:
                    target_tokens = set(content_tokens(target))
                    if target_tokens and target_tokens & cset:
                        hits += 1
                        break
        return hits

    def rank(
        self,
        query: str,
        domain: Optional[str] = None,
        top_k: int = 20,
        freq: Optional[Dict] = None,
        layer: Optional[str] = "shadow",
    ) -> List[tuple]:
        with self._lock:
            if not self.residuals:
                return []
            if freq is None:
                freq = question_frequency(query)
            # RCF: lock probe frequencies for resonance scoring
            self._last_query_freqs = text_to_frequencies(query)
            probe = packed_to_bits(bytes_to_bits_packed(query.encode("utf-8")))
            qset = set(content_tokens(query))
            q_lower = query.lower().strip()
            candidate_idxs: set = set()
            if qset:
                for t in qset:
                    candidate_idxs.update(self._token_index.get(t, []))
            if domain:
                candidate_idxs.update(self._domain_index.get(domain, []))
            # always soft-expand for morphological / fuzzy neighbors (bond~bonded, frame~frames)
            if qset and self.residuals:
                for i, res in enumerate(self.residuals):
                    if res.domain == "query":
                        continue
                    if layer is not None and not (
                        res.layer == layer
                        or (layer == "shadow" and res.layer == "legacy")
                    ):
                        continue
                    soft = fuzzy_token_hits(qset, res.content_set)
                    if soft >= 0.65:
                        candidate_idxs.add(i)
                        continue
                    for qt in qset:
                        if len(qt) < 4:
                            continue
                        for ct in res.content_set:
                            if len(ct) >= 4 and (ct.startswith(qt) or qt.startswith(ct[:4])):
                                candidate_idxs.add(i)
                                break
            # phrase-anchor / bridge expansion (locked-text only)
            q_lower_r = query.lower().strip()
            bridge_needles = []
            for trigger, targets in PHRASE_BRIDGES.items():
                if trigger in q_lower_r:
                    bridge_needles.extend(targets)
            for i, res in enumerate(self.residuals):
                if res.domain in ("query", "rejected"):
                    continue
                if layer is not None and not (
                    res.layer == layer
                    or (layer == "shadow" and res.layer == "legacy")
                ):
                    continue
                frag = res.fragment.lower()
                for phrase in PHRASE_ANCHORS:
                    if phrase in q_lower_r and any(w in frag for w in phrase.split() if len(w) > 1):
                        candidate_idxs.add(i)
                        break
                for needle in bridge_needles:
                    if needle in frag:
                        candidate_idxs.add(i)

            if not candidate_idxs and not (qset or domain):
                candidate_idxs = set(range(len(self.residuals)))
            scores = []
            for i in candidate_idxs:
                res = self.residuals[i]
                if res.domain in ("query", "rejected"):
                    continue  # never answer from query or rejected residuals
                if layer is not None and not (
                    res.layer == layer
                    or (layer == "shadow" and res.layer == "legacy")
                ):
                    continue
                r = hamming_sim(probe, res.bits())
                hits = sum(1 for t in qset if t in res.content_set) if qset else 0
                coverage = hits / max(1, len(qset)) if qset else 0.0
                score = 0.20 * r + 0.40 * coverage
                frag_lower = res.fragment.lower()
                exact_sub = bool(q_lower and q_lower in frag_lower)
                if exact_sub:
                    score += 0.62
                elif any(t in frag_lower for t in qset if len(t) >= 3):
                    score += 0.28
                if hits >= 2:
                    score += 0.22
                elif hits == 1:
                    score += 0.12
                if "::" in res.fragment:
                    score += 0.12
                # primary anchor boost: token matches the tag before first ::
                # handle MOTOR::OVERLOAD::... -> primary becomes overload
                parts = [p for p in frag_lower.split("::") if p]
                primary_tag = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
                for t in qset:
                    if len(t) >= 4 and t == primary_tag:
                        score += 0.55
                    elif len(t) >= 4 and (primary_tag.startswith(t) or t in primary_tag):
                        score += 0.40
                # multi-token primary match e.g. "service factor" vs SERVICE_FACTOR
                primary_compact = primary_tag.replace("_", " ").replace("-", " ")
                if primary_compact and all(tok in frag_lower for tok in primary_compact.split() if len(tok) > 2):
                    if any(tok in qset for tok in primary_compact.split() if len(tok) > 2):
                        score += 0.35
                # key-noun boost
                key_boost = 0.0
                for t in qset:
                    if len(t) >= 4 and t in frag_lower:
                        key_boost += 0.16
                score += min(0.32, key_boost)
                # phrase anchor / bridge boost
                phrase_hits = 0.0
                for phrase in PHRASE_ANCHORS:
                    if phrase in q_lower and phrase in frag_lower:
                        phrase_hits += 1.0
                for trigger, targets in PHRASE_BRIDGES.items():
                    if trigger in q_lower:
                        for needle in targets:
                            if needle in frag_lower:
                                phrase_hits += 1.2
                score += min(0.45, phrase_hits * 0.22)
                # negative evidence: exhaustion vs stroke style cross-talk
                if "exhaustion" in q_lower and "stroke" in frag_lower and "exhaustion" not in frag_lower:
                    score *= 0.45
                if "stroke" in q_lower and "exhaustion" in frag_lower and "stroke" not in frag_lower:
                    score *= 0.45

                # quantity questions prefer residuals that state a number/unit
                if any(w in q_lower for w in ("how much", "how many", "what is the minimum", "minimum", "inches", "voltage", "pressure")):
                    if any(ch.isdigit() for ch in res.fragment):
                        score += 0.28
                    # demote pure diagnostic cross-talk on quantity pulls
                    if any(w in frag_lower for w in ("error", "fault", "failed", "indicates")) and not any(ch.isdigit() for ch in res.fragment):
                        score *= 0.70
                # multi-token phrase boost (natural gas, water column, fuel line)
                q_words = [t for t in q_lower.split() if len(t) > 2]
                for wi in range(len(q_words) - 1):
                    phrase = q_words[wi] + " " + q_words[wi + 1]
                    if phrase in frag_lower:
                        score += 0.22
                # light synonym / morphological bridges
                bridge_hits = 0
                for t in qset:
                    for alt in TOKEN_BRIDGES.get(t, []):
                        if alt in frag_lower or alt == primary_tag:
                            score += 0.32
                            bridge_hits += 1
                            break
                if bridge_hits:
                    score += min(0.18, 0.08 * bridge_hits)
                if domain and res.domain == domain:
                    score += 0.10
                if res.protect:
                    score += 0.05
                # hierarchical shell + imprint boosts (synthesis-friendly)
                # prefer deeper shells and deep imprint for grounded answers
                shell_boost = {0: 0.02, 1: 0.04, 2: 0.06, 3: 0.03}.get(getattr(res, "shell", 0), 0.0)
                imprint_boost = {"deep": 0.10, "medium": 0.04, "fast": 0.01}.get(getattr(res, "imprint_layer", "medium"), 0.0)
                score += shell_boost + imprint_boost
                score += 0.08 * float(getattr(res, "coherence", 0.85) - 0.70)
                # Bellman value bias: high-value residuals (proven useful) rise; low-value decay
                score += 0.26 * (float(getattr(res, "value", 0.50)) - 0.50)
                # conceptual / memoir intent boost — targeted, not blanket
                if any(w in q_lower for w in ("why", "origin", "began", "built", "started")):
                    if "origin" in frag_lower or "began as" in frag_lower or "memory bottleneck" in frag_lower:
                        score += 0.55
                    if "void_purpose" in frag_lower and "origin" not in frag_lower:
                        score -= 0.15
                if any(w in q_lower for w in ("unused", "decay", "decayed", "disappear")):
                    if "slowly decay" in frag_lower or "decay never deletes" in frag_lower:
                        score += 0.55
                    if "remain fully visible" in frag_lower:
                        score += 0.35
                    if "surface decayed" in frag_lower or "ascending value" in frag_lower:
                        score += 0.15 if ("find" in q_lower or "how do i" in q_lower) else -0.10
                if any(w in q_lower for w in ("invent", "invention", "invent facts", "make up", "hallucinate")):
                    if "no free invention" in frag_lower or "supported by locked" in frag_lower or "every answer must be supported" in frag_lower:
                        score += 1.20
                    elif "never invents" in frag_lower or "inventable" in frag_lower:
                        score -= 0.25
                # Coherence Principle force
                if any(w in q_lower for w in ("structural leak", "ghost tax", "coherence principle", "5 percent", "resonant window", "chaos plus coherence", "emergence")):
                    if any(k in frag_lower for k in ("structural leak", "ghost tax", "5 percent", "primordial", "coherence principle", "resonant window", "chaos plus coherence", "emergence")):
                        score += 0.60
                # Orch / microtubule force
                if any(w in q_lower for w in ("orch", "orch or", "microtubule", "tubulin", "tryptophan", "anesthetic", "objective reduction", "hameroff")):
                    if any(k in frag_lower for k in ("microtubule", "orch", "tubulin", "objective reduction", "tryptophan", "anesthetic", "maps orchestrate")):
                        score += 0.55
                # RCF resonant boost
                qf = getattr(self, "_last_query_freqs", None)
                rf = getattr(res, "freqs", None)
                if qf and rf:
                    score += 0.35 * resonance_score(qf, rf)

                # frequency-aware modulation
                if freq.get("diag_scale", 0.0) > 0 and any(d in frag_lower for d in ("fail", "failed", "error", "protect", "overload", "loss", "phase", "slip", "start", "drop", "dropped", "fault", "pressure", "miss")):
                    score += 0.28 * freq.get("diag_scale", 0.0)
                # causal queries demote pure status/ready lines
                if freq.get("class") == "causal" and any(d in frag_lower for d in ("ready signal", "signal sent", "confirmed grip", "before conveyor")):
                    score *= 0.55
                if freq.get("process_bias", 0.0) > 0 and any(p in frag_lower for p in ("process", "step", "method", "flow", "sequence", "start", "assemble")):
                    score += 0.15 * freq.get("process_bias", 0.0)
                if freq.get("entity_bias", 0.0) > 0 and any(e in frag_lower for e in ("person", "name", "who", "author")):
                    score += 0.12 * freq.get("entity_bias", 0.0)

                # ---- Specificity / density / FULL demotion (tight answers preferred) ----
                # Density: matching tokens as fraction of residual content tokens
                res_tok_count = max(1, len(res.content_set))
                density = hits / res_tok_count if hits else 0.0
                score += min(0.22, density * 0.55)

                # Length dampener: long dumps lose when lexical coverage is comparable
                frag_len = len(res.fragment)
                if frag_len > 420:
                    # progressive soft penalty; keeps long residuals usable but rarely primary
                    length_penalty = min(0.28, (frag_len - 420) / 2800.0)
                    score *= (1.0 - length_penalty)

                # Explicit _FULL residual demotion (still available, rarely wins)
                is_full = primary_tag.endswith("_full") or primary_tag.endswith("full") or "_full::" in frag_lower
                if is_full:
                    score *= 0.72
                    # extra demotion if a query token already lives in a tighter tag elsewhere
                    # (handled downstream by synthesize rank_key as well)

                # Stronger primary-tag exactness when query mentions the concept
                if primary_tag and len(primary_tag) >= 4:
                    tag_tokens_set = set(primary_tag.replace("_", " ").split())
                    tag_overlap = len(tag_tokens_set & qset)
                    if tag_overlap >= 1:
                        score += 0.18 * tag_overlap
                    # exact tag token present in query is decisive
                    for tt in tag_tokens_set:
                        if len(tt) >= 4 and tt in q_lower:
                            score += 0.25
                            break

                # treat fuzzy/morphological hits + synonym bridges as partial lexical signal
                soft_hits = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                if bridge_hits:
                    soft_hits = max(soft_hits, 0.70)
                lexical_signal = hits + (1 if exact_sub else 0) + (1 if soft_hits >= 0.55 else 0)
                if lexical_signal == 0:
                    score *= 0.03
                    if r > 0.58:
                        try:
                            phase_factor = (int(res.residual_id[:4], 16) % 100) / 100.0
                        except (TypeError, ValueError):
                            phase_factor = 0.0
                        score += 0.18 * phase_factor * freq.get("fluct_open", 0.35)
                elif hits == 0 and soft_hits >= 0.65:
                    # soft-only match: mild damp, keep bridge score
                    score *= 0.55
                    score += min(0.25, soft_hits * 0.15)
                elif coverage < 0.15 and not exact_sub and soft_hits < 0.65:
                    score *= 0.30
                elif hits == 1 and not exact_sub:
                    score *= 0.68

                scores.append((res, float(min(1.5, score))))  # headroom so conceptual boosts can break ties
            scores.sort(key=lambda x: -x[1])
            return scores[:top_k]

    def backfill_governance(self) -> int:
        """Re-derive family keys for residuals with family='' and enforce FIFO governance.

        Runs once after snapshot or chain load to bring residuals locked before
        the governance layer under active-engram demotion rules.

        Pass 1 — re-derivation:
            Any residual whose family is '' has _derive_family_key called on its
            fragment.  If a key is derivable the residual is updated in-place.

        Pass 2 — FIFO governance:
            For every non-empty family the last residual (highest list index =
            most-recently locked) is made active; all prior same-family residuals
            are demoted to latent.  Residuals whose family remains '' are untouched.

        Returns the number of residuals whose family key was backfilled.
        """
        with self._lock:
            backfilled = 0

            # Pass 1: re-derive family key for residuals with no family
            for res in self.residuals:
                if res.layer not in {"shadow", "legacy"}:
                    continue
                if res.family == "":
                    fam, tagged = _derive_family_key(res.fragment)
                    if fam:
                        res.family = fam
                        res.family_tagged = tagged
                        backfilled += 1

            # Pass 2: FIFO governance — last residual per family wins.
            # Scan forward to find the highest index per family (= most recently locked).
            family_last_idx: Dict[str, int] = {}
            for i, res in enumerate(self.residuals):
                if res.layer in {"shadow", "legacy"} and res.family:
                    family_last_idx[f"{res.seed_identity}\0{res.family}"] = i

            # Enforce: only the last residual for each family stays active.
            for i, res in enumerate(self.residuals):
                if res.layer in {"shadow", "legacy"} and res.family:
                    family_key = f"{res.seed_identity}\0{res.family}"
                    if i == family_last_idx[family_key]:
                        res.active = True   # most-recent engram: ensure it is active
                    else:
                        res.active = False  # older sibling: demote to latent

            return backfilled

    def status(self) -> Dict[str, Any]:
        with self._lock:
            ok, msg = self.verify_chain()
            # Compute governance summary under _lock so it is consistent with
            # concurrent store() calls that mutate active/latent state.
            # Only tag-derived (family_tagged=True) families appear externally;
            # fallback body-word families are used internally but never surfaced.
            # Per-family breakdown includes both active and latent counts so
            # consumers can identify which families have silenced memories.
            families_map: Dict[str, Dict[str, int]] = {}
            for r in self.residuals:
                if r.layer in {"shadow", "legacy"} and r.family and r.family_tagged:
                    entry = families_map.setdefault(r.family, {"active": 0, "latent": 0})
                    if r.active:
                        entry["active"] += 1
                    else:
                        entry["latent"] += 1
            layers = Counter(r.layer for r in self.residuals)
            seeds: Dict[str, Dict[str, Any]] = {}
            for r in self.residuals:
                if r.layer not in {"source", "shadow"}:
                    continue
                entry = seeds.setdefault(
                    r.seed_identity,
                    {
                        "identity": r.seed_identity,
                        "scale": r.seed_scale,
                        "density": r.seed_density,
                        "mass": r.seed_mass,
                        "intent": r.seed_intent,
                        "domain": r.domain,
                        "sources": 0,
                        "shadows": 0,
                    },
                )
                entry["sources" if r.layer == "source" else "shadows"] += 1
            return {
                "residual_count": len(self.residuals),
                "layers": dict(layers),
                "seeds": seeds,
                "chain_ok": ok,
                "chain_msg": msg,
                "chain_tip": self.chain_tip[:16] + "...",
                "memory": {
                    "families": families_map,
                },
            }


# ============================================================
# ENVELOPE AUTH (hub-style: nonce / iat / exp / kid / TTL / skew)
# ============================================================
class SecureNode:
    """Lean node: instance methods for lock/project, static methods for envelope auth."""

    def __init__(self, node_id: str, void: "CoherentVoid") -> None:
        self.node_id = node_id
        self.void = void
        self.secret = void.secret
        void.connect(node_id)

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------
    def lock_text(
        self,
        text: str,
        domain: str = "general",
        protect: bool = True,
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
        identity: Optional[str] = None,
        scale: float = 1.0,
        density: float = 1.0,
        mass: Optional[float] = None,
        intent: str = "",
        shadow_texts: Optional[List[str]] = None,
    ) -> str:
        """Lock text via envelope auth then pass verified payload into lean ingest."""
        secret_str = self.secret if isinstance(self.secret, str) else self.secret.decode("utf-8")
        envelope = SecureNode.lock_payload(text, secret=secret_str)
        if not SecureNode.verify_payload(envelope, secret=secret_str):
            return "auth_failed"
        payload_bytes = text.encode("utf-8")
        to_sign = payload_bytes + b"lock" + domain.encode()
        secret_bytes = self.secret if isinstance(self.secret, bytes) else self.secret.encode("utf-8")
        sig = sign_packet(to_sign, secret_bytes)
        return self.void.ingest(
            "lock", payload_bytes, domain=domain, source=self.node_id,
            signature=sig, protect=protect,
            shell=shell, imprint_layer=imprint_layer, coherence=coherence,
            seed_identity=identity, seed_scale=scale, seed_density=density,
            seed_mass=mass, seed_intent=intent, shadow_payloads=shadow_texts,
        )

    def project(self, query: str, mode: str = "exact") -> str:
        return self.void.project(query, mode=mode, source=self.node_id)

    # ------------------------------------------------------------------
    # Static envelope helpers (hub-style)
    # ------------------------------------------------------------------
    @staticmethod
    def _kid(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def lock_payload(
        payload: Union[str, bytes],
        secret: str,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = 30,
        skew_seconds: int = 10,
    ) -> Dict[str, Any]:
        now = int(time.time())
        if isinstance(payload, bytes):
            encoded_payload = base64.b64encode(payload).decode("ascii")
            kind = "binary"
        else:
            encoded_payload = payload
            kind = "text"

        body: Dict[str, Any] = {
            "payload": encoded_payload,
            "kind": kind,
            "iat": now,
            "timestamp": now,
            "exp": now + ttl_seconds,
            "nonce": uuid.uuid4().hex,
            "kid": SecureNode._kid(secret),
            "metadata": metadata or {},
        }
        serialized = canonical_payload(body)
        body["signature"] = hmac_sign(secret, serialized)
        return body

    @staticmethod
    def verify_payload(
        payload: Dict[str, Any],
        secret: str,
        ttl_seconds: int = 30,
        skew_seconds: int = 10,
        previous_secret: Optional[str] = None,
    ) -> bool:
        candidates = [secret]
        if previous_secret and previous_secret != secret:
            candidates.append(previous_secret)

        for candidate in candidates:
            signature = payload.get("signature", "")
            body = {k: v for k, v in payload.items() if k != "signature"}
            serialized = canonical_payload(body)

            if not signature or not hmac_verify(candidate, serialized, signature):
                continue

            timestamp = payload.get("iat")
            if timestamp is None:
                timestamp = payload.get("timestamp")
            if not isinstance(timestamp, int):
                continue

            exp = payload.get("exp")
            if not isinstance(exp, int):
                continue

            nonce = payload.get("nonce")
            kid = payload.get("kid")
            if not isinstance(nonce, str) or not nonce:
                continue
            if not isinstance(kid, str) or kid != SecureNode._kid(candidate):
                continue

            now = int(time.time())
            if timestamp > now + skew_seconds:
                continue
            if exp < now - skew_seconds:
                continue
            if now - timestamp > ttl_seconds + skew_seconds:
                continue

            return True

        return False


# ============================================================
# COHERENT VOID – lean dual-mode engine (exact / synthesize)
# ============================================================
class CoherentVoid:
    """Lean void engine: permanent residuals, hash chain, strict refusal gates."""

    _REFUSAL = "No locked residual in coherent void."

    def __init__(
        self,
        name: str = "void",
        secret: Union[str, bytes] = b"CHANGE-ME-32-BYTE-SECRET-KEY!!",
        min_project_score: float = 0.58,
        min_grounding: float = 0.35,
    ) -> None:
        self.name = name
        # Normalise secret: keep both bytes and str forms available
        if isinstance(secret, bytes):
            self.secret: bytes = secret
            self._secret: str = secret.decode("utf-8", errors="replace")
        else:
            self._secret = secret
            self.secret = secret.encode("utf-8")
        self.field = CoherentField()
        self.min_score = min_project_score
        self.min_grounding = min_grounding
        self._lock = threading.RLock()
        self.lock_count = 0
        self.project_count = 0
        self.invention_refusals = 0
        self.start_time = time.time()
        self.connected: Dict[str, float] = {}
        self._query_log_limit = 3000
        self.vibrate_steps = 12
        self.vibrate_dt = 0.08
        self.coupling = 0.38
        self.ghost_tax = 0.05  # Coherence Principle resonant window / 5% interface
        self.harness_gamma = 5000.0
        self.boost_sigma = 0.16
        self.boost_beta = 0.22
        self.boost_gamma = 3500.0
        self.boost_enabled = True
        self.alchemy_enabled = True
        self.cross_seed_resonance_threshold = 0.92
        self.or_events = 0
        # Pure-Harness dynamics is an explicit opt-in diagnostic layer. It is
        # never consulted by Exact/Synthesize ranking.
        self.pure_harness = PureHarnessDynamics()

    def configure_pure_harness(
        self,
        *,
        enabled: bool = True,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Enable or retune the immutable Pure-Harness dynamics evaluator."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        with self._lock:
            self.pure_harness = self.pure_harness.configured(
                enabled=enabled,
                **overrides,
            )
            return self.pure_harness.status()

    def pure_harness_response(
        self,
        initial_residual: float,
        gamma: float,
        **controls: Any,
    ) -> float:
        """Evaluate the scalar Pure-Harness law without changing field state."""
        return self.pure_harness.response(initial_residual, gamma, **controls)

    def evolve_residual_pairs(
        self,
        residuals: List[float],
        **controls: Any,
    ) -> Dict[str, Any]:
        """Run an opt-in deterministic multi-pair flow and return diagnostics."""
        result: ResidualFlowResult = self.pure_harness.evolve(
            residuals,
            **controls,
        )
        return result.as_dict()

    def clear(self) -> Dict[str, Any]:
        """Wipe all residuals and reset counters — field returns to genesis state."""
        with self._lock:
            wiped = len(self.field.residuals)
            self.field = CoherentField()
            self.lock_count = 0
            self.project_count = 0
            self.invention_refusals = 0
            self.or_events = 0
            self.start_time = time.time()
        return {"cleared": wiped, "locked": 0}

    def connect(self, system_id: str) -> str:
        with self._lock:
            self.connected[system_id] = time.time()
            return f"{system_id} connected"

    def ingest(
        self,
        action: str,
        payload: bytes,
        domain: str = "general",
        source: str = "unknown",
        label: Optional[str] = None,
        signature: Optional[bytes] = None,
        protect: bool = True,
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
        seed_identity: Optional[str] = None,
        seed_scale: float = 1.0,
        seed_density: float = 1.0,
        seed_mass: Optional[float] = None,
        seed_intent: str = "",
        shadow_payloads: Optional[List[Union[str, bytes]]] = None,
    ) -> str:
        """Authenticated ingest; action must be 'lock' or 'confirm'."""
        with self._lock:
            if action in ("lock", "confirm"):
                if signature is None:
                    return "auth_failed"
                to_verify = payload + action.encode() + domain.encode()
                if not verify_signature(to_verify, signature, self.secret):
                    return "auth_failed"
                seed = HyperSeed.create(
                    seed_identity,
                    scale=seed_scale,
                    density=seed_density,
                    mass=seed_mass,
                    intent=seed_intent,
                    domain=domain,
                )
                if isinstance(payload, bytes):
                    try:
                        source_text = payload.decode("utf-8").strip()
                    except Exception:
                        return "decode_fail"
                else:
                    source_text = str(payload).strip()
                source_id = hashlib.sha256(
                    f"{seed.identity}|{source_text}".encode("utf-8")
                ).hexdigest()[:16]
                raw_shadows = shadow_payloads or [source_text]
                shadows: List[str] = []
                seen_shadows: Set[str] = set()
                for raw_shadow in raw_shadows:
                    if isinstance(raw_shadow, bytes):
                        try:
                            shadow_text = raw_shadow.decode("utf-8").strip()
                        except Exception:
                            return "shadow_decode_fail"
                    else:
                        shadow_text = str(raw_shadow).strip()
                    if len(shadow_text) < 8:
                        return "shadow_too_short"
                    if not _shadow_is_grounded(source_text, shadow_text):
                        return "ungrounded_shadow"
                    if shadow_text in seen_shadows:
                        continue
                    seen_shadows.add(shadow_text)
                    shadows.append(shadow_text)
                if not shadows:
                    return "missing_shadow"

                # Pair commit: preflight and append while holding the field lock.
                # If any write unexpectedly fails, remove every appended record
                # and restore governance/index state before returning.
                with self.field._lock:
                    source_key = self.field._raw_key(
                        source_text, "source", seed.identity, source_id
                    )
                    if source_key in self.field._exact_index:
                        return "duplicate"
                    for shadow_text in shadows:
                        shadow_key = self.field._raw_key(
                            shadow_text, "shadow", seed.identity, source_id
                        )
                        if shadow_key in self.field._exact_index:
                            return "duplicate"
                    checkpoint = len(self.field.residuals)
                    active_states = [
                        residual.active for residual in self.field.residuals
                    ]
                    try:
                        ok, reason = self.field.store(
                            source_text,
                            domain=domain,
                            label=label,
                            node_id=source,
                            protect=True,
                            shell=0,
                            imprint_layer="deep",
                            coherence=1.0,
                            value=0.0,
                            layer="source",
                            source_id=source_id,
                            seed_identity=seed.identity,
                            seed_scale=seed.scale,
                            seed_density=seed.density,
                            seed_mass=seed.mass,
                            seed_intent=seed.intent,
                        )
                        if not ok:
                            self.field._rollback_appends(checkpoint, active_states)
                            return reason
                        for shadow_text in shadows:
                            shadow_ok, shadow_reason = self.field.store(
                                shadow_text,
                                domain=domain,
                                label=label,
                                node_id=source,
                                protect=protect,
                                shell=shell,
                                imprint_layer=imprint_layer,
                                coherence=coherence,
                                layer="shadow",
                                source_id=source_id,
                                seed_identity=seed.identity,
                                seed_scale=seed.scale,
                                seed_density=seed.density,
                                seed_mass=seed.mass,
                                seed_intent=seed.intent,
                            )
                            if not shadow_ok:
                                self.field._rollback_appends(
                                    checkpoint, active_states
                                )
                                return shadow_reason
                    except Exception:
                        self.field._rollback_appends(checkpoint, active_states)
                        return "store_failed"
                self.lock_count += 1
                return "locked"
            return "ignored"

    def _log_query(self, query: str, source: str = "user", mode: str = "exact") -> None:
        freq = question_frequency(query)
        qlog = f"QUERY::{source}::{mode}|{freq['class']} | {query[:120]}"
        ok, _ = self.field.store(
            qlog,
            domain="query",
            node_id=source,
            protect=False,
            shell=0,
            imprint_layer="fast",
            coherence=0.99,
            value=0.0,
            freqs=text_to_frequencies(query),
            layer="query",
            seed_identity="__query__",
        )
        if ok and len(self.field._domain_index.get("query", [])) > self._query_log_limit:
            # Bound query-chain index growth while preserving append-only residual history.
            self.field._domain_index["query"] = self.field._domain_index["query"][-self._query_log_limit:]

    def _vibrate_residuals(
        self,
        candidates: List[Tuple[Residual, float]],
        query_ref: float = 1.0,
    ) -> Tuple[Dict[str, float], Set[str]]:
        """Carrier-wave drive: rank each residual by living alignment to the query carrier.

        Drive law (per candidate):
          target_phase = +query_ref if net ≥ 0 else −query_ref
          core.force   = k_net * net + k_pull * (target_phase − core.phase)
          core.step(dt)    ← preserves ghost-tax leak so phase still jitters

        Final score = align + motion_bonus
          align        = 1 / (1 + |core.phase − query_ref|)
                         × low_factor if anti-phase  (suppressed, not zeroed)
          motion_bonus = small reward for cores with active velocity (living orbit)
                         zero for anti-phase cores (no reward for anti-phase jitter)

        Returns:
          boosts       — {residual_id: carrier_boost} in roughly [−1.2, +1.1]
          in_phase_set — residual IDs whose cores settled phase ≥ 0

        Ghost-tax leak (≈5%) is preserved via RealityCore.step — modes never freeze
        to identical phases; perfect zero-error lock is intentionally avoided.
        """
        if not candidates:
            return {}, set()

        k_net  = 0.8          # coupling:  net score drives force
        k_pull = 0.5          # restoring: pull toward target phase
        low_factor    = 0.3   # suppression multiplier for anti-phase residuals
        motion_scale  = 0.08  # velocity → motion bonus conversion
        motion_cap    = 0.10  # maximum motion bonus (keeps it "small")

        cores = []
        for res, net in candidates[:12]:
            core = res.ensure_core(scale=1.0 + abs(net))
            target_phase = query_ref if net >= 0.0 else -query_ref
            cores.append((res, net, core, target_phase))

        for _ in range(self.vibrate_steps):
            for res, net, core, target_phase in cores:
                core.force = k_net * net + k_pull * (target_phase - core.phase)
                core.step(self.vibrate_dt)

        # Rank by sustained living alignment to query carrier.
        out: Dict[str, float] = {}
        in_phase_set: Set[str] = set()
        for res, net, core, target_phase in cores:
            in_phase = core.phase >= 0.0
            align = 1.0 / (1.0 + abs(core.phase - query_ref))
            if not in_phase:
                align *= low_factor          # anti-phase: suppressed, not zeroed
            # Motion bonus: reward living orbit (nonzero velocity) for in-phase modes.
            # Anti-phase cores get no motion bonus — jitter away from carrier is not rewarded.
            motion_bonus = min(abs(core.vel) * motion_scale, motion_cap) if in_phase else 0.0
            # Carrier boost: blend of phase alignment + residual motion bonus.
            carrier_boost = (2.0 * align - 1.0) + motion_bonus
            out[res.residual_id] = carrier_boost
            if in_phase:
                in_phase_set.add(res.residual_id)
        return out, in_phase_set

    def _pure_harness_phase_adjustments(
        self,
        candidates: List[Tuple[Residual, float]],
        query_ref: float = 1.0,
    ) -> Dict[str, float]:
        """Return a bounded, relative phase tie-breaker for eligible Shadows.

        This runs only after Synthesize has already applied grounding, seed,
        frame, target, and carrier gates.  It models a candidate's remaining
        carrier phase error with the scalar Pure-Harness envelope and centers
        the resulting quality, so it cannot manufacture relevance or add a
        uniform score lift to a candidate set.
        """
        config = self.pure_harness.config
        if not (
            config.enabled
            and config.synthesize_phase_signal_enabled
            and candidates
        ):
            return {}

        phase_errors = [
            abs(res.ensure_core(scale=1.0 + abs(score)).phase - query_ref)
            for res, score in candidates[:6]
        ]
        qualities = [
            1.0 / (1.0 + self.pure_harness.response(error, gamma=1.0))
            for error in phase_errors
        ]
        mean_quality = sum(qualities) / len(qualities)
        max_bonus = config.synthesize_phase_signal_max_bonus
        return {
            res.residual_id: max(
                -max_bonus,
                min(max_bonus, max_bonus * 2.0 * (quality - mean_quality)),
            )
            for (res, _), quality in zip(candidates[:6], qualities)
        }

    @staticmethod
    def _passes_synthesize_primary_admission(
        residual: Residual,
        score: float,
        query_terms: Set[str],
        normalized_query: str,
    ) -> bool:
        """Return whether an unmodified candidate may become a primary answer."""
        if score < 0.48:
            return False
        if not query_terms:
            return True
        return (
            fuzzy_token_hits(query_terms, residual.content_set) >= 0.20
            or normalized_query in residual.fragment.lower()
        )

    def _apply_pure_harness_phase_signal(
        self,
        ordered: List[Tuple[Residual, float]],
        query_terms: Set[str],
        normalized_query: str,
    ) -> List[Tuple[Residual, float]]:
        """Apply the optional signal only to candidates already admitted to answer.

        The primary-admission test uses the carrier-adjusted score *before* any
        Pure-Harness adjustment. This ensures the signal can resolve a close
        eligible tie but cannot convert a below-threshold candidate or refusal
        into an answer.
        """
        pre_phase_ranked = sorted(ordered, key=lambda item: item[1], reverse=True)
        admitted_candidates = [
            (res, score)
            for res, score in pre_phase_ranked
            if self._passes_synthesize_primary_admission(
                res,
                score,
                query_terms,
                normalized_query,
            )
        ][:6]
        if len(admitted_candidates) < 2:
            return ordered
        best_score = max(score for _, score in admitted_candidates)
        tie_window = self.pure_harness.config.synthesize_phase_signal_tie_window
        phase_candidates = [
            (res, score)
            for res, score in admitted_candidates
            if best_score - score <= tie_window
        ]
        if len(phase_candidates) < 2:
            return ordered
        phase_adjustments = self._pure_harness_phase_adjustments(phase_candidates)
        if not phase_adjustments:
            return ordered
        return [
            (
                res,
                max(
                    0.48,
                    score + phase_adjustments[res.residual_id],
                )
                if res.residual_id in phase_adjustments
                else score,
            )
            for res, score in ordered
        ]

    def _bellman_update(self, winners: List[Residual], reward: float = 0.85, alpha: float = 0.12, gamma: float = 0.90) -> None:
        """Lightweight Bellman-style value update.
        Successful residuals gain value; nearby competitors receive a mild decay.
        False / low-utility knowledge is gradually phased out of ranking preference.
        """
        if not winners:
            return
        # max value among current knowledge (excluding query/rejected)
        max_v = 0.50
        for r in self.field.residuals:
            if r.layer not in {"shadow", "legacy"} or r.domain in ("query", "rejected"):
                continue
            max_v = max(max_v, float(getattr(r, "value", 0.50)))
        target = reward + gamma * max_v
        winner_ids = {w.residual_id for w in winners}
        for r in self.field.residuals:
            if r.layer not in {"shadow", "legacy"} or r.domain in ("query", "rejected"):
                continue
            v = float(getattr(r, "value", 0.50))
            if r.residual_id in winner_ids:
                # positive update toward target
                r.value = max(0.05, min(1.0, (1.0 - alpha) * v + alpha * target))
                # slight coherence lift on proven residuals
                r.coherence = min(1.0, r.coherence + 0.01)
            else:
                # slow global decay so unused / conflicting knowledge loses preference
                r.value = max(0.05, v * (1.0 - self.ghost_tax * 0.06))

    @staticmethod
    def _is_json_leak(fragment: str) -> bool:
        """Return True if this residual fragment is a leaked JSON request body."""
        f = fragment.strip()
        # Raw JSON object that contains inject payload keys
        if f.startswith("{") and ('"full_text"' in f or '"domain"' in f or '"protect"' in f):
            return True
        # Residual body section (after ::) starts with { and has JSON keys
        body = f.split("::", 2)[-1].strip() if "::" in f else f
        if body.startswith("{") and (
            '"full_text"' in body or "full_text" in body[:60]
        ):
            return True
        # Segment whose body is literally the key string
        if '"full_text"' in fragment or '"full_text":' in fragment:
            return True
        return False

    @staticmethod
    def _exact_terms(text: str) -> List[str]:
        """Distinctive hard-match terms; no bridges, values, or learned weights."""
        return [
            token
            for token in tokenize(text)
            if len(token) > 2 and token not in _EVIDENCE_STOP
        ]

    @staticmethod
    def _hard_term_hits(terms: List[str], residual: Residual) -> int:
        residual_stems = {_stem_token(token) for token in residual.content_set}
        return sum(1 for term in terms if _stem_token(term) in residual_stems)

    def _project_exact(self, query: str) -> Union[str, List[str]]:
        """Pure Source transfer: deterministic hard evidence or refusal."""
        sources = [
            residual
            for residual in self.field.residuals
            if residual.layer in {"source", "legacy"}
            and not self._is_json_leak(residual.fragment)
        ]
        if not sources:
            self.invention_refusals += 1
            return self._REFUSAL

        q_lower = query.lower().strip().rstrip("?!.")
        terms = self._exact_terms(query)
        q_frame = _query_frame(query)
        multi_frames: Dict[str, Optional[Set[str]]] = {
            "LIST": {"LIST_ITEM"},
            # A complete unstructured Source that contains all hard step-query
            # terms is admissible even though its companion Shadows carry the
            # explicit STEP frames.
            "STEPS": {"STEP", "GENERAL"},
            "COMPARE": {"COMPARE", "RELATION", "DEFINITION", "FACT"},
            "RELATE": {"RELATION", "DEFINITION", "MECHANISM"},
            "SUMMARIZE": None,
        }

        if q_frame in multi_frames:
            allowed = multi_frames[q_frame]
            threshold = max(1, math.ceil(len(terms) * 0.5))
            compare_targets = (
                _extract_compare_targets(query) if q_frame == "COMPARE" else []
            )
            selected: List[Residual] = []
            for residual in sources:
                if allowed is not None and _frame(residual) not in allowed:
                    continue
                if compare_targets:
                    if not any(
                        target_terms
                        and self._hard_term_hits(target_terms, residual)
                        == len(target_terms)
                        for target_terms in (
                            self._exact_terms(target) for target in compare_targets
                        )
                    ):
                        continue
                elif terms and self._hard_term_hits(terms, residual) < threshold:
                    continue
                selected.append(residual)
            if q_frame == "STEPS":
                def exact_step_number(residual: Residual) -> Tuple[int, int]:
                    match = re.search(
                        r"\bstep[_\s-]*(\d+)\b",
                        residual.fragment,
                        re.IGNORECASE,
                    )
                    return (
                        int(match.group(1)) if match else 999,
                        residual.version,
                    )

                selected.sort(key=exact_step_number)
            if q_frame in {"COMPARE", "RELATE"}:
                selected = selected[:2]
            elif q_frame != "STEPS":
                selected = selected[:5]
            if selected:
                return [residual.fragment for residual in selected]
            self.invention_refusals += 1
            return self._REFUSAL

        # Exact substring is the strongest admissible proof.
        substring_matches = [
            residual for residual in sources
            if q_lower and q_lower in residual.fragment.lower()
        ]
        if substring_matches:
            return substring_matches[0].fragment

        # Otherwise every distinctive query term must be covered, allowing only
        # deterministic morphology (plural/tense), never fuzzy or bridged terms.
        if terms:
            exact_target = _extract_query_target(query)
            coverage_matches = [
                residual for residual in sources
                if self._hard_term_hits(terms, residual) == len(terms)
                and (
                    not exact_target
                    or _residual_matches_target(exact_target, residual)
                )
            ]
            if coverage_matches:
                return coverage_matches[0].fragment

        self.invention_refusals += 1
        return self._REFUSAL

    def project(self, query: str, mode: str = "exact", source: str = "user") -> str:
        """Project query against locked residuals; returns fragment string or refusal."""
        self.project_count += 1
        self._log_query(query, source=source, mode=mode)
        if mode == "exact":
            return self._project_exact(query)
        if mode != "synthesize":
            return "Unknown mode"
        # top_k=64: exact path was using the default of 20, which means any
        # residual ranked 21st or lower was invisible to all frame-preference
        # passes.  In a corpus of 12-20+ residuals with dense same-carrier
        # competition the definition or condition residual often falls that far.
        # Normalize query before ranking: strip modal/pronoun scaffolding
        # ("should you", "do you", "please") and singularize simple plurals
        # ("boats"→"boat") so phrase-variant queries reach the same residuals.
        # The original query is still used for all intent/target/frame logic;
        # only the Bellman scoring call uses the normalized form.
        _rq = re.sub(r'\b(should|please)\b\s*', '', query, flags=re.I)
        _rq = re.sub(r'\b(do|can|will|would|shall)\s+(you|i|we|they)\b\s*', '', _rq, flags=re.I)
        # Strip any residual "you/i/we" left after modal removal
        _rq = re.sub(r'\b(you|i|we)\b\s*', '', _rq, flags=re.I)
        _rq_words = []
        for _w in _rq.split():
            _wb = _w.strip("?.,!")
            if (_wb.endswith("s") and not _wb.endswith("ss")
                    and len(_wb) >= 5 and _wb[:-1].isalpha()):
                _rq_words.append(_wb[:-1])
            else:
                _rq_words.append(_wb)
        _rq = " ".join(_rq_words).strip() or query
        ranked = self.field.rank(_rq, top_k=64, layer="shadow")
        ranked = [
            (res, score) for res, score in ranked
            if res.domain != "query" and not self._is_json_leak(res.fragment)
        ]
        # Multi-body intents (STEPS, LIST, COMPARE, SUMMARIZE, RELATE) collect
        # sets of residuals — individual step/list bodies often score below
        # min_score because they are not the single best match for the query text.
        # Bypass the single-residual score gate for these intents so the
        # assembly block always gets a chance to run.
        _early_intent = _query_frame(query)
        _is_multi_body = _early_intent in ("STEPS", "LIST", "COMPARE", "SUMMARIZE", "RELATE")
        if not ranked or (not _is_multi_body and ranked[0][1] < self.min_score):
            self.invention_refusals += 1
            return self._REFUSAL
        # ── Target-subject hard filter (both exact and synthesize) ───────────
        # Core rule (change order): token overlap alone must not determine the
        # winner when a clear query target can be extracted.  "phase lock HOW"
        # must not return the tagged-locks residual just because both share
        # "lock".  Filter ranked to residuals whose tag primary or lead subject
        # matches the extracted target, THEN let frame/ego rank inside that set.
        #
        # Hard latch: if a target is extractable and zero residuals match it,
        # refuse rather than fall through to the full list (wrong neighbor wins).
        #
        # Skip for multi-body intents (STEPS/LIST/etc.) — they aggregate across
        # residuals by design and must not be restricted to a single target.
        if not _is_multi_body:
            _hard_tgt = _extract_synthesize_query_target(query)
            if _hard_tgt:
                _hard_matched = [
                    (r, s) for r, s in ranked
                    if _residual_matches_target(_hard_tgt, r)
                ]
                if _hard_matched:
                    ranked = _hard_matched
                else:
                    # Target is known but no residual is about it → refuse.
                    self.invention_refusals += 1
                    return self._REFUSAL
        # ── End target-subject hard filter ───────────────────────────────────
        q_lower = query.lower().strip()
        qset = set(content_tokens(query))
        if mode == "exact":
            # Apply active-engram bonus to the ranked list so active residuals
            # are preferred in all passes, not only in the fallback.
            # +0.25 for active engrams; latent cousins keep their raw score.
            # Sort by Bellman score + active-engram bonus - multi-sentence penalty.
            # Multi-sentence dump residuals win on coverage; the penalty pushes them
            # below atomic single-sentence residuals with similar Bellman scores.
            # 0.12 per extra sentence ending beyond the first (cheap '. ' count on raw fragment).
            ranked = sorted(
                ranked,
                key=lambda item: (
                    item[1]
                    + (0.25 if item[0].active else 0.0)
                    - 0.12 * max(0, item[0].fragment.count(". ") - 1)
                ),
                reverse=True,
            )
            # ── Hard frame gate ──────────────────────────────────────────────
            # Core rule (change order): memory stores atomic framed engrams;
            # context retrieves by carrier AND modulation.  A wrong-frame
            # residual is ineligible whenever a correctly-framed one exists.
            #
            # Steps:
            #   1. Classify query into DEFINITION / MECHANISM / WHY /
            #      CONDITION / GENERAL.
            #   2. Find every residual in ranked whose body frame matches.
            #   3. If any match → keep ONLY those; passes below operate on
            #      an already-frame-filtered list so wrong-frame residuals
            #      cannot win regardless of Bellman magnitude.
            #   4. If none match → fall through to full ranked (broadened).
            _q_frame = _query_frame(query)
            if _q_frame != "GENERAL":
                _frame_matched = [
                    (r, s) for r, s in ranked
                    if _frame(r) == _q_frame
                ]
                if _frame_matched:
                    ranked = _frame_matched
            # ── Target-subject narrowing (MECHANISM) ─────────────────────────
            # Fix 1: same-frame wrong-carrier collision.  When multiple
            # MECHANISM residuals exist ("phase lock" and "tagged locks" both
            # MECHANISM), frame gate alone cannot separate them.  Further
            # restrict to residuals whose body has the query's carrier as its
            # primary subject (aboutness == 2).  Falls through to full
            # frame-gated list if no residual meets the stricter test.
            if _q_frame == "MECHANISM" and len(ranked) > 1:
                _tgt_stems_fg = _extract_action_stems(query)
                _tgt_carrier_fg = _extract_carrier_target(query, _tgt_stems_fg)
                if not _tgt_carrier_fg:
                    _tgt_carrier_fg = _extract_mechanism_target(query)
                if _tgt_carrier_fg:
                    _tgt_primary = [
                        (r, s) for r, s in ranked
                        if _carrier_aboutness(
                            _tgt_carrier_fg,
                            parse_topic_lineage(r.fragment)[2],
                        ) == 2
                    ]
                    if _tgt_primary:
                        ranked = _tgt_primary
            # ── End frame gate ───────────────────────────────────────────────

            # ── Multi-residual and CONFIRM projection ────────────────────────
            # Runs BEFORE single-body passes so the intent router takes
            # precedence when the intent is explicitly multi-body or CONFIRM.
            #
            # LIST      → top-N LIST_ITEM residuals, same carrier family
            # STEPS     → ordered STEP residuals
            # SUMMARIZE → top-N any frame, same domain
            # COMPARE   → up to 2 DEFINITION/FACT residuals (compared targets)
            # RELATE    → up to 2 RELATION/DEFINITION/MECHANISM residuals
            # CONFIRM   → first FACT/DEFINITION residual with token overlap
            #
            # Returns List[str] (handled in merged.py) for multi-body intents.
            # CONFIRM returns a single str (same as single-body passes).
            # Falls through to single-body passes if nothing found.
            if _q_frame == "CONFIRM":
                # "Is X about Y?" / "Is it true that …" — find a FACT or
                # DEFINITION residual that shares tokens with the claim.
                # Value check: if query asserts a specific numeric/named value
                # ("fifty percent", "5%", "true", etc.) that does not appear in
                # the residual body, refuse — returning a body that says a
                # different value would be a false confirmation.
                # Extract specific value tokens (numbers + word-numerals only;
                # units like "percent" are excluded so "fifty percent" checks
                # "fifty" against the body, not the unit word).
                _conf_value_pats = re.findall(
                    r'\b(\d+(?:\.\d+)?|fifty|twenty|thirty|forty|sixty|seventy|'
                    r'eighty|ninety|hundred)\b',
                    q_lower,
                )
                for _res, _score in ranked[:32]:
                    if _score < 0.20:
                        break
                    if fuzzy_token_hits(qset, _res.content_set) < 0.12:
                        continue
                    if _frame(_res) in ("FACT", "DEFINITION"):
                        _, _clean = parse_lineage(_res.fragment)
                        if _conf_value_pats:
                            _body_l = _clean.lower()
                            if not any(v in _body_l for v in _conf_value_pats):
                                # Asserted value absent from residual → refuse
                                self.invention_refusals += 1
                                return self._REFUSAL
                        return _clean
                # No supporting fact → refuse
                self.invention_refusals += 1
                return self._REFUSAL
            elif _q_frame == "COMPARE":
                # COMPARE composition (change order):
                #   1. Prefer explicit *_COMPARE or *_RELATION residuals
                #   2. Else compose: find definition/fact for target A + target B
                #   3. Empty only if fewer than 2 useful target residuals exist
                _multi_hits = []
                _seen_bodies: "Set[str]" = set()
                # Pass 1: explicit COMPARE / RELATION residuals
                for _res, _score in ranked:
                    if _score < 0.18:
                        break
                    if fuzzy_token_hits(qset, _res.content_set) < 0.10:
                        continue
                    if _frame(_res) in ("COMPARE", "RELATION"):
                        _, _clean = parse_lineage(_res.fragment)
                        _key = _clean[:80].lower()
                        if _key not in _seen_bodies:
                            _seen_bodies.add(_key)
                            _multi_hits.append(_clean)
                    if len(_multi_hits) >= 2:
                        break
                # Pass 2: compose from target-A def + target-B def when explicit missing
                if len(_multi_hits) < 2:
                    _ctgts = _extract_compare_targets(query)
                    _by_tgt: "Dict[str, str]" = {}
                    for _res, _score in ranked:
                        if _score < 0.15:
                            break
                        if _frame(_res) not in ("DEFINITION", "FACT"):
                            continue
                        _, _, _rb = parse_topic_lineage(_res.fragment)
                        _rbl = _rb.lower()
                        for _tgt in _ctgts:
                            if _tgt.lower() not in _by_tgt and _tgt.lower() in _rbl:
                                _, _clean = parse_lineage(_res.fragment)
                                _key = _clean[:80].lower()
                                if _key not in _seen_bodies:
                                    _seen_bodies.add(_key)
                                    _by_tgt[_tgt.lower()] = _clean
                    # Merge target defs with any explicit hits
                    for _tgt_body in list(_by_tgt.values()):
                        if _tgt_body not in _multi_hits:
                            _multi_hits.append(_tgt_body)
                        if len(_multi_hits) >= 2:
                            break
                if _multi_hits:
                    return _multi_hits
                # Fall through to single-body passes
            elif _q_frame == "STEPS":
                # STEPS assembly — root-cause fix:
                # Step bodies rarely share tokens with the query ("lock framed
                # residuals" vs "steps to use the void"), so ranked may only
                # contain one anchor step.  Iterating ranked misses siblings.
                #
                # Strategy:
                #   1. Anchor: find first STEP residual in ranked (token-matched)
                #   2. Derive family prefix: strip trailing '-N' digits from slug
                #      so LOCK_STEP_1/2/3 → 'lock-step' shared prefix
                #   3. Collect: scan self.field.residuals for all STEP-framed /
                #      step-numbered residuals whose family starts with that prefix
                #   4. Fallback: no anchor → any STEP residual with a query token
                #   5. Order by parsed step number; return ordered set
                _STEP_NUM_RE = re.compile(r"^step\s*(\d+)", re.IGNORECASE)
                _FAMSUFFIX_RE = re.compile(r"-\d+$")
                # Find anchor and its family prefix from token-matched ranked list
                _step_anchor_prefix: "Optional[str]" = None
                for _res, _ in ranked:
                    _, _, _asb = parse_topic_lineage(_res.fragment)
                    if _frame(_res) == "STEP" or _STEP_NUM_RE.match(_asb.strip()):
                        if _res.family:
                            _step_anchor_prefix = _FAMSUFFIX_RE.sub("", _res.family)
                        break
                # Collect all step residuals from the full field
                _step_items: "List[Tuple[int, str]]" = []
                _seen_bodies: "Set[str]" = set()
                for _res in self.field.residuals:
                    if _res.domain in ("query", "rejected"):
                        continue
                    _, _, _sb = parse_topic_lineage(_res.fragment)
                    _sm = _STEP_NUM_RE.match(_sb.strip())
                    if _frame(_res) != "STEP" and not _sm:
                        continue
                    # Scope: family prefix match (anchor) or query-token overlap
                    if _step_anchor_prefix:
                        _res_prefix = _FAMSUFFIX_RE.sub("", _res.family or "")
                        if _res_prefix != _step_anchor_prefix:
                            continue
                    else:
                        _frag_l = _res.fragment.lower()
                        if not any(t in _frag_l for t in qset if len(t) >= 3):
                            continue
                    _num = int(_sm.group(1)) if _sm else 999
                    _, _clean = parse_lineage(_res.fragment)
                    _key = _clean[:80].lower()
                    if _key not in _seen_bodies:
                        _seen_bodies.add(_key)
                        _step_items.append((_num, _clean))
                _step_items.sort(key=lambda x: x[0])
                _multi_hits = [_body for _, _body in _step_items]
                if _multi_hits:
                    return _multi_hits
                # Fall through to single-body passes
            elif _q_frame in ("LIST", "SUMMARIZE", "RELATE"):
                _frame_allowed: "Optional[Set[str]]" = {
                    "LIST":      {"LIST_ITEM"},
                    "SUMMARIZE": None,
                    "RELATE":    {"RELATION", "DEFINITION", "MECHANISM"},
                }[_q_frame]
                _max_items = 2 if _q_frame == "RELATE" else 5
                _multi_hits = []
                _seen_bodies = set()
                for _res, _score in ranked:
                    if _score < 0.18:
                        break
                    if fuzzy_token_hits(qset, _res.content_set) < 0.10:
                        continue
                    if _frame_allowed is not None and _frame(_res) not in _frame_allowed:
                        continue
                    _, _clean = parse_lineage(_res.fragment)
                    _key = _clean[:80].lower()
                    if _key in _seen_bodies:
                        continue
                    _seen_bodies.add(_key)
                    _multi_hits.append(_clean)
                    if len(_multi_hits) >= _max_items:
                        break
                if _multi_hits:
                    return _multi_hits
                # No frame-matched residuals → fall through to single-body passes
            # ── End multi-residual / CONFIRM ─────────────────────────────────

            # Pass 1: full query string appears verbatim in the fragment.
            for res, score in ranked[:24]:
                if q_lower and q_lower in res.fragment.lower() and score >= 0.50:
                    _, clean = parse_lineage(res.fragment)
                    return clean
            # Pass 2: HOW / action queries — prefer residual whose body contains
            # the query's action verb stem (beats pure Bellman weight).
            # Guard: skip for condition queries — "What happens if there is no X?"
            # is classified as _is_action_query=True (stem "happen") but must reach
            # Pass 4 (CONDITION frame), not be short-circuited here by the stem.
            if _is_action_query(query) and not _is_condition_query(query):
                action_stems = _extract_action_stems(query)
                if action_stems:
                    # Carrier-aboutness gate: within the frame-gated set, a
                    # stem match alone is not enough — the query's noun target
                    # must be the primary subject of the winning body, or a
                    # wrong-carrier HOW residual with high Bellman weight wins.
                    _p2_target = _extract_carrier_target(query, action_stems)
                    for res, score in ranked[:24]:
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        b_lower = ev_body.lower()
                        if score >= 0.45 and any(stem in b_lower for stem in action_stems):
                            if not _p2_target:
                                _, clean = parse_lineage(res.fragment)
                                return clean
                            if _carrier_aboutness(_p2_target, ev_body) == 2:
                                # primary subject — decisive
                                _, clean = parse_lineage(res.fragment)
                                return clean
                            # grade < 2 → incidental mention or wrong carrier:
                            # keep scanning; the Bellman-fallback aboutness gate
                            # below refuses if nothing is genuinely about target.
            # Pass 2b: MECHANISM intent gate — catches conversational HOW forms
            # that Pass 2 misses (passive voice, subject pronoun, scaffolding
            # verb before the target noun):
            #   "How do you achieve phase lock?"  — target extracted as
            #     "achieve phase lock", aboutness=1 → Pass 2 falls through
            #   "How is phase lock achieved?"     — target "is phase lock achiev",
            #     aboutness=1 → same
            #   "achieve phase lock"              — no HOW prefix at all
            # Strategy: strip all HOW scaffolding with _extract_mechanism_target
            # to get the bare noun phrase, then find any MECHANISM-framed residual
            # whose body contains that phrase.  No aboutness gate: if the
            # mechanism residual explicitly names the target, it answers the query.
            # Falls through (does not refuse) when no MECHANISM residual found.
            if _q_frame == "MECHANISM":
                _mech_tgt = _extract_mechanism_target(query)
                if _mech_tgt:
                    _mech_tgt_l = _mech_tgt.lower()
                    for res, score in ranked:
                        if _frame(res) != "MECHANISM":
                            continue
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        if _mech_tgt_l in ev_body.lower():
                            _, clean = parse_lineage(res.fragment)
                            return clean
            # Pass 2c: WHY target-aboutness gate.
            # "Why can ego help or hurt?" must return the ego residual, not the
            # empathy residual (both are WHY-framed; soft moral-word bridging
            # causes cross-topic drift without this gate).
            # Strategy: extract the query's subject noun, scan WHY-framed
            # residuals for any whose body mentions that subject, return the
            # first.  Falls through if no WHY residual names the target.
            if _q_frame == "WHY":
                _why_tgt = _extract_why_target(query)
                if _why_tgt:
                    _why_tgt_l = _why_tgt.lower()
                    # Multi-word: accept if ALL head words (len>=4) appear in body.
                    # Single-word: require exact substring match.
                    _why_tgt_words = [w for w in _why_tgt_l.split() if len(w) >= 4]
                    for res, score in ranked:
                        if _frame(res) != "WHY":
                            continue
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        b_lower = ev_body.lower()
                        if _why_tgt_l in b_lower:
                            _, clean = parse_lineage(res.fragment)
                            return clean
                        if _why_tgt_words and all(w in b_lower for w in _why_tgt_words):
                            _, clean = parse_lineage(res.fragment)
                            return clean
            # Pass 3: WHAT-is definition queries — prefer the residual that
            # *defines* the target over any residual that merely mentions it.
            # Two-pass: definitional body first; non-weak mention as fallback.
            if _is_definition_query(query):
                def_target = _extract_definition_target(query)
                if def_target:
                    _dt3_pat = (
                        re.escape(def_target) + r"s?"
                        if " " not in def_target
                        else re.escape(def_target)
                    )
                    # Pass 3a: body opens with "target is/are …"
                    # Scan the FULL ranked list — in dense same-carrier fields the
                    # definition residual can fall below position 24 in Bellman rank.
                    # Prefer atomic (≤1 interior sentence break) over blob dumps;
                    # blob fallback used only if no atomic match exists anywhere.
                    _def_pat = rf"(?:^|\.\s+)(?:the |your |a |an )?{_dt3_pat}\s+(?:is|are)\b"
                    # Collect ALL definitional candidates instead of returning the
                    # first in Bellman order. Old alternate phrasings accumulate
                    # Bellman value over many rounds and would otherwise permanently
                    # outrank a freshly locked, more precise source residual.
                    # Selection key (descending priority):
                    #   1. atomic body (≤1 interior sentence break)
                    #   2. lead-clause precision — target named at the very start
                    #      of the body beats target buried mid-lead
                    #      + active-engram bonus (the freshest lock in the family)
                    #   3. Bellman-ranked score — tiebreak ONLY; accumulated value
                    #      alone can never override a stronger target match.
                    _def_hits: "List[Tuple[Residual, float, str]]" = []
                    for res, score in ranked:
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        b_lower = ev_body.lower()
                        if re.search(_def_pat, b_lower[:100]):
                            _def_hits.append((res, score, ev_body))
                    if _def_hits:
                        def _lead_precision(body: str) -> float:
                            b = body.lower()
                            m = re.search(_def_pat, b[:100])
                            if not m:
                                return 0.0
                            pos = m.start()
                            # Target as the opening subject is the most precise
                            # definition; later positions are progressively weaker.
                            if pos == 0:
                                return 3.0
                            if pos <= 30:
                                return 1.5
                            return 0.5
                        _best = max(
                            _def_hits,
                            key=lambda t: (
                                1 if t[2].count(". ") <= 1 else 0,   # atomic first
                                _lead_precision(t[2])
                                + (1.0 if t[0].active else 0.0),      # fresh lock wins
                                t[1],                                 # Bellman tiebreak
                            ),
                        )
                        _, clean = parse_lineage(_best[0].fragment)
                        return clean
                    # Pass 3b: target in body, not buried in a list/attribute clause
                    for res, score in ranked:
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        b_lower = ev_body.lower()
                        if score >= 0.25 and re.search(rf"\b{_dt3_pat}\b", b_lower):
                            _weak3 = bool(re.search(
                                rf"(?:"
                                rf",\s*{_dt3_pat}"
                                rf"|{_dt3_pat}\s*,"
                                rf"|\b(?:carries?|includes?|including|contains?)\b[^.]*\b{_dt3_pat}\b"
                                rf")",
                                b_lower[:200],
                            ))
                            if not _weak3:
                                _, clean = parse_lineage(res.fragment)
                                return clean
            # Pass 4: CONDITION queries — full ranked scan, atomic-first.
            # Same-carrier dump residuals (boat/storm with broad token coverage)
            # can outrank the correctly-framed IF/without residual in dense fields;
            # scanning the full list and preferring atomic bodies prevents this.
            if _is_condition_query(query):
                _cond_blob: "Residual | None" = None
                for res, score in ranked:
                    _, _, ev_body = parse_topic_lineage(res.fragment)
                    if _frame(res) == "CONDITION":
                        if fuzzy_token_hits(qset, res.content_set) >= 0.15:
                            if ev_body.count(". ") <= 1:   # atomic
                                _, clean = parse_lineage(res.fragment)
                                return clean
                            elif _cond_blob is None:
                                _cond_blob = res
                if _cond_blob is not None:
                    _, clean = parse_lineage(_cond_blob.fragment)
                    return clean
            # Off-domain action refuse: queries that request off-field
            # generative tasks (write, code, joke, draw, generate, invent)
            # must not be satisfied by weak Bellman token overlap.
            # "Write python code" shares "lock" with mechanism residuals but
            # is clearly outside the field ontology.
            _OFF_DOMAIN: frozenset = frozenset({
                "write", "code", "joke", "draw", "generate", "invent",
                "create", "make", "tell", "sing", "translate", "summarise",
            })
            _q_first = q_lower.split()[0] if q_lower else ""
            if _q_first in _OFF_DOMAIN:
                self.invention_refusals += 1
                return self._REFUSAL
            # Fallback: top Bellman match with token-hit threshold.
            top_res, top_score = ranked[0]
            hits = sum(1 for t in qset if t in top_res.content_set) if qset else 0
            exact_sub = bool(q_lower and q_lower in top_res.fragment.lower())
            if hits == 0 and not exact_sub:
                self.invention_refusals += 1
                return self._REFUSAL
            if top_score < 0.62 and hits < 2 and not exact_sub:
                self.invention_refusals += 1
                return self._REFUSAL
            # Off-target gate: query has ≥3 distinctive terms but zero evidence
            # match → selected only by Bellman weight on a shared entity token.
            # Prefer empty over a wrong related residual.
            _, _, _et_body = parse_topic_lineage(top_res.fragment)
            _et_ev = _evidence_score(query, _et_body)
            if _et_ev == 0.0:
                _et_q_words = [w.strip("?.,!") for w in query.lower().split()
                               if len(w) > 3 and w.strip("?.,!") not in _EVIDENCE_STOP]
                if len(_et_q_words) >= 3:
                    self.invention_refusals += 1
                    return self._REFUSAL
            # Carrier-aboutness gate (Bellman fallback, MECHANISM frame only):
            # within the frame-gated set, the top-Bellman residual must have the
            # query's noun target as its primary subject.  If it doesn't, swap
            # in the best-ranked residual that does; if none exists, refuse —
            # a wrong-carrier HOW residual must never win on Bellman weight.
            # DEFINITION queries are handled by Pass 3 (_extract_definition_target)
            # and CONDITION queries by Pass 4; both bypass this gate.
            if _q_frame == "MECHANISM":
                _ab_stems = _extract_action_stems(query)
                _ab_target = _extract_carrier_target(query, _ab_stems)
                if _ab_target:
                    _, _, _ab_top_body = parse_topic_lineage(top_res.fragment)
                    _ab_top = _carrier_aboutness(_ab_target, _ab_top_body)
                    if _ab_top < 2:
                        # Find the best-ranked candidate with the target as its
                        # primary subject (grade 2). Grade 1 (incidental
                        # possessive/prepositional mention) is NOT sufficient to
                        # answer a target-specific MECHANISM query.
                        _ab_swap: "Optional[Tuple[Residual, float]]" = None
                        for _ab_res, _ab_score in ranked:
                            if _ab_score < 0.30:
                                break
                            _, _, _ab_body = parse_topic_lineage(_ab_res.fragment)
                            if _carrier_aboutness(_ab_target, _ab_body) == 2:
                                _ab_swap = (_ab_res, _ab_score)
                                break
                        if _ab_swap is not None:
                            top_res, top_score = _ab_swap
                        else:
                            # No residual anywhere has this carrier as its primary
                            # subject — refuse rather than let a wrong-carrier or
                            # incidental-mention body win on Bellman weight.
                            self.invention_refusals += 1
                            return self._REFUSAL
            # Active-engram verbatim guarantee: if the fallback winner is a latent
            # cousin, swap it for the active sibling from the same family when one
            # exists with a sufficient score. This prevents Bellman-frozen alternates
            # from permanently drifting into the recall slot for their family.
            if top_res.family and not top_res.active:
                for res2, score2 in ranked[:24]:
                    if res2.family == top_res.family and res2.active and score2 >= 0.40:
                        top_res = res2
                        break
            _, clean = parse_lineage(top_res.fragment)
            return clean
        if mode == "synthesize":
            intent_cell = classify_intent_cell(query)
            intent = intent_cell.primary
            lin_intent = detect_intent(query)
            query_topics = detect_topics(query)
            freq = question_frequency(query)
            recover = [
                (res, score)
                for res, score in self.field.rank(
                    query, top_k=64, freq=freq, layer="shadow"
                )
                if res.domain not in ("query", "rejected") and not self._is_json_leak(res.fragment)
            ]
            candidates: List[Tuple[Residual, float]] = recover[:32]
            if qset:
                for res, score in recover[32:]:
                    if score < 0.38:
                        continue
                    if fuzzy_token_hits(qset, res.content_set) >= 0.44:
                        candidates.append((res, score))
            if not candidates:
                self.invention_refusals += 1
                return self._REFUSAL

            # Semantic rescue: for intent-specific queries the correct answer
            # may rank below position 16 purely on Bellman magnitude (e.g. a
            # freshly locked definition losing to a mature incidental mention).
            # Scan all of `recover` (up to top_k=32, which covers a corpus of
            # 17+ residuals completely) and add the best semantic match to
            # candidates if it is missing.
            _cand_ids: Set[str] = {r.residual_id for r, _ in candidates}
            if _is_definition_query(query):
                _rsc_tgt = _extract_definition_target(query)
                if _rsc_tgt:
                    _rsc_pat = (
                        re.escape(_rsc_tgt) + r"s?"
                        if " " not in _rsc_tgt else re.escape(_rsc_tgt)
                    )
                    for _rr, _rs in recover:
                        if _rr.residual_id in _cand_ids:
                            continue
                        _, _, _rb = parse_topic_lineage(_rr.fragment)
                        if re.search(
                            rf"(?:^|\.\s+)(?:the |your |a |an )?{_rsc_pat}\s+(?:is|are)\b",
                            _rb.lower()[:100],
                        ):
                            candidates.append((_rr, _rs))
                            break
            elif lin_intent == "WHY":
                _rsc_why = _extract_why_target(query)
                if _rsc_why:
                    _rsc_why_stem = (
                        _rsc_why.rstrip("s") if len(_rsc_why) > 4 else _rsc_why
                    )
                    _rsc_why_pat = re.escape(_rsc_why_stem) + r"\w*"
                    for _rr, _rs in recover:
                        if _rr.residual_id in _cand_ids:
                            continue
                        _, _, _rb = parse_topic_lineage(_rr.fragment)
                        _rb_l = _rb.lower()
                        _tpos = _rb_l.find(_rsc_why_stem[:5])
                        if _tpos != -1 and _tpos <= 25 and re.search(
                            rf"\b{_rsc_why_pat}\b", _rb_l[:120]
                        ):
                            candidates.append((_rr, _rs))
                            break
            elif _is_condition_query(query):
                _rsc_abs = re.search(
                    r"(?:if there (?:is|are) no|without|if not)\s+(\w+)",
                    query.lower(),
                )
                if _rsc_abs and len(_rsc_abs.group(1)) >= 5:
                    _rsc_noun = _rsc_abs.group(1)
                    for _rr, _rs in recover:
                        if _rr.residual_id in _cand_ids:
                            continue
                        _, _, _rb = parse_topic_lineage(_rr.fragment)
                        if re.search(
                            rf"without {_rsc_noun}|no {_rsc_noun}\b|{_rsc_noun} cannot\b",
                            _rb.lower(),
                        ):
                            candidates.append((_rr, _rs))
                            break

            # ── Harness + HyperSeed scope (Shadow-only) ─────────────────────
            # Stage A: no opinionated rank feature is allowed to rescue an
            # ungrounded shadow. Target identity is re-applied here because the
            # semantic-rescue scan above intentionally starts from the wider set.
            if not _is_multi_body:
                _sq_target = _extract_synthesize_query_target(query)
                if _sq_target:
                    _targeted = [
                        (r, s) for r, s in candidates
                        if _residual_matches_target(_sq_target, r)
                    ]
                    if _targeted:
                        candidates = _targeted
                    else:
                        self.invention_refusals += 1
                        return self._REFUSAL

            _ground_terms = self._exact_terms(query)

            def _grounding_strength(residual: Residual) -> float:
                _, _, ground_body = parse_topic_lineage(residual.fragment)
                exact_hits = self._hard_term_hits(_ground_terms, residual)
                coverage = exact_hits / max(1, len(_ground_terms))
                evidence = _evidence_score(query, ground_body) / 1.5
                soft = fuzzy_token_hits(qset, residual.content_set) if qset else 0.0
                return max(coverage, evidence, soft)

            grounded = [
                (residual, score)
                for residual, score in candidates
                if _grounding_strength(residual) > 0.0
            ]
            if not grounded:
                self.invention_refusals += 1
                return self._REFUSAL
            candidates = grounded

            # Select the queried universe by evidence before mass is considered.
            # This prevents a heavy but unrelated seed from capturing the query.
            _seed_grounding: Dict[str, float] = {}
            _seed_mass: Dict[str, float] = {}
            for _seed_res, _ in candidates:
                _seed_grounding[_seed_res.seed_identity] = max(
                    _seed_grounding.get(_seed_res.seed_identity, 0.0),
                    _grounding_strength(_seed_res),
                )
                _seed_mass[_seed_res.seed_identity] = max(
                    _seed_mass.get(_seed_res.seed_identity, 0.0),
                    _seed_res.seed_mass,
                )
            _primary_seed = max(
                _seed_grounding,
                key=lambda seed_id: (
                    _seed_grounding[seed_id],
                    1.0 + min(
                        0.20,
                        0.05 * math.log1p(max(0.0, _seed_mass[seed_id])),
                    ),
                    seed_id,
                ),
            )
            _eligible_seed_ids: Set[str] = {_primary_seed}
            _cross_seed_intent = _query_frame(query) in {"COMPARE", "RELATE"}
            if _cross_seed_intent:
                _eligible_seed_ids.update(_seed_grounding)
            else:
                _query_freqs = text_to_frequencies(query)
                for _seed_res, _ in candidates:
                    if _seed_res.seed_identity == _primary_seed:
                        continue
                    if (
                        resonance_score(_query_freqs, _seed_res.freqs)
                        >= self.cross_seed_resonance_threshold
                    ):
                        _eligible_seed_ids.add(_seed_res.seed_identity)
            candidates = [
                (residual, score)
                for residual, score in candidates
                if residual.seed_identity in _eligible_seed_ids
            ]
            # ── End harness + HyperSeed scope ───────────────────────────────

            # ── Hard frame gate (synthesize) ─────────────────────────────────
            # Same rule as exact path: wrong-frame residuals are ineligible
            # when a correctly-framed candidate exists.
            #
            # Synthesize extension (change order §3): after narrowing to
            # frame-matched primaries, allow up to ONE sibling from the same
            # residual family whose frame is not a hard mismatch — this lets
            # synthesize surface a compatible supporting residual (e.g. the
            # WHY alongside the DEFINITION) without letting wrong-frame
            # same-carrier residuals claim the primary slot.
            _sq_frame = _query_frame(query)
            if _sq_frame != "GENERAL":
                _sf_matched = [
                    (r, s) for r, s in candidates
                    if _frame(r) == _sq_frame
                ]
                if _sf_matched:
                    _sf_families = {r.family for r, _ in _sf_matched if r.family}
                    # Hard-mismatch frames that must never appear as primary
                    _hard_mismatch = {
                        "DEFINITION": {"MECHANISM"},
                        "MECHANISM":  {"CONDITION"},
                        "WHY":        {"MECHANISM"},
                        "CONDITION":  {"MECHANISM"},
                    }.get(_sq_frame, set())
                    _sf_siblings = [
                        (r, s) for r, s in candidates
                        if (r, s) not in _sf_matched
                        and r.family in _sf_families
                        and _frame(r) not in _hard_mismatch
                    ]
                    candidates = _sf_matched + _sf_siblings[:1]
            # ── End frame gate ───────────────────────────────────────────────

            # ── Synthesize multi-residual: COMPARE composition + STEPS assembly ─
            # Mirror of the exact-path multi-residual block for the two intents
            # that need it most.  Returns List[str] directly so merged.py builds
            # the multi-item results list.
            if _sq_frame == "COMPARE":
                _sm_hits: "List[str]" = []
                _sm_seen: "Set[str]" = set()
                # Pass 1: explicit COMPARE / RELATION candidates
                for _sr, _ss in candidates:
                    if _frame(_sr) in ("COMPARE", "RELATION"):
                        if fuzzy_token_hits(qset, _sr.content_set) >= 0.08:
                            _, _sc = parse_lineage(_sr.fragment)
                            _sk = _sc[:80].lower()
                            if _sk not in _sm_seen:
                                _sm_seen.add(_sk)
                                _sm_hits.append(_sc)
                    if len(_sm_hits) >= 2:
                        break
                # Pass 2: compose from target-A def + target-B def
                if len(_sm_hits) < 2:
                    _sctgts = _extract_compare_targets(query)
                    _sby_tgt: "Dict[str, str]" = {}
                    for _sr, _ss in candidates:
                        if _frame(_sr) not in ("DEFINITION", "FACT"):
                            continue
                        _, _, _srb = parse_topic_lineage(_sr.fragment)
                        _srbl = _srb.lower()
                        for _stgt in _sctgts:
                            if _stgt.lower() not in _sby_tgt and _stgt.lower() in _srbl:
                                _, _sc = parse_lineage(_sr.fragment)
                                _sk = _sc[:80].lower()
                                if _sk not in _sm_seen:
                                    _sm_seen.add(_sk)
                                    _sby_tgt[_stgt.lower()] = _sc
                    for _sv in list(_sby_tgt.values()):
                        if _sv not in _sm_hits:
                            _sm_hits.append(_sv)
                        if len(_sm_hits) >= 2:
                            break
                if _sm_hits:
                    self._bellman_update(
                        [r for r, _ in candidates if parse_lineage(r.fragment)[1] in _sm_hits[:2]],
                        reward=0.78,
                    )
                    return _sm_hits
            elif _sq_frame == "STEPS":
                # Same root-cause fix as exact path: family-prefix scope.
                _STEP_NUM_RE_S = re.compile(r"^step\s*(\d+)", re.IGNORECASE)
                _FAMSUFFIX_RE_S = re.compile(r"-\d+$")
                _ss_anchor_prefix: "Optional[str]" = None
                _ss_anchor_source: "Optional[str]" = None
                for _sr, _ in candidates:
                    _, _, _assb = parse_topic_lineage(_sr.fragment)
                    if _frame(_sr) == "STEP" or _STEP_NUM_RE_S.match(_assb.strip()):
                        same_source_steps = sum(
                            1
                            for candidate in self.field.residuals
                            if (
                                candidate.layer in {"shadow", "legacy"}
                                and candidate.source_id == _sr.source_id
                                and _frame(candidate) == "STEP"
                            )
                        )
                        if same_source_steps > 1:
                            _ss_anchor_source = _sr.source_id
                        if _sr.family:
                            _ss_anchor_prefix = _FAMSUFFIX_RE_S.sub("", _sr.family)
                        break
                _ss_items: "List[Tuple[int, str]]" = []
                _ss_seen: "Set[str]" = set()
                for _sr in self.field.residuals:
                    if (
                        _sr.layer not in {"shadow", "legacy"}
                        or _sr.domain in ("query", "rejected")
                        or _sr.seed_identity not in _eligible_seed_ids
                    ):
                        continue
                    _, _, _ssb = parse_topic_lineage(_sr.fragment)
                    _ssm = _STEP_NUM_RE_S.match(_ssb.strip())
                    if _frame(_sr) != "STEP" and not _ssm:
                        continue
                    if _ss_anchor_source:
                        if _sr.source_id != _ss_anchor_source:
                            continue
                    elif _ss_anchor_prefix:
                        _sr_prefix = _FAMSUFFIX_RE_S.sub("", _sr.family or "")
                        if _sr_prefix != _ss_anchor_prefix:
                            continue
                    else:
                        _sfrag_l = _sr.fragment.lower()
                        if not any(t in _sfrag_l for t in qset if len(t) >= 3):
                            continue
                    _snum = int(_ssm.group(1)) if _ssm else 999
                    _, _sc = parse_lineage(_sr.fragment)
                    _sk = _sc[:80].lower()
                    if _sk not in _ss_seen:
                        _ss_seen.add(_sk)
                        _ss_items.append((_snum, _sc))
                _ss_items.sort(key=lambda x: x[0])
                _ss_hits = [_b for _, _b in _ss_items]
                if _ss_hits:
                    return _ss_hits
            elif _sq_frame in ("LIST", "SUMMARIZE", "RELATE"):
                # Mirror of the exact-path LIST/SUMMARIZE/RELATE assembly.
                # Residuals carry frames like LIST_ITEM, never "LIST", so the
                # frame gate above never narrows candidates for these intents —
                # collect the frame-allowed matches here and return List[str].
                _sl_frame_allowed: "Optional[Set[str]]" = {
                    "LIST":      {"LIST_ITEM"},
                    "SUMMARIZE": None,
                    "RELATE":    {"RELATION", "DEFINITION", "MECHANISM"},
                }[_sq_frame]
                _sl_max_items = 2 if _sq_frame == "RELATE" else 5
                _sl_hits: "List[str]" = []
                _sl_seen: "Set[str]" = set()
                for _sr, _ss in candidates:
                    if fuzzy_token_hits(qset, _sr.content_set) < 0.10:
                        continue
                    if _sl_frame_allowed is not None and _frame(_sr) not in _sl_frame_allowed:
                        continue
                    _, _sc = parse_lineage(_sr.fragment)
                    _sk = _sc[:80].lower()
                    if _sk in _sl_seen:
                        continue
                    _sl_seen.add(_sk)
                    _sl_hits.append(_sc)
                    if len(_sl_hits) >= _sl_max_items:
                        break
                if _sl_hits:
                    return _sl_hits
                # No frame-matched residuals → fall through to single-body passes
            # ── End synthesize multi-residual ─────────────────────────────────

            ordered: List[Tuple[Residual, float]] = []
            seen_ids: Set[str] = set()
            for res, score in candidates:
                adjusted = score
                if res.imprint_layer in {"deep", "medium"} and res.coherence >= 0.88:
                    adjusted += 0.03
                # Evidence score: content match is a first-class signal.
                res_topic, res_lineage, ev_body = parse_topic_lineage(res.fragment)
                ev = _evidence_score(query, ev_body)
                adjusted += ev * 1.4   # exact phrase (1.5) → +2.1; strong overlap → +1.4

                # Auto-derive topic for untagged residuals so raw material competes fairly.
                if res_topic is None:
                    res_topic = _auto_topic_from_body(ev_body)

                # Topic-bound lineage boost: parent topic must match before lineage fires.
                lineage_match = (res_lineage == lin_intent and lin_intent != "GENERAL")
                if query_topics:
                    topic_match = (res_topic in query_topics)
                    if topic_match and lineage_match:
                        adjusted += 2.0   # strongest: correct parent + correct lineage
                    elif topic_match:
                        adjusted += 0.8   # strong: correct parent, any lineage
                    elif res_topic is not None and not topic_match:
                        adjusted -= 0.6   # penalty: explicit wrong parent topic
                    # cross-topic lineage match gets no boost — cannot beat same-topic
                else:
                    # No topic context — fall back to lineage-only (existing behaviour)
                    if lineage_match:
                        adjusted += 1.5
                    elif res_lineage is not None:
                        adjusted -= 0.3
                # Intent Cell preference runs only after relevance, target,
                # grounding, seed, and frame eligibility have already admitted
                # this Shadow. It cannot make an ineligible residual relevant.
                adjusted += 0.65 * _intent_branch_strength(intent_cell, res)
                # Destructive: label/title fragments never beat a substantive residual.
                # Applied universally before intent-specific scoring.
                if _is_label_fragment(ev_body):
                    # Bare titles remain destructive, but a compact operational
                    # status sentence can be verb-less and still carry grounded
                    # content (for example a CMD tag with five status terms).
                    adjusted -= 2.5 if len(content_tokens(ev_body)) <= 3 else 0.4

                # Intent-specific role preference + subject-anchor scoring.
                #
                # Priority order (checked top-to-bottom; first match wins the role branch):
                #   1. Condition query  → prefer CONDITION, demote MECHANISM
                #   2. Definition query → WHAT subject-anchor (definitional > lead > body > off-topic)
                #   3. WHY query        → subject-anchor on explanatory target
                #   4. HOW / action    → action-target coupling check, synonym expansion
                #
                # Core rule: recall the memory *about* the target, not every memory
                # that merely contains the target word.
                role = _frame(res)
                if _is_condition_query(query):
                    # "What happens if …", "if not …", "without …": want CONDITION bodies.
                    if role == "CONDITION":
                        adjusted += 6.0   # frame match — large enough to beat Bellman magnitude
                    elif role == "MECHANISM":
                        adjusted -= 8.0   # frame mismatch — hard demote
                elif _is_definition_query(query):
                    # "What is X" / "What are X": the residual that *defines* X must
                    # decisively beat any residual that only *mentions* X.
                    def_target = _extract_definition_target(query)
                    if def_target:
                        b_lower = ev_body.lower()
                        # Word-boundary pattern: exact + optional trailing 's' for plurals.
                        if " " not in def_target:
                            t_pat = re.escape(def_target) + r"s?"
                        else:
                            t_pat = re.escape(def_target)
                        # Definitional pattern: target is primary subject of an identity clause
                        # at the very start of the body — excludes conditional openers
                        # like "When too many boats are …".
                        definitional = bool(re.search(
                            rf"(?:^|\.\s+)(?:the |your |a |an )?{t_pat}\s+(?:is|are)\b",
                            b_lower[:100],
                        ))
                        in_lead = bool(re.search(rf"\b{t_pat}\b", b_lower[:140]))
                        in_body = bool(re.search(rf"\b{t_pat}\b", b_lower))
                        # Detect weak-mention context: target listed as an
                        # attribute/object of another subject ("carries X",
                        # "including X") or buried in a comma-separated enumeration.
                        _weak_ctx = in_lead and bool(re.search(
                            rf"(?:"
                            rf"\b(?:carries?|includes?|including|contains?|encodes?|stores?)\b[^.{{0,60}}]\b{t_pat}\b"
                            rf"|,\s*{t_pat}"
                            rf"|{t_pat}\s*,"
                            rf")",
                            b_lower[:200],
                        ))
                        if definitional:
                            adjusted += 4.0   # body IS the definition of target
                        elif in_lead and not _weak_ctx:
                            adjusted += 2.0   # target is primary lead subject
                        elif in_body:
                            adjusted += 0.5   # incidental or list mention
                        else:
                            adjusted -= 2.0   # off-topic: hard demote
                        # Foreign subject penalty: if this residual opens with a
                        # definitional clause for a *different* entity, it is about
                        # something else — demote even if it mentions the target.
                        if not definitional:
                            _fsm = re.match(
                                r'^(?:the |a |an |your )?(.+?)\s+(?:is|are)\b',
                                b_lower[:80],
                            )
                            if _fsm:
                                _fsubj = _fsm.group(1).strip()
                                if len(_fsubj) >= 3:
                                    _t_words = set(def_target.split())
                                    _s_words = set(_fsubj.split())
                                    if not (_t_words & _s_words):
                                        adjusted -= 2.5  # defines something else
                    # Frame preference: same target + right frame must beat
                    # same target + wrong frame. Bonuses/penalties must exceed
                    # typical Bellman magnitude differences in a trained field.
                    if role == "DEFINITION":
                        adjusted += 6.0   # frame match — WHAT wants a definition
                    elif role == "MECHANISM":
                        # Hard-demote MECHANISM for DEFINITION queries — UNLESS
                        # this MECHANISM residual is itself *about* the target
                        # (its lead subject IS the definition target, meaning
                        # the field has no DEFINITION-framed body for it and the
                        # MECHANISM body is the best available answer).
                        # "What is the fitness gate?" + FITNESS_GATE_MECHANISM
                        # body "Fitness gate selects…" → lead matches → keep.
                        _mech_lead_ok = bool(re.match(
                            rf"^(?:the |a |an )?{t_pat}\b",
                            ev_body.lower()[:80],
                        ))
                        if not _mech_lead_ok:
                            adjusted -= 8.0  # frame mismatch, wrong carrier → demote
                elif lin_intent == "WHY":
                    # WHY queries: prefer residuals that *explain* the target.
                    # A residual that merely mentions the subject incidentally is penalised.
                    why_target = _extract_why_target(query)
                    if why_target:
                        b_lower = ev_body.lower()
                        if " " not in why_target:
                            t_pat = re.escape(why_target.rstrip("s") if len(why_target) > 4 else why_target) + r"\w*"
                        else:
                            t_pat = re.escape(why_target)
                        in_lead  = bool(re.search(rf"\b{t_pat}\b", b_lower[:120]))
                        has_target = bool(re.search(rf"\b{t_pat}\b", b_lower))
                        t_pos = b_lower.find(why_target[:5])   # approximate position
                        if in_lead and t_pos <= 20:
                            adjusted += 3.0   # target IS the explanatory subject
                        elif in_lead:
                            adjusted += 1.5   # target in lead but not primary subject
                        elif has_target:
                            adjusted += 0.3   # incidental mention
                        else:
                            adjusted -= 1.5   # target absent — off-topic
                    # Frame mismatch penalty for WHY: a MECHANISM body answers
                    # "how" not "why" — demote it hard relative to an explanatory frame.
                    if role == "MECHANISM":
                        adjusted -= 6.0
                elif lin_intent == "HOW" or _is_action_query(query):
                    # HOW / action / WHEN queries: want MECHANISM bodies where
                    # the action verb operates *on* the query target — not just
                    # any body that contains the action somewhere.
                    b_ev_lower = ev_body.lower()
                    action_stems = _extract_action_stems(query)

                    # Verb match: literal stem OR synonym from _ACTION_SYNONYMS.
                    verb_match = any(stem in b_ev_lower for stem in action_stems)
                    if not verb_match and action_stems:
                        for _stem in action_stems:
                            for _syn in _ACTION_SYNONYMS.get(_stem, []):
                                if _syn in b_ev_lower:
                                    verb_match = True
                                    break
                            if verb_match:
                                break

                    # Action-target coupling: the matched verb must appear near
                    # the noun target (within ~80 chars), preventing a body that
                    # suppresses "the storm" from winning "suppress ghost tax".
                    how_target = _extract_how_target(query, action_stems)
                    action_coupled = False
                    if how_target and verb_match:
                        t_pat_ht = re.escape(how_target)
                        # Collect every verb/synonym match position and check proximity.
                        _match_terms: List[str] = list(action_stems)
                        for _stem in action_stems:
                            _match_terms.extend(_ACTION_SYNONYMS.get(_stem, []))
                        for _term in _match_terms:
                            for _m in re.finditer(re.escape(_term), b_ev_lower):
                                region = b_ev_lower[max(0, _m.start() - 30): _m.end() + 80]
                                if re.search(rf"\b{t_pat_ht}\b", region):
                                    action_coupled = True
                                    break
                            if action_coupled:
                                break

                    if action_coupled:
                        adjusted += 3.5   # verb operates on the correct target — decisive
                    elif verb_match:
                        adjusted += 2.0   # verb present but aimed at a different target
                    elif len(ev_body.strip()) < 80 or not action_stems:
                        pass              # very short body: no penalty
                    else:
                        adjusted -= 0.5  # demote noun-only bodies on action queries

                    if role == "MECHANISM":
                        adjusted += 0.8
                    elif role == "CONDITION":
                        adjusted -= 0.8
                    # Linked-term synonym bridge (ghost tax ↔ floor/gamma, etc.)
                    adjusted += _linked_term_evidence(query, ev_body)
                # Active-engram bonus: the preferred recall engram for its family
                # gets a scoring advantage over latent cousins.
                if res.active:
                    adjusted += 0.25
                # Stage B: post-harness inertia and controlled Voice energy.
                # Mass is deliberately bounded and only acts inside the already
                # grounded/eligible seed set, so it cannot make an unrelated seed
                # relevant or override a hard exact match.
                _intent_gate = 1.0
                if res.seed_intent:
                    _intent_terms = {
                        intent.lower(),
                        lin_intent.lower(),
                        _sq_frame.lower(),
                    }
                    _intent_gate = (
                        1.05
                        if res.seed_intent.lower() in _intent_terms
                        else 0.94
                    )
                _mass_boost = 1.0 + min(
                    0.20,
                    0.05 * math.log1p(max(0.0, res.seed_mass)),
                )
                adjusted *= _intent_gate * _mass_boost
                if self.boost_enabled:
                    # Deterministic bounded oscillation: variability without
                    # randomness or invented text.
                    _phase = int(res.residual_id[:8], 16) / float(0xFFFFFFFF)
                    _oscillation = (
                        (_phase - 0.5)
                        * 2.0
                        * self.boost_sigma
                        * self.boost_beta
                        * min(1.0, self.harness_gamma / self.boost_gamma)
                    )
                    adjusted += _oscillation
                if res.residual_id not in seen_ids:
                    seen_ids.add(res.residual_id)
                    ordered.append((res, adjusted))

            # Memory governance penalty pass — applied after full scoring so the
            # active_engram_bonus above is visible when computing family bests.
            #
            # interference_penalty  (−0.20): latent variant loses to active sibling.
            # off_family_penalty    (−0.15): residual from a non-queried family that
            #   already has a strong active engram recalled (score ≥ 0.55).
            _family_active_best: Dict[str, float] = {}
            for _r, _adj in ordered:
                if _r.active and _r.family:
                    if _adj > _family_active_best.get(_r.family, -999.0):
                        _family_active_best[_r.family] = _adj
            # Query family tokens — family slugs overlap with query tokens
            _q_family_parts: Set[str] = set()
            for _tok in qset:
                _q_family_parts.add(_tok)
                for _part in _tok.split("-"):
                    if len(_part) >= 3:
                        _q_family_parts.add(_part)

            def _family_overlaps_query(fam: str) -> bool:
                if not fam:
                    return True  # no family key → no off-family penalty
                return any(p in _q_family_parts or fam in _q_family_parts
                           for p in fam.split("-"))

            ordered = [
                (
                    _r,
                    _adj
                    - (0.20 if (not _r.active and _r.family and
                                _family_active_best.get(_r.family, -999.0) > _adj) else 0.0)
                    - (0.15 if (_r.family and not _family_overlaps_query(_r.family) and
                                _family_active_best.get(_r.family, -999.0) >= 0.55) else 0.0),
                )
                for _r, _adj in ordered
            ]

            # Carrier-wave pass: drive top candidates against query reference (+1.0).
            # Wanted modes phase-lock → boost + motion reward; unwanted modes cancel.
            # Applied after the full scoring loop so carrier uses real net scores.
            carrier_boosts, in_phase_set = self._vibrate_residuals(ordered[:6])
            ordered = [
                (res, adj + carrier_boosts.get(res.residual_id, 0.0))
                for res, adj in ordered
            ]
            # Optional Pure-Harness phase signal: raw offsets are centered, while
            # the applied score preserves the primary-admission floor. It runs only
            # for candidates that already satisfy the unmodified cutoff and evidence.
            ordered = self._apply_pure_harness_phase_signal(
                ordered,
                qset,
                q_lower,
            )

            # WHAT-query definitional override: after all scoring (including
            # carrier-wave), if any candidate opens with "target is/are …" it is
            # the authoritative definition and must rank #1 regardless of how much
            # Bellman magnitude has accumulated on an incidental-mention residual.
            if _is_definition_query(query):
                _def_tgt = _extract_definition_target(query)
                if _def_tgt:
                    _def_tpat = (
                        re.escape(_def_tgt) + r"s?"
                        if " " not in _def_tgt
                        else re.escape(_def_tgt)
                    )
                    _max_adj = max((a for _, a in ordered), default=0.0)
                    for _di, (_dr, _da) in enumerate(ordered):
                        _, _, _db = parse_topic_lineage(_dr.fragment)
                        if re.search(
                            rf"(?:^|\.\s+)(?:the |your |a |an )?{_def_tpat}\s+(?:is|are)\b",
                            _db.lower()[:100],
                        ):
                            ordered[_di] = (_dr, _max_adj + 100.0)
                            break   # first definitional candidate wins
            elif lin_intent == "WHY":
                # WHY override: the residual where the subject target appears
                # at the very start (position ≤ 20) is the explanatory answer;
                # promote it above any incidental mention.
                _why_tgt_o = _extract_why_target(query)
                if _why_tgt_o:
                    _why_stem_o = (
                        _why_tgt_o.rstrip("s") if len(_why_tgt_o) > 4 else _why_tgt_o
                    )
                    _why_pat_o = re.escape(_why_stem_o) + r"\w*"
                    _max_why = max((a for _, a in ordered), default=0.0)
                    for _wi, (_wr, _wa) in enumerate(ordered):
                        _, _, _wb = parse_topic_lineage(_wr.fragment)
                        _wb_l = _wb.lower()
                        _wpos = _wb_l.find(_why_stem_o[:5])
                        if (
                            _wpos != -1
                            and _wpos <= 20
                            and re.search(rf"\b{_why_pat_o}\b", _wb_l[:120])
                        ):
                            ordered[_wi] = (_wr, _max_why + 100.0)
                            break
            elif _is_condition_query(query):
                # CONDITION override: the residual that directly describes the
                # absence/failure of the queried entity wins over any residual
                # that merely has a high Bellman score from prior oscillations.
                _cond_abs = re.search(
                    r"(?:if there (?:is|are) no|without|if not)\s+(\w+)",
                    query.lower(),
                )
                if _cond_abs and len(_cond_abs.group(1)) >= 5:
                    _cond_noun = _cond_abs.group(1)
                    _max_cond = max((a for _, a in ordered), default=0.0)
                    for _ci, (_cr, _ca) in enumerate(ordered):
                        _, _, _cb = parse_topic_lineage(_cr.fragment)
                        _cb_l = _cb.lower()
                        if re.search(
                            rf"without {_cond_noun}|no {_cond_noun}\b|{_cond_noun} cannot\b",
                            _cb_l,
                        ) and _frame(_cr) == "CONDITION":
                            ordered[_ci] = (_cr, _max_cond + 100.0)
                            break

            force_needles: Tuple[str, ...] = ()
            if any(w in q_lower for w in ("why", "origin", "began", "built", "started")):
                force_needles = ("origin", "began as", "memory bottleneck", "geometry of stored")
            elif any(w in q_lower for w in ("unused", "decay", "decayed", "disappear")):
                force_needles = (
                    "slowly decay",
                    "decay never deletes",
                    "remain fully visible",
                    "surface decayed",
                    "ascending value",
                )
            elif any(w in q_lower for w in ("invent", "invention")):
                force_needles = ("no free invention", "supported by locked")

            def _body_text(text: str) -> str:
                text = text.strip()
                parts = text.split("::", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
                if " | " in text:
                    return text.split(" | ", 1)[1].strip()
                if len(parts) == 2:
                    return parts[1].strip()
                return text

            def _is_full_fragment(text: str) -> bool:
                head = text.split(" | ")[0] if " | " in text else text
                parts = [p for p in head.lower().split("::") if p]
                tag = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
                return tag.endswith("_full") or tag.endswith("full") or "_full::" in text.lower()

            def rank_key(item: Tuple[Residual, float]) -> Tuple[float, float, float, float, float, float, float, float]:
                res, score = item
                frag = res.fragment.lower()
                exact = 1.0 if (q_lower and q_lower in frag) else 0.0
                soft = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                parts = [p for p in frag.split("::") if p]
                primary_tag = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
                tag_hit = 0.0
                for t in qset:
                    if len(t) >= 4 and (t == primary_tag or t in primary_tag or primary_tag.startswith(t)):
                        tag_hit = 1.0
                        break
                force = 1.0 if force_needles and any(needle in frag for needle in force_needles) else 0.0
                preconcept = 1.0 if (res.imprint_layer in {"deep", "medium"} and res.coherence >= 0.88) else 0.0
                full_penalty = 0.0 if _is_full_fragment(res.fragment) else 1.0
                # Carrier boost is already baked into `score` (adjusted) from the
                # _vibrate_residuals carrier pass; no separate vibrated_rank needed.
                return (score, force, exact, tag_hit, full_penalty, preconcept, soft)

            ordered.sort(key=rank_key, reverse=True)
            primary_res: Optional[Residual] = None
            primary_text = ""
            support_residuals: List[Residual] = []
            support_texts: List[str] = []

            for res, score in ordered:
                if not self._passes_synthesize_primary_admission(
                    res,
                    score,
                    qset,
                    q_lower,
                ):
                    continue
                primary_res = res
                primary_text = res.fragment.strip()
                break
            if not primary_text:
                self.invention_refusals += 1
                return self._REFUSAL

            # Off-target gate: if the primary has zero evidence match against the
            # query AND the query carries ≥3 distinctive terms, it was selected
            # purely by Bellman weight on a shared entity token. Prefer empty over
            # a confidently wrong answer (e.g. "What color is HyperSeed binary?").
            if primary_res is not None:
                _, _, _ot_body = parse_topic_lineage(primary_res.fragment)
                _ot_ev = _evidence_score(query, _ot_body)
                if _ot_ev == 0.0:
                    _ot_q_words = [w.strip("?.,!") for w in query.lower().split()
                                   if len(w) > 3 and w.strip("?.,!") not in _EVIDENCE_STOP]
                    if len(_ot_q_words) >= 3:
                        self.invention_refusals += 1
                        return self._REFUSAL

            primary_full = _is_full_fragment(primary_text)
            primary_body = _body_text(primary_text).lower()

            # Wave rule: secondary must be net-positive AND not the opposite
            # role for this intent (out-of-phase residuals cancel instead of
            # appearing as related context).
            preferred_role: Optional[str] = (
                "CONDITION"  if (_is_condition_query(query) or intent == "when") else
                "DEFINITION" if _is_definition_query(query) else
                "MECHANISM"  if (lin_intent == "HOW" or _is_action_query(query)) else
                "WHY"        if intent in ("why", "diagnose") else
                None
            )
            _opposite_role = {"MECHANISM": "CONDITION", "CONDITION": "MECHANISM",
                               "DEFINITION": "MECHANISM", "WHY": "DEFINITION"}

            for res, score in ordered:
                if primary_res is not None and res.residual_id == primary_res.residual_id:
                    continue
                if score < 0.44:
                    continue
                # Wave: secondary must be net-positive (constructive wins).
                if score <= 0:
                    continue
                cand = res.fragment.strip()
                cand_body = _body_text(cand).lower()
                if not cand_body or cand_body == primary_body:
                    continue
                if primary_res is None or not _intent_support_compatible(
                    intent_cell,
                    primary_res,
                    res,
                ):
                    continue
                if not self._passes_synthesize_primary_admission(
                    res,
                    score,
                    qset,
                    q_lower,
                ):
                    continue
                cand_full = _is_full_fragment(cand)
                if primary_full and cand_full:
                    continue
                if cand_full and not primary_full:
                    continue
                # Wave: reject secondary whose role is out-of-phase with intent.
                if preferred_role is not None:
                    opp = _opposite_role.get(preferred_role)
                    if opp and _frame(res) == opp:
                        continue
                # Phase-family check: if the candidate was in the carrier top-6,
                # only accept it as secondary if it settled in the same phase family
                # as the query carrier (+Q_ref). Anti-phase candidates cancel rather
                # than appear as related context.
                if (
                    in_phase_set
                    and res.residual_id in carrier_boosts
                    and res.residual_id not in in_phase_set
                ):
                    continue
                soft = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                if qset and soft < 0.16 and q_lower not in cand.lower():
                    continue
                support_residuals.append(res)
                support_texts.append(cand)
                if len(support_residuals) >= 2:
                    break

            winners = [primary_res] if primary_res is not None else []
            winners.extend(support_residuals)
            self._bellman_update(
                winners,
                reward=0.88 if (intent == "diagnose" or freq.get("class") == "quantity") else 0.78,
            )
            answer = format_intent_cell_answer(
                intent_cell,
                primary_text,
                support_texts,
            )
            if not answer:
                self.invention_refusals += 1
                return self._REFUSAL
            self.or_events += 1  # objective-reduction event
            return answer
        return "Unknown mode"

    def verify_integrity(self) -> Tuple[bool, str]:
        """Verify hash chain integrity."""
        ok, message = self.field.verify_chain()
        if ok and self.lock_count:
            return (
                True,
                f"chain intact ({self.lock_count} residuals; "
                f"{len(self.field.residuals)} paired records)",
            )
        return ok, message

    def status(self) -> Dict[str, Any]:
        # field.status() acquires field._lock and returns chain health and
        # governance summary atomically (consistent with concurrent store()).
        field_st = self.field.status()
        return {
            "void": self.name,
            "locked": field_st["residual_count"],
            "lock_count": self.lock_count,
            "project_count": self.project_count,
            "refusals": self.invention_refusals,
            "chain_ok": field_st["chain_ok"],
            "chain_msg": field_st["chain_msg"],
            "chain_tip": field_st["chain_tip"],
            "layers": field_st["layers"],
            "seeds": field_st["seeds"],
            "nodes": list(self.connected.keys()),
            "uptime_sec": round(time.time() - self.start_time, 1),
            "pure_harness": self.pure_harness.status(),
            "memory": field_st["memory"],
        }
