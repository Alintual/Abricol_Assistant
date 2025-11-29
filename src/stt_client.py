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
    """Загружает модель faster-whisper для транскрибации."""
    import logging
    logger = logging.getLogger(__name__)
    
    global _model
    if _model is None:
        logger.info(f"Загрузка модели STT: размер={STT_SETTINGS.model_size}, device={STT_SETTINGS.device}, compute_type={STT_SETTINGS.compute_type}")
        try:
            fw_module = importlib.import_module("faster_whisper")
            logger.info("Модуль faster_whisper импортирован успешно")
        except ImportError as exc:  # pragma: no cover
            logger.error(f"Не удалось импортировать faster_whisper: {exc}")
            raise ImportError(
                "Пакет 'faster-whisper' не установлен. Установите его: pip install faster-whisper"
            ) from exc
        
        WhisperModel = getattr(fw_module, "WhisperModel")
        logger.info(f"Создание экземпляра WhisperModel с параметрами: model_size={STT_SETTINGS.model_size}")
        
        try:
            _model = WhisperModel(
                STT_SETTINGS.model_size,
                device=STT_SETTINGS.device,
                compute_type=STT_SETTINGS.compute_type,
            )
            logger.info("Модель WhisperModel создана успешно")
        except Exception as e:
            logger.error(f"Ошибка при создании модели: {e}", exc_info=True)
            raise
    else:
        logger.debug("Модель уже загружена, используем существующий экземпляр")
    
    return _model


def _sync_transcribe(path: Path) -> str:
    """Транскрибирует аудио файл."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"Загрузка модели STT (размер: {STT_SETTINGS.model_size})...")
    model = _load_model()
    logger.info(f"Модель загружена успешно")
    
    audio_path = str(path)
    logger.info(f"Начало транскрибации файла: {audio_path}")
    
    try:
        segments, info = model.transcribe(
            audio_path,
            language=STT_SETTINGS.language or None,
            beam_size=STT_SETTINGS.beam_size,
            vad_filter=STT_SETTINGS.vad_filter,
            temperature=STT_SETTINGS.temperature,
        )
        
        logger.info(f"Язык транскрибации: {info.language}, вероятность: {info.language_probability:.2f}")
        
        pieces = []
        for seg in segments:
            if seg.text and seg.text.strip():
                pieces.append(seg.text.strip())
                logger.debug(f"Сегмент: {seg.text.strip()}")
        
        result = " ".join(pieces).strip()
        logger.info(f"Транскрибация завершена, получено символов: {len(result)}")
        
        if not result:
            logger.warning("Транскрибация вернула пустой результат!")
        
        return result
    except Exception as e:
        logger.error(f"Ошибка при транскрибации: {e}", exc_info=True)
        raise


async def transcribe_file(path: str | Path) -> str:
    """Transcribe an audio file asynchronously using faster-whisper."""
    audio_path = Path(path)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_transcribe, audio_path))


