"""Настройки для локальной транскрибации.

Параметры берутся из переменных окружения (.env) или из файла ``config/stt_config.json``.
Если оба отсутствуют, используются значения по умолчанию.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "stt_config.json"


@dataclass(frozen=True)
class STTSettings:
    model_size: str = "medium"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "ru"
    beam_size: int = 5
    vad_filter: bool = False
    temperature: float = 0.0


def _load_settings(path: Path) -> STTSettings:
    # Загружаем из JSON файла, если он существует
    json_data: Dict[str, Any] = {}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                json_data = json.load(fh)
        except Exception:  # pragma: no cover - конфиг читается редко
            # Игнорируем ошибку чтения JSON, используем значения по умолчанию
            pass

    def _get(name: str, default: Any) -> Any:
        # Приоритет: переменные окружения > JSON > значения по умолчанию
        
        # Проверяем переменные окружения
        env_map = {
            "model_size": os.getenv("STT_MODEL_SIZE"),
            "device": os.getenv("STT_DEVICE"),
            "compute_type": os.getenv("STT_COMPUTE_TYPE"),
            "language": os.getenv("STT_LANGUAGE"),
            "beam_size": os.getenv("STT_BEAM_SIZE"),
            "vad_filter": os.getenv("STT_VAD_FILTER"),
            "temperature": os.getenv("STT_TEMPERATURE"),
        }
        
        env_value = env_map.get(name)
        if env_value is not None:
            return env_value
        
        # Затем JSON
        if name in json_data:
            return json_data[name]
        
        # Иначе значение по умолчанию
        return default

    # Преобразуем значения с правильными типами
    model_size = str(_get("model_size", STTSettings.model_size))
    device = str(_get("device", STTSettings.device))
    compute_type = str(_get("compute_type", STTSettings.compute_type))
    language = str(_get("language", STTSettings.language))
    
    beam_size_val = _get("beam_size", STTSettings.beam_size)
    beam_size = int(beam_size_val) if beam_size_val is not None else STTSettings.beam_size
    
    vad_filter_val = _get("vad_filter", STTSettings.vad_filter)
    if isinstance(vad_filter_val, bool):
        vad_filter = vad_filter_val
    else:
        vad_filter = str(vad_filter_val).lower() in ("true", "1", "yes") if vad_filter_val is not None else STTSettings.vad_filter
    
    temperature_val = _get("temperature", STTSettings.temperature)
    temperature = float(temperature_val) if temperature_val is not None else STTSettings.temperature

    return STTSettings(
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        temperature=temperature,
    )


STT_SETTINGS = _load_settings(CONFIG_PATH)
