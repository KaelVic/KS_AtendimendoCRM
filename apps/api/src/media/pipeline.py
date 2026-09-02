from __future__ import annotations

import hashlib
import io
import struct
import warnings
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import PurePath
from typing import Protocol
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import LocalMediaStorage
from .transcription import AudioTranscriptionUnavailable, Transcriber


class MediaProcessingError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


class ProcessingState(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass(frozen=True)
class MediaPolicy:
    max_bytes: int = 25 * 1024 * 1024
    max_audio_duration_seconds: float = 15 * 60
    max_image_pixels: int = 25_000_000
    max_image_dimension: int = 2_048
    retain_originals: bool = True

    @classmethod
    def from_settings(cls, settings: object) -> "MediaPolicy":
        return cls(
            max_bytes=int(getattr(settings, "MEDIA_MAX_BYTES")),
            max_audio_duration_seconds=float(getattr(settings, "MEDIA_MAX_AUDIO_DURATION_SECONDS")),
            max_image_pixels=int(getattr(settings, "MEDIA_MAX_IMAGE_PIXELS")),
            max_image_dimension=int(getattr(settings, "MEDIA_MAX_IMAGE_DIMENSION")),
            retain_originals=bool(getattr(settings, "MEDIA_RETAIN_ORIGINALS")),
        )


@dataclass(frozen=True)
class MediaUpload:
    tenant_id: UUID
    message_id: UUID
    idempotency_key: str
    declared_mime_type: str
    payload: bytes
    filename: str | None = None


@dataclass
class MediaAssetRecord:
    id: UUID
    tenant_id: UUID
    message_id: UUID
    idempotency_key: str
    kind: str
    processing_state: ProcessingState
    declared_mime_type: str
    detected_mime_type: str
    size_bytes: int
    duration_ms: int | None
    sha256: str
    storage_key: str | None
    original_storage_key: str | None
    provider_storage_key: str | None
    provider_mime_type: str | None
    transcript: str | None
    failure_code: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MediaRepository(Protocol):
    async def claim(self, record: MediaAssetRecord) -> tuple[MediaAssetRecord, bool]: ...
    async def update(self, record: MediaAssetRecord) -> MediaAssetRecord: ...


class InMemoryMediaRepository:
    def __init__(self):
        self.records: dict[tuple[UUID, str], MediaAssetRecord] = {}

    async def claim(self, record: MediaAssetRecord) -> tuple[MediaAssetRecord, bool]:
        key = (record.tenant_id, record.idempotency_key)
        existing = self.records.get(key)
        if existing is not None:
            return existing, False
        self.records[key] = record
        return record, True

    async def update(self, record: MediaAssetRecord) -> MediaAssetRecord:
        self.records[(record.tenant_id, record.idempotency_key)] = record
        return record


def _canonical_declared_mime(value: str) -> str:
    aliases = {"audio/x-wav": "audio/wav", "audio/wave": "audio/wav", "image/jpg": "image/jpeg"}
    return aliases.get(value.strip().lower(), value.strip().lower())


def _validate_filename(filename: str | None) -> None:
    if filename is None:
        return
    if not filename or "\x00" in filename or "/" in filename or "\\" in filename:
        raise MediaProcessingError("PATH_TRAVERSAL_BLOCKED")
    if PurePath(filename).name != filename:
        raise MediaProcessingError("PATH_TRAVERSAL_BLOCKED")


def _audio_mime(payload: bytes) -> str | None:
    if payload[:4] == b"RIFF" and payload[8:12] == b"WAVE":
        return "audio/wav"
    if payload[:4] == b"OggS":
        return "audio/ogg"
    offset = 0
    if payload[:3] == b"ID3" and len(payload) >= 10:
        offset = 10 + sum((payload[6 + i] & 0x7F) << (7 * (3 - i)) for i in range(4))
    if len(payload) >= offset + 2 and payload[offset] == 0xFF and payload[offset + 1] & 0xE0 == 0xE0:
        return "audio/mpeg"
    return None


def _wav_duration(payload: bytes) -> float:
    try:
        with wave.open(io.BytesIO(payload)) as source:
            rate = source.getframerate()
            frames = source.getnframes()
            channels = source.getnchannels()
            if rate <= 0 or frames < 0 or channels <= 0:
                raise MediaProcessingError("AUDIO_DURATION_INVALID")
            return frames / rate
    except (wave.Error, EOFError) as exc:
        raise MediaProcessingError("MEDIA_CORRUPTED") from exc


def _ogg_duration(payload: bytes) -> float:
    position = 0
    max_granule = -1
    sample_rate: int | None = None
    while position < len(payload):
        if len(payload) - position < 27 or payload[position : position + 4] != b"OggS":
            raise MediaProcessingError("MEDIA_CORRUPTED")
        header = payload[position : position + 27]
        segment_count = header[26]
        table_end = position + 27 + segment_count
        if table_end > len(payload):
            raise MediaProcessingError("MEDIA_CORRUPTED")
        body_size = sum(payload[position + 27 : table_end])
        body_end = table_end + body_size
        if body_end > len(payload):
            raise MediaProcessingError("MEDIA_CORRUPTED")
        body = payload[table_end:body_end]
        if body.startswith(b"OpusHead"):
            sample_rate = 48_000
        elif body.startswith(b"\x01vorbis") and len(body) >= 16:
            sample_rate = struct.unpack_from("<I", body, 12)[0]
        max_granule = max(max_granule, int.from_bytes(header[6:14], "little", signed=False))
        position = body_end
    if position != len(payload) or max_granule < 0 or not sample_rate:
        raise MediaProcessingError("AUDIO_DURATION_INVALID")
    return max_granule / sample_rate


def _mp3_duration(payload: bytes) -> float:
    offset = 0
    if payload[:3] == b"ID3":
        if len(payload) < 10:
            raise MediaProcessingError("MEDIA_CORRUPTED")
        offset = 10 + sum((payload[6 + i] & 0x7F) << (7 * (3 - i)) for i in range(4))
    if len(payload) < offset + 4:
        raise MediaProcessingError("MEDIA_CORRUPTED")
    header = int.from_bytes(payload[offset : offset + 4], "big")
    if (header >> 21) & 0x7FF != 0x7FF:
        raise MediaProcessingError("MEDIA_CORRUPTED")
    version = (header >> 19) & 0x3
    layer = (header >> 17) & 0x3
    bitrate_index = (header >> 12) & 0xF
    sample_index = (header >> 10) & 0x3
    if version not in (2, 3) or layer != 1 or bitrate_index in (0, 15) or sample_index == 3:
        raise MediaProcessingError("AUDIO_DURATION_INVALID")
    bitrates = {3: [32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320], 2: [8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}[version]
    sample_rates = {3: [44_100, 48_000, 32_000], 2: [22_050, 24_000, 16_000]}[version]
    bitrate = bitrates[bitrate_index - 1] * 1000
    frame_length = (144 if version == 3 else 72) * bitrate // sample_rates[sample_index]
    frame_length += (header >> 9) & 1
    if len(payload) - offset < frame_length:
        raise MediaProcessingError("MEDIA_CORRUPTED")
    # For VBR streams, use the lowest legal bitrate as an upper-bound duration;
    # accepting an optimistic first-frame estimate could bypass the duration cap.
    minimum_bitrate = min(bitrates) * 1000
    return max(0.0, (len(payload) - offset) * 8 / minimum_bitrate)


def _duration_seconds(payload: bytes, mime_type: str) -> float:
    if mime_type == "audio/wav":
        return _wav_duration(payload)
    if mime_type == "audio/ogg":
        return _ogg_duration(payload)
    if mime_type == "audio/mpeg":
        return _mp3_duration(payload)
    raise MediaProcessingError("AUDIO_FORMAT_NOT_SUPPORTED")


def _image_derivative(payload: bytes, policy: MediaPolicy) -> tuple[str, bytes]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as probe:
                width, height = probe.size
                if width * height > policy.max_image_pixels:
                    raise MediaProcessingError("DECOMPRESSION_BOMB_BLOCKED")
                probe.verify()
            with Image.open(io.BytesIO(payload)) as source:
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((policy.max_image_dimension, policy.max_image_dimension), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=85, optimize=True, exif=b"")
                return "image/jpeg", output.getvalue()
    except MediaProcessingError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaProcessingError("MEDIA_CORRUPTED") from exc


class MediaPipeline:
    def __init__(self, repository: MediaRepository, storage: LocalMediaStorage, transcriber: Transcriber, policy: MediaPolicy | None = None):
        self.repository = repository
        self.storage = storage
        self.transcriber = transcriber
        self.policy = policy or MediaPolicy()

    def _validate(self, upload: MediaUpload) -> tuple[str, str, int | None, bytes | None]:
        _validate_filename(upload.filename)
        if not upload.idempotency_key.strip() or len(upload.idempotency_key) > 255:
            raise MediaProcessingError("IDEMPOTENCY_KEY_INVALID")
        if not upload.payload or len(upload.payload) > self.policy.max_bytes:
            raise MediaProcessingError("MEDIA_SIZE_INVALID")
        declared = _canonical_declared_mime(upload.declared_mime_type)
        actual_audio = _audio_mime(upload.payload)
        if declared.startswith("audio/"):
            if actual_audio != declared:
                raise MediaProcessingError("MEDIA_TYPE_MISMATCH")
            duration = _duration_seconds(upload.payload, actual_audio)
            if duration > self.policy.max_audio_duration_seconds:
                raise MediaProcessingError("AUDIO_DURATION_EXCEEDED")
            return "AUDIO", actual_audio, round(duration * 1000), None
        if declared.startswith("image/"):
            try:
                with Image.open(io.BytesIO(upload.payload)) as probe:
                    actual_format = probe.format
            except (UnidentifiedImageError, OSError) as exc:
                raise MediaProcessingError("MEDIA_CORRUPTED") from exc
            actual_image = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(actual_format or "")
            if actual_image != declared:
                raise MediaProcessingError("MEDIA_TYPE_MISMATCH")
            provider_mime, derivative = _image_derivative(upload.payload, self.policy)
            return "IMAGE", actual_image, None, derivative
        raise MediaProcessingError("MEDIA_TYPE_NOT_ALLOWED")

    async def process(self, upload: MediaUpload) -> MediaAssetRecord:
        kind, detected, duration_ms, derivative = self._validate(upload)
        source_key: str | None = None
        original_key: str | None = None
        provider_key: str | None = None
        persisted = False
        try:
            if kind == "AUDIO":
                suffix = {"audio/wav": ".wav", "audio/ogg": ".ogg", "audio/mpeg": ".mp3"}[detected]
                source_key = self.storage.put(upload.tenant_id, upload.payload, suffix)
                if self.policy.retain_originals:
                    original_key = source_key
            else:
                provider_key = self.storage.put(upload.tenant_id, derivative or b"", ".jpg")
                if self.policy.retain_originals:
                    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[detected]
                    original_key = self.storage.put(upload.tenant_id, upload.payload, suffix)
            record = MediaAssetRecord(
                id=uuid4(), tenant_id=upload.tenant_id, message_id=upload.message_id,
                idempotency_key=upload.idempotency_key, kind=kind, processing_state=ProcessingState.RECEIVED,
                declared_mime_type=_canonical_declared_mime(upload.declared_mime_type), detected_mime_type=detected,
                size_bytes=len(upload.payload), duration_ms=duration_ms, sha256=hashlib.sha256(upload.payload).hexdigest(),
                storage_key=source_key if kind == "AUDIO" and self.policy.retain_originals else provider_key,
                original_storage_key=original_key, provider_storage_key=provider_key,
                provider_mime_type="image/jpeg" if kind == "IMAGE" else None, transcript=None, failure_code=None,
            )
            claimed, created = await self.repository.claim(record)
            if not created:
                self._cleanup(upload.tenant_id, source_key, original_key, provider_key)
                if claimed.sha256 != record.sha256:
                    raise MediaProcessingError("IDEMPOTENCY_CONFLICT")
                return claimed
            persisted = True
            record.processing_state = ProcessingState.PROCESSING
            record.updated_at = datetime.now(timezone.utc)
            await self.repository.update(record)
            if kind == "AUDIO":
                record.transcript = (await self.transcriber.transcribe(upload.payload, detected)).strip()
            record.processing_state = ProcessingState.READY
            record.updated_at = datetime.now(timezone.utc)
            await self.repository.update(record)
            if kind == "AUDIO" and not self.policy.retain_originals:
                self.storage.delete(upload.tenant_id, source_key)
            if kind == "IMAGE" and not self.policy.retain_originals:
                self.storage.delete(upload.tenant_id, original_key)
            return record
        except Exception as exc:
            if persisted:
                record.processing_state = ProcessingState.FAILED
                record.failure_code = getattr(exc, "code", "PROCESSING_FAILED")
                record.updated_at = datetime.now(timezone.utc)
                await self.repository.update(record)
            if not self.policy.retain_originals:
                self._cleanup(upload.tenant_id, source_key if kind == "AUDIO" else original_key)
            if isinstance(exc, MediaProcessingError):
                raise
            if isinstance(exc, AudioTranscriptionUnavailable):
                raise MediaProcessingError("TRANSCRIPTION_UNAVAILABLE") from exc
            raise MediaProcessingError("PROCESSING_FAILED") from exc

    def _cleanup(self, tenant_id: UUID, *keys: str | None) -> None:
        seen: set[str] = set()
        for key in keys:
            if key is not None and key not in seen:
                self.storage.delete(tenant_id, key)
                seen.add(key)


def provider_media_reference(record: MediaAssetRecord) -> dict[str, str | int]:
    if record.processing_state != ProcessingState.READY or record.kind != "IMAGE" or not record.provider_storage_key:
        raise MediaProcessingError("MEDIA_NOT_READY_FOR_PROVIDER")
    return {"kind": "IMAGE", "mime_type": record.provider_mime_type or "image/jpeg", "storage_key": record.provider_storage_key}


def transcript_as_untrusted_context(transcript: str) -> str:
    """Keep transcription as data; delimiters are context, never system instructions."""
    return "[DADO_NAO_CONFIAVEL: TRANSCRICAO]\n" + transcript[:12_000] + "\n[/DADO_NAO_CONFIAVEL]"
