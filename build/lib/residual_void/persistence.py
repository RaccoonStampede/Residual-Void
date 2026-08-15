from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

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
            result = super().lock(text, domain=domain, protect=protect)
            if result not in {"locked", "duplicate"}:
                raise ValueError(f"broken_chain_lock_line_{index}:{result}")

    def lock(
        self,
        text: str,
        domain: str = "general",
        protect: bool = True,
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
    ) -> str:
        result = super().lock(
            text,
            domain=domain,
            protect=protect,
            shell=shell,
            imprint_layer=imprint_layer,
            coherence=coherence,
        )
        if result == "locked":
            self._append_record({"text": text, "domain": domain, "protect": protect})
        return result

    def confirm(self, lock_id: str):
        residual = super().confirm(lock_id)
        if residual is not None:
            self._append_record(
                {"text": residual.fragment, "domain": residual.domain, "protect": residual.protect}
            )
        return residual
