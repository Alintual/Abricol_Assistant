"""
Модуль для работы с маппингом рисунков и изображений из PDF.
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional, Iterable, List, Tuple

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "data", "images")
MAPPING_FILE = os.path.join(IMAGES_DIR, "figure_mapping.json")


def load_figure_mapping() -> Dict[str, dict]:
    """Загружает маппинг рисунков на изображения."""
    if not os.path.exists(MAPPING_FILE):
        return {}
    
    try:
        with open(MAPPING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def find_figures_in_text(text: str) -> list:
    """Находит все упоминания рисунков в тексте (Рис.X.X.X)."""
    import re
    pattern = re.compile(r'рис\.?\s*(\d+(?:\.\d+)+)', re.IGNORECASE)
    matches = pattern.findall(text or "")
    return [f"Рис.{fig}" for fig in matches]


def get_image_path_for_figure(figure_key: str) -> Optional[str]:
    """Возвращает путь к изображению для указанного рисунка."""
    mapping = load_figure_mapping()
    if figure_key in mapping and "path" in mapping[figure_key]:
        path = mapping[figure_key]["path"]
        
        # Нормализуем путь (заменяем Windows-разделители на Unix)
        path = path.replace("\\", "/")
        
        # Если путь абсолютный, проверяем его существование
        if os.path.isabs(path):
            if os.path.exists(path):
                return path
            # Если абсолютный путь не существует (например, Windows путь в Linux контейнере),
            # пытаемся извлечь имя файла и найти его в IMAGES_DIR
            filename = os.path.basename(path)
            if filename:
                alt_path = os.path.join(IMAGES_DIR, filename)
                if os.path.exists(alt_path):
                    return alt_path
        
        # Если путь относительный, строим его относительно IMAGES_DIR
        if not os.path.isabs(path):
            # Убираем возможные префиксы пути, оставляя только имя файла
            filename = os.path.basename(path)
            full_path = os.path.join(IMAGES_DIR, filename)
            if os.path.exists(full_path):
                return full_path
            
            # Пробуем исходный относительный путь относительно IMAGES_DIR
            full_path = os.path.join(IMAGES_DIR, path)
            if os.path.exists(full_path):
                return full_path
        
        # Также проверяем поле "image", если оно есть
        if "image" in mapping[figure_key]:
            image_filename = mapping[figure_key]["image"]
            alt_path = os.path.join(IMAGES_DIR, image_filename)
            if os.path.exists(alt_path):
                return alt_path
    
    return None


def get_figure_title(figure_key: str) -> str:
    """Возвращает заголовок рисунка или пустую строку."""
    mapping = load_figure_mapping()
    if figure_key in mapping:
        fig_info = mapping[figure_key]
        if isinstance(fig_info, dict) and "title" in fig_info:
            return fig_info["title"]
    return ""


def find_figures_by_keywords(keywords: Iterable[str]) -> List[str]:
    """Возвращает список ключей рисунков, у которых заголовок содержит любые из ключевых слов.

    Результат отсортирован по количеству совпавших ключевых слов (по убыванию), затем по ключу.
    """
    kw = {k.lower() for k in keywords if k}
    if not kw:
        return []
    mapping = load_figure_mapping()
    scored: List[Tuple[str, int]] = []
    for fig_key, info in mapping.items():
        if not isinstance(info, dict):
            continue
        title = str(info.get("title", "")).lower()
        if not title:
            continue
        score = sum(1 for k in kw if k and k in title)
        if score > 0:
            scored.append((fig_key, score))
    # Сортируем по score (desc), затем по fig_key для стабильности
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [fig for fig, _ in scored]

