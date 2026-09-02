"""Secure media ingestion and processing adapters."""

from .pipeline import (
    AudioTranscriptionUnavailable,
    InMemoryMediaRepository,
    MediaPipeline,
    MediaPolicy,
    MediaProcessingError,
    MediaUpload,
    ProcessingState,
    provider_media_reference,
    transcript_as_untrusted_context,
)
from .persistence import SqlAlchemyMediaRepository
from .storage import LocalMediaStorage, StoragePathError
from .transcription import FakeTranscriber, FasterWhisperTranscriber

__all__ = [
    "AudioTranscriptionUnavailable", "FakeTranscriber", "FasterWhisperTranscriber",
    "InMemoryMediaRepository", "LocalMediaStorage", "MediaPipeline", "MediaPolicy",
    "MediaProcessingError", "MediaUpload", "ProcessingState", "StoragePathError",
    "SqlAlchemyMediaRepository",
    "provider_media_reference", "transcript_as_untrusted_context",
]
