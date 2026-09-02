from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4


class StoragePathError(ValueError):
    """A caller attempted to access a path outside the media namespace."""


class LocalMediaStorage:
    """Small local/S3-compatible seam with an intentionally opaque key API."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, tenant_id: UUID, key: str) -> Path:
        if not key or "\\" in key:
            raise StoragePathError("referência de storage inválida")
        relative = PurePosixPath(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise StoragePathError("referência de storage inválida")
        expected_prefix = PurePosixPath("media") / str(tenant_id)
        if relative.parts[:2] != expected_prefix.parts:
            raise StoragePathError("referência de storage fora do tenant")
        candidate = (self.root / Path(*relative.parts)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise StoragePathError("referência de storage fora da raiz") from exc
        return candidate

    def put(self, tenant_id: UUID, payload: bytes, suffix: str) -> str:
        if not suffix.startswith(".") or "/" in suffix or "\\" in suffix:
            raise StoragePathError("extensão inválida")
        key = f"media/{tenant_id}/{uuid4().hex}{suffix.lower()}"
        destination = self._resolve(tenant_id, key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return key

    def read(self, tenant_id: UUID, key: str) -> bytes:
        return self._resolve(tenant_id, key).read_bytes()

    def delete(self, tenant_id: UUID, key: str | None) -> None:
        if key is None:
            return
        path = self._resolve(tenant_id, key)
        if path.exists():
            path.unlink()
