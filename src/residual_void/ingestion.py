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


def auto_segment(text: str, domain: str = "DOC", min_len: int = 50) -> List[str]:
    text = text.replace("\r\n", "\n").strip()
    parts = re.split(
        r"\n(?=#{1,4}\s|\d+\.\s+[A-Z]|[A-Z][A-Za-z0-9 \-/]{2,50}:\s|[A-Z][A-Z0-9 \-]{3,}:\s|Error\s+Code)",
        text,
    )
    if len(parts) < 3:
        parts = re.split(r"\n\s*\n+", text)
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
