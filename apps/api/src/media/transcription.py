from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Protocol


class Transcriber(Protocol):
    async def transcribe(self, payload: bytes, mime_type: str) -> str: ...


class AudioTranscriptionUnavailable(RuntimeError):
    pass


class FasterWhisperTranscriber:
    """Lazy local adapter; importing the model is never required at API startup."""

    def __init__(self, model_size: str = "small", device: str = "cpu", compute_type: str = "int8", model: object | None = None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = model

    def _get_model(self) -> object:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel  # type: ignore[import-not-found]
            except ImportError as exc:
                raise AudioTranscriptionUnavailable("Faster-Whisper não instalado/configurado no worker") from exc
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def _transcribe_sync(self, payload: bytes, mime_type: str) -> str:
        suffix = {"audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/ogg": ".ogg"}[mime_type]
        with tempfile.NamedTemporaryFile(prefix="ks-media-", suffix=suffix, delete=True) as handle:
            handle.write(payload)
            handle.flush()
            segments, _info = self._get_model().transcribe(str(Path(handle.name)), vad_filter=True)  # type: ignore[attr-defined]
            return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    async def transcribe(self, payload: bytes, mime_type: str) -> str:
        return await asyncio.to_thread(self._transcribe_sync, payload, mime_type)


class FakeTranscriber:
    def __init__(self, transcript: str = "transcrição de teste"):
        self.transcript = transcript
        self.calls = 0

    async def transcribe(self, payload: bytes, mime_type: str) -> str:
        self.calls += 1
        return self.transcript
