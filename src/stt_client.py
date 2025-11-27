"""Client for speech-to-text transcription using local Whisper models."""

from __future__ import annotations

import asyncio
import importlib
from functools import partial
from pathlib import Path
from typing import Any, Optional

from .stt_settings import STT_SETTINGS

_model: Optional[Any] = None


def _load_model() -> Any:
    global _model
    if _model is None:
        try:
            fw_module = importlib.import_module("faster_whisper")
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Пакет 'faster-whisper' не установлен. Установите его: pip install faster-whisper"
            ) from exc
        WhisperModel = getattr(fw_module, "WhisperModel")
        _model = WhisperModel(
            STT_SETTINGS.model_size,
            device=STT_SETTINGS.device,
            compute_type=STT_SETTINGS.compute_type,
        )
    return _model


def _sync_transcribe(path: Path) -> str:
    model = _load_model()
    segments, _ = model.transcribe(
        str(path),
        language=STT_SETTINGS.language or None,
        beam_size=STT_SETTINGS.beam_size,
        vad_filter=STT_SETTINGS.vad_filter,
        temperature=STT_SETTINGS.temperature,
    )
    pieces = [seg.text.strip() for seg in segments if seg.text]
    return " ".join(pieces).strip()


async def transcribe_file(path: str | Path) -> str:
    """Transcribe an audio file asynchronously using faster-whisper."""
    audio_path = Path(path)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_transcribe, audio_path))


