from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .merged import ResidualVoid


class PersistentVoid(ResidualVoid):
    def __init__(
        self,
        secret: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str] = None,
        name: str = "void",
        storage_path: str = "residual_void_chain.jsonl",
    ) -> None:
        self.storage_path = Path(storage_path)
        super().__init__(secret=secret, config=config, config_path=config_path, name=name)
        self._load_chain()

    def _append_record(self, record: Dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _load_chain(self) -> None:
        if not self.storage_path.exists():
            return
        lines = self.storage_path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception as exc:
                raise ValueError(f"broken_chain_jsonl_line_{index}") from exc
            text = rec.get("text")
            domain = rec.get("domain", "general")
            protect = bool(rec.get("protect", True))
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"broken_chain_record_line_{index}")
            result = super().lock(
                text,
                domain=domain,
                protect=protect,
                shell=rec.get("shell"),
                imprint_layer=str(rec.get("imprint_layer", "medium")),
                coherence=float(rec.get("coherence", 0.85)),
                identity=rec.get("identity"),
                scale=float(rec.get("scale", 1.0)),
                density=float(rec.get("density", 1.0)),
                mass=float(rec["mass"]) if rec.get("mass") is not None else None,
                intent=str(rec.get("intent", "")),
                shadow_texts=rec.get("shadow_texts")
                if isinstance(rec.get("shadow_texts"), list)
                else None,
            )
            if result not in {"locked", "duplicate"}:
                raise ValueError(f"broken_chain_lock_line_{index}:{result}")
        # Backfill governance for residuals that pre-date the governance layer.
        # Re-derives family="" entries and enforces FIFO active-engram ordering
        # so freshly locked residuals can correctly demote old ungoverned cousins.
        self._void.field.backfill_governance()

    def lock(
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
        result = super().lock(
            text,
            domain=domain,
            protect=protect,
            shell=shell,
            imprint_layer=imprint_layer,
            coherence=coherence,
            identity=identity,
            scale=scale,
            density=density,
            mass=mass,
            intent=intent,
            shadow_texts=shadow_texts,
        )
        if result == "locked":
            self._append_record({
                "text": text,
                "domain": domain,
                "protect": protect,
                "shell": shell,
                "imprint_layer": imprint_layer,
                "coherence": coherence,
                "identity": identity,
                "scale": scale,
                "density": density,
                "mass": mass,
                "intent": intent,
                "shadow_texts": shadow_texts,
            })
        return result

    def confirm(self, lock_id: str):
        residual = super().confirm(lock_id)
        if residual is not None:
            self._append_record(
                {
                    "text": residual.fragment,
                    "domain": residual.domain,
                    "protect": residual.protect,
                    "identity": residual.seed_identity,
                    "scale": residual.seed_scale,
                    "density": residual.seed_density,
                    "mass": residual.seed_mass,
                    "intent": residual.seed_intent,
                }
            )
        return residual

    def clear(self) -> dict:
        """Wipe in-memory residuals AND truncate the JSONL chain file.

        Without this override, clear() removes residuals from the running
        field but leaves the JSONL intact.  On the next restart _load_chain()
        would replay the file and resurrect every cleared residual, making
        /clear a no-op across restarts.
        """
        result = super().clear()
        # Truncate (don't delete) so the path stays predictable and any
        # file-watching infrastructure doesn't need to recreate it.
        if self.storage_path.exists():
            self.storage_path.write_text("", encoding="utf-8")
        return result
