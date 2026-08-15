from __future__ import annotations

import re
from typing import Dict, List, Protocol


class _LockingVoid(Protocol):
    def lock(
        self,
        text: str,
        domain: str = "general",
        protect: bool = True,
        shell: int | None = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
    ) -> str: ...


_SENTENCE_TARGET_MAX = 400
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_long_text(text: str, limit: int) -> List[str]:
    words = text.split()
    if not words:
        return []
    chunks: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
            continue
        chunks.append(current)
        current = word
    chunks.append(current)
    return chunks


def _sentence_chunks(text: str) -> List[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if len(sentences) <= 1:
        return _split_long_text(text.strip(), _SENTENCE_TARGET_MAX) or [text.strip()]
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        units = (
            _split_long_text(sentence, _SENTENCE_TARGET_MAX)
            if len(sentence) > _SENTENCE_TARGET_MAX
            else [sentence]
        )
        for unit in units:
            if not current:
                current = unit
                continue
            candidate = f"{current} {unit}"
            if len(candidate) <= _SENTENCE_TARGET_MAX:
                current = candidate
                continue
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)
    return chunks


def auto_segment(text: str, domain: str = "DOC", min_len: int = 50) -> List[str]:
    text = text.replace("\r\n", "\n").strip()
    parts = re.split(
        r"\n(?=#{1,4}\s|\d+\.\s+[A-Z]|[A-Z][A-Za-z0-9 \-/]{2,50}:\s|[A-Z][A-Z0-9 \-]{3,}:\s|Error\s+Code)",
        text,
    )
    if len(parts) < 3:
        parts = re.split(r"\n\s*\n+", text)
    normalized_parts = [part.strip() for part in parts if part.strip()]
    needs_refinement = len(normalized_parts) < 3
    if needs_refinement or any(len(part) > _SENTENCE_TARGET_MAX for part in normalized_parts):
        refined_parts: List[str] = []
        for part in normalized_parts:
            if len(part) > _SENTENCE_TARGET_MAX or needs_refinement:
                refined_parts.extend(_sentence_chunks(part))
            else:
                refined_parts.append(part)
        parts = refined_parts
    residuals: List[str] = []
    seen = set()
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was", "will", "can", "how", "what",
        "when", "must", "should", "unit", "models", "some", "every", "change", "inspect", "test",
        "use", "always", "verify", "a", "an", "is", "of", "to", "in", "on", "by", "i", "my", "me",
    }
    for i, part in enumerate(parts):
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
        key = body[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        residuals.append(f"{domain}::{tag}::{body}")
    return residuals


def inject_document(
    void: _LockingVoid,
    full_text: str,
    domain: str = "DOC",
    title: str = "SOURCE",
    protect: bool = True,
) -> Dict[str, int]:
    full_text = full_text.strip()
    if len(full_text) < 20:
        return {"segments": 0, "locked": 0}
    full_tag = title.upper().replace(" ", "_")[:20]
    full_residual = f"{domain}::{full_tag}_FULL::{full_text}"
    full_lock = void.lock(
        full_residual,
        domain=domain.lower(),
        protect=protect,
        imprint_layer="medium",
        coherence=0.90,
        shell=0,
    )
    segments = auto_segment(full_text, domain=domain)
    locked = 1 if full_lock == "locked" else 0
    for seg in segments:
        if void.lock(
            seg,
            domain=domain.lower(),
            protect=protect,
            imprint_layer="deep",
            coherence=0.97,
            shell=2,
        ) == "locked":
            locked += 1
    return {"segments": len(segments) + 1, "locked": locked}
