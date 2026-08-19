from __future__ import annotations

import re
from typing import Dict, List, Optional, Protocol

# ---------------------------------------------------------------------------
# Write-time frame classifier for auto_segment()
# ---------------------------------------------------------------------------
# Inlined here (not imported from core) to avoid circular imports.
# Mirrors _classify_residual_role() — keep in sync if that changes.
_FRAME_CONDITION_RE = re.compile(
    r"^(if |without |when there'?s? no |unless )"
    r"|\b(if there is no|without any|when .{0,25} (drops|fails|is removed|is absent))\b",
    re.IGNORECASE,
)
_FRAME_MECHANISM_RE = re.compile(
    r"\b(harness mode|auditor mode)\b"
    r"|\b(raises|restores|suppresses|detects|couples|tunes|maintains|applies"
    r"|activates|increases|decreases|boosts|dampens|amplifies|re-synchroni"
    r"|modulates?|synchroni\w+|drives?\b)\b"
    r"|\bby (increasing|coupling|raising|tuning|locking|suppressing|restoring"
    r"|detecting|applying|activating|synchroni\w+)\b"
    r"|\bworks? by\b|\bfunctions? by\b|\boperates? by\b",
    re.IGNORECASE,
)
_FRAME_DEFINITION_RE = re.compile(
    r"\b(is the|is a|is an|are the|are a|is your|are your|refers to|defined as)\b",
    re.IGNORECASE,
)
_FRAME_WHY_RE = re.compile(
    r"\b(creates?|leads? to|because|results? in|produces?|causes?)\b"
    r"|\b(high|low)\s+\w+\s+(creates?|produces?|leads?)\b"
    r"|\b(coherent path|incoherent|turbulent|fragment|collective memory)\b",
    re.IGNORECASE,
)
_FRAME_SUFFIXES = frozenset(
    ("DEFINITION", "MECHANISM", "CONDITION", "WHY",
     "HOW", "WHAT", "WHATIF", "WHEN", "WHERE", "WHO",
     "EFFECT", "LIMIT", "COMPARE", "EXAMPLE", "RELATION",
     "LIST_ITEM", "STEP", "FACT")
)


# Expanded speech-act classes (change order: expanded query intent router)
_FRAME_STEP_RE = re.compile(
    r"^\s*(step \d+[:.]|first[,:]?\s+(you|we)|to begin[,:]?\s|to start[,:]?\s)"
    r"|\b(then (you|we)|next[,:]?\s+(you|we)|finally[,:]?\s+(the|you|we))\b",
    re.IGNORECASE,
)
_FRAME_FACT_RE = re.compile(
    r"\b(approximately|about \d|roughly \d+|equal to|per cent|\d+\s*%"
    r"|is (always|never|exactly|only))\b",
    re.IGNORECASE,
)


def _auto_frame_tag(body: str) -> str:
    """Return the speech-act frame suffix for a body, or '' if GENERAL.

    Priority (top-to-bottom; first match wins):
      CONDITION > STEP > MECHANISM > FACT > DEFINITION > WHY
    STEP is detected before MECHANISM because a body that opens with
    'Step 1:' is a STEP regardless of its action verbs.
    """
    b = body.strip()
    if _FRAME_CONDITION_RE.search(b):
        return "CONDITION"
    if _FRAME_STEP_RE.search(b):
        return "STEP"
    if _FRAME_MECHANISM_RE.search(b):
        return "MECHANISM"
    if _FRAME_FACT_RE.search(b):
        return "FACT"
    if _FRAME_DEFINITION_RE.search(b):
        return "DEFINITION"
    if _FRAME_WHY_RE.search(b):
        return "WHY"
    return ""


class _LockingVoid(Protocol):
    def lock(
        self,
        text: str,
        domain: str = "general",
        protect: bool = True,
        shell: int | None = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
        identity: Optional[str] = None,
        scale: float = 1.0,
        density: float = 1.0,
        mass: Optional[float] = None,
        intent: str = "",
        shadow_texts: Optional[List[str]] = None,
    ) -> str: ...


def auto_segment(text: str, domain: str = "DOC", min_len: int = 12) -> List[str]:
    """Dense-raw-aware segmenter v2.3.
    Decimal-safe, missing-space-after-period fix, sentence fallback.
    Exact body storage. Atomic units for frequency / oscillation imprint.
    """
    text = text.replace("\r\n", "\n").strip()
    text = re.sub(r"(\d)\.(\d)", r"\1DECIMAL\2", text)
    text = re.sub(r"(?<=[.!?])(?=[A-Z])", " ", text)
    text = text.replace("DECIMAL", ".")

    parts = re.split(
        r"\n(?=#{1,4}\s|\d+\.\s+[A-Za-z]|[A-Z][A-Za-z0-9 \-/]{2,40}:\s|[A-Z][A-Z0-9 \-]{3,}:\s|Error\s+Code|Procedure:)",
        text,
    )
    if len(parts) < 3:
        parts = re.split(r"\n\s*\n+", text)
    if len(parts) < 2:
        parts = re.split(r"(?<=[.!?])\s+", text)

    final_parts: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 140 or (p.count(". ") + p.count("! ") + p.count("? ") >= 1 and len(p) > 40):
            p2 = re.sub(r"(\d)\.(\d)", r"\1DECIMAL\2", p)
            bits = re.split(r"(?<=[.!?])\s+", p2)
            for b in bits:
                final_parts.append(b.replace("DECIMAL", ".").strip())
        else:
            final_parts.append(p)

    # Anaphoric pronoun merge: a segment opening with an unresolved pronoun
    # (It/This/These/They/Its/That/Those) loses its subject after splitting.
    # Example: "A HyperSeed is … 200 bytes. It carries Ghost Tax, …"
    #           → without merge, "It carries Ghost Tax" becomes a fake ghost-tax memory.
    # Fix: append such segments to the preceding segment instead of creating a new residual.
    _ANAPHORIC_RE = re.compile(r'^(?:it|this|these|they|its|that|those)\b', re.IGNORECASE)
    merged_parts: List[str] = []
    for _part in final_parts:
        if merged_parts and _ANAPHORIC_RE.match(_part.strip()):
            merged_parts[-1] = merged_parts[-1].rstrip() + " " + _part.strip()
        else:
            merged_parts.append(_part)
    final_parts = merged_parts

    residuals: List[str] = []
    seen = set()
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was", "will", "can", "how", "what",
        "when", "must", "should", "unit", "models", "some", "every", "change", "inspect", "test",
        "use", "always", "verify", "a", "an", "is", "of", "to", "in", "on", "by", "i", "my", "me", "it",
    }
    for i, part in enumerate(final_parts):
        part = part.strip()
        if len(part) < min_len:
            continue
        lines = [l.strip() for l in part.split("\n") if l.strip()]
        if not lines:
            continue
        first = re.sub(r"^#{1,4}\s*|\d+\.\s*|:\s*$", "", lines[0])
        words = re.findall(r"[A-Za-z0-9]+", first)
        words = [w for w in words if len(w) > 2 and w.lower() not in stop]
        tag = "_".join(w.upper() for w in words[:4]) if words else f"SEC_{i+1:02d}"
        tag = re.sub(r"[^A-Z0-9_]", "", tag)[:26]
        body = " ".join(lines)
        key = body[:90].lower()
        if key in seen:
            continue
        seen.add(key)
        # Write-time frame tag: append speech-act frame suffix to the
        # auto-generated tag so that inject() produces structured tags like
        # DOC::GHOST_TAX_DEFINITION::body instead of DOC::GHOST_TAX::body.
        # This makes the frame gate in project() O(1) (tag lookup) instead of
        # a regex scan on the body, and eliminates the isolation-vs-dense-corpus
        # gap where free-text frame inference fails under Bellman competition.
        # Only append if the tag doesn't already carry a recognised frame suffix.
        _tag_upper = tag.upper()
        if not any(_tag_upper.endswith(f"_{fs}") or _tag_upper == fs
                   for fs in _FRAME_SUFFIXES):
            _frame = _auto_frame_tag(body)
            if _frame:
                tag = f"{tag}_{_frame}"
        residuals.append(f"{domain}::{tag}::{body}")
    return residuals


_PAYLOAD_KEYS = frozenset((
    "full_text", "domain", "protect", "title", "identity",
    "scale", "density", "mass", "intent",
))


def _looks_like_json_payload(text: str) -> bool:
    """Return True if text appears to be a raw HTTP request body rather than plain text."""
    t = text.strip()
    if not t.startswith("{"):
        return False
    import json as _j
    try:
        parsed = _j.loads(t)
        return isinstance(parsed, dict) and bool(_PAYLOAD_KEYS & set(parsed.keys()))
    except Exception:
        return False


def inject_document(
    void: _LockingVoid,
    full_text: str,
    domain: str = "DOC",
    title: str = "SOURCE",
    protect: bool = True,
    identity: Optional[str] = None,
    scale: float = 1.0,
    density: float = 1.0,
    mass: Optional[float] = None,
    intent: str = "",
) -> Dict[str, int]:
    # Guard: if caller accidentally passed the whole JSON body, extract the text value.
    if _looks_like_json_payload(full_text):
        import json as _j
        try:
            parsed = _j.loads(full_text.strip())
            full_text = str(parsed.get("full_text", "")).strip()
        except Exception:
            return {"segments": 0, "locked": 0}
    full_text = full_text.strip()
    if len(full_text) < 20:
        return {"segments": 0, "locked": 0}
    # Preserve the complete input once as immutable Source; use only the atomic
    # segments as ranked Shadows.
    segments = auto_segment(full_text, domain=domain)
    if not segments:
        return {"segments": 0, "locked": 0, "sources": 0, "shadows": 0}
    result = void.lock(
        full_text,
        domain=domain.lower(),
        protect=protect,
        imprint_layer="deep",
        coherence=0.97,
        shell=2,
        identity=identity or title or domain,
        scale=scale,
        density=density,
        mass=mass,
        intent=intent,
        shadow_texts=segments,
    )
    success = result == "locked"
    return {
        "segments": len(segments),
        "locked": len(segments) if success else 0,
        "sources": 1 if success else 0,
        "shadows": len(segments) if success else 0,
    }
