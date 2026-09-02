from __future__ import annotations

from dataclasses import fields

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import MediaAsset
from .pipeline import MediaAssetRecord, ProcessingState


_RECORD_FIELDS = {
    field.name
    for field in fields(MediaAssetRecord)
    if field.name not in {"id", "created_at", "updated_at"}
}


def _to_record(row: MediaAsset) -> MediaAssetRecord:
    return MediaAssetRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        message_id=row.message_id,
        idempotency_key=row.idempotency_key,
        kind=row.kind,
        processing_state=ProcessingState(row.processing_state),
        declared_mime_type=row.declared_mime_type,
        detected_mime_type=row.detected_mime_type,
        size_bytes=row.size_bytes,
        duration_ms=row.duration_ms,
        sha256=row.sha256,
        storage_key=row.storage_key,
        original_storage_key=row.original_storage_key,
        provider_storage_key=row.provider_storage_key,
        provider_mime_type=row.provider_mime_type,
        transcript=row.transcript,
        failure_code=row.failure_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyMediaRepository:
    """Atomic tenant-scoped claim backed by the unique idempotency constraint."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim(self, record: MediaAssetRecord) -> tuple[MediaAssetRecord, bool]:
        values = {
            name: getattr(record, name)
            for name in _RECORD_FIELDS
            if name != "processing_state"
        }
        values["processing_state"] = record.processing_state.value
        statement = (
            insert(MediaAsset)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
            .returning(MediaAsset.id)
        )
        inserted_id = (await self.session.execute(statement)).scalar_one_or_none()
        await self.session.commit()
        if inserted_id is not None:
            return record, True
        existing = await self.session.scalar(
            select(MediaAsset).where(
                MediaAsset.tenant_id == record.tenant_id,
                MediaAsset.idempotency_key == record.idempotency_key,
            )
        )
        if existing is None:
            raise RuntimeError("claim de mídia não retornou registro")
        return _to_record(existing), False

    async def update(self, record: MediaAssetRecord) -> MediaAssetRecord:
        row = await self.session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == record.id,
                MediaAsset.tenant_id == record.tenant_id,
            )
        )
        if row is None:
            raise LookupError("MEDIA_NOT_FOUND")
        for name in _RECORD_FIELDS:
            value = getattr(record, name)
            setattr(row, name, value.value if name == "processing_state" else value)
        row.updated_at = record.updated_at
        await self.session.commit()
        return _to_record(row)
