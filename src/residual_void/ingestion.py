from __future__ import annotations

import re
from typing import Dict, List, Protocol


class _LockingVoid(Protocol):
    def lock(self, text: str, domain: str = "general", protect: bool = True) -> str: ...


def auto_segment(text: str, domain: str = "DOC", min_len: int = 50) -> List[str]:
    chunks = []
    if not text:
        return chunks
    parts = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?])\s+", text) if p.strip()]
    bucket = ""
    for part in parts:
        candidate = (bucket + " " + part).strip() if bucket else part
        if len(candidate) < min_len:
            bucket = candidate
            continue
        chunks.append(candidate)
        bucket = ""
    if bucket:
        chunks.append(bucket)
    return chunks


def inject_document(
    void: _LockingVoid,
    full_text: str,
    domain: str = "DOC",
    title: str = "SOURCE",
    protect: bool = True,
) -> Dict[str, int]:
    segments = auto_segment(full_text, domain=domain)
    locked = 0
    for idx, seg in enumerate(segments, start=1):
        payload = f"{title}::{idx:03d}::{seg}"
        if void.lock(payload, domain=domain, protect=protect) == "locked":
            locked += 1
    return {"segments": len(segments), "locked": locked}
