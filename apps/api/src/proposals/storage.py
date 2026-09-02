from __future__ import annotations

from pathlib import Path
from uuid import UUID


class ProposalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, tenant_id: UUID, data_hash: str, content: bytes) -> str:
        key = f"proposals/{tenant_id}/{data_hash}.pdf"
        destination = (self.root / "proposals" / str(tenant_id) / f"{data_hash}.pdf").resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return key
