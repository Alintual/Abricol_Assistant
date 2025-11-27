"""Настройки для локальной транскрибации.

Параметры берутся из файла ``config/stt_config.json``. Если файл отсутствует
или содержит неполные данные, используются значения по умолчанию.
"""

from __future__ import annotations

import json
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
    if not path.exists():
        return STTSettings()

    try:
        with path.open("r", encoding="utf-8") as fh:
            data: Dict[str, Any] = json.load(fh)
    except Exception as exc:  # pragma: no cover - конфиг читается редко
        raise RuntimeError(f"Не удалось прочитать файл настроек STT: {path}") from exc

    def _get(name: str, default: Any) -> Any:
        return data.get(name, default)

    return STTSettings(
        model_size=str(_get("model_size", STTSettings.model_size)),
        device=str(_get("device", STTSettings.device)),
        compute_type=str(_get("compute_type", STTSettings.compute_type)),
        language=str(_get("language", STTSettings.language)),
        beam_size=int(_get("beam_size", STTSettings.beam_size)),
        vad_filter=bool(_get("vad_filter", STTSettings.vad_filter)),
        temperature=float(_get("temperature", STTSettings.temperature)),
    )


STT_SETTINGS = _load_settings(CONFIG_PATH)
