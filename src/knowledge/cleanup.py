"""
Автоматическая очистка и нормализация сгенерированных артефактов БЗ.

Назначение:
- Нормализовать ссылки на рисунки: «Рис. 1.2. 3» → «Рис.1.2.3»
- Исправить типовые разрывы слов после OCR: «бан нер» → «баннер», «осв ещенность» → «освещенность», и т.п.
- Нормализовать заголовки в figure_mapping.json
"""

from __future__ import annotations

import os
import json
import re
from typing import Callable, List, Tuple


# Набор целевых замен для типовых разрывов внутри слов (безопасные точечные фиксы)
SAFE_WORD_FIXES: List[Tuple[re.Pattern, str]] = [
    # Общие OCR-ошибки с разрывами
    (re.compile(r"\bбан\s+нер\b", re.IGNORECASE), "баннер"),
    (re.compile(r"\bСертифика\s+т\b", re.IGNORECASE), "Сертификат"),
    (re.compile(r"\bборт\s+ов\b", re.IGNORECASE), "бортов"),
    (re.compile(r"\bосв\s+ещенн", re.IGNORECASE), "освещенн"),
    (re.compile(r"\bрасположе\s+ни", re.IGNORECASE), "расположени"),
    (re.compile(r"\bназываетс\s+я\b", re.IGNORECASE), "называется"),
    (re.compile(r"\bруководствоватьс\s+я\b", re.IGNORECASE), "руководствоваться"),
    (re.compile(r"\bсоударени\s+я\b", re.IGNORECASE), "соударения"),
    (re.compile(r"\bпадени\s+я\b", re.IGNORECASE), "падения"),
    (re.compile(r"\bнаход\s+ящ", re.IGNORECASE), "находящ"),
]


def normalize_figure_refs(text: str) -> str:
    """Нормализует формат ссылок на рисунки к «Рис.X.Y.Z» без лишних пробелов.

    Примеры:
    - «Рис. 1.2. 3» → «Рис.1.2.3»
    - «Рис. 2.2.1» → «Рис.2.2.1»
    """
    def _repl(m: re.Match) -> str:
        num = m.group(1)
        # Убираем пробелы вокруг точек и внутри компонентов
        num = re.sub(r"\s*\.\s*", ".", num.strip())
        return f"Рис.{num}"

    # Допускаем опциональную точку после «Рис», любые пробелы, и числа с точками и пробелами
    pattern = re.compile(r"Рис\.?\s*([0-9\s\.]{3,})")
    return pattern.sub(_repl, text)


def apply_safe_word_fixes(text: str) -> str:
    """Применяет безопасные точечные фиксы разрывов внутри слов.

    Используются только проверенные замены, не влияющие на разделение слов в нормальных случаях.
    """
    fixed = text
    for pattern, replacement in SAFE_WORD_FIXES:
        fixed = pattern.sub(replacement, fixed)
    return fixed


def normalize_whitespace_punctuation(text: str) -> str:
    """Базовая нормализация пробелов и пунктуации (щадящая)."""
    # 2+ пробелов → один
    text = re.sub(r"[ ]{2,}", " ", text)
    # Пробелы перед знаками препинания
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    # Нормализуем пробелы после знаков препинания (по крайней мере один)
    text = re.sub(r"([.,;:!?])\s+", r"\1 ", text)
    # Убираем пробелы вокруг дефисов внутри слов
    text = re.sub(r"\s+-\s+", "-", text)
    text = re.sub(r"\s+-\s*([А-Яа-яЁёA-Za-z])", r"-\1", text)
    return text.strip()


def clean_text_content(text: str) -> str:
    """Комплексная очистка контента: фигуры, пунктуация, безопасные фиксы слов."""
    text = normalize_figure_refs(text)
    text = normalize_whitespace_punctuation(text)
    text = apply_safe_word_fixes(text)
    return text


def clean_structured_texts(structured_dir: str) -> None:
    """Проходит по всем *_structured.txt и применяет очистку."""
    if not os.path.isdir(structured_dir):
        return
    for name in os.listdir(structured_dir):
        if not name.endswith("_structured.txt"):
            continue
        path = os.path.join(structured_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                original = f.read()
            cleaned = clean_text_content(original)
            if cleaned != original:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(cleaned)
        except Exception:
            # Щадяще: не прерываем конвейер при единичной ошибке
            continue


def clean_figure_mapping_titles(mapping_file: str) -> None:
    """Очищает заголовки в figure_mapping.json (поле title)."""
    if not os.path.exists(mapping_file):
        return
    try:
        with open(mapping_file, "r", encoding="utf-8") as f:
            mapping = json.load(f)
    except Exception:
        return

    updated = False
    for key, info in list(mapping.items()):
        if isinstance(info, dict) and isinstance(info.get("title"), str):
            original = info["title"]
            cleaned = apply_safe_word_fixes(normalize_figure_refs(normalize_whitespace_punctuation(original)))
            if cleaned != original:
                info["title"] = cleaned
                updated = True

    if updated:
        try:
            with open(mapping_file, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


