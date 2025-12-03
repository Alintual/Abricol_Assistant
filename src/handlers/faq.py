import logging
import os
import re
import tempfile
import unicodedata
from collections.abc import Sequence
from functools import lru_cache

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    InputFile,
)
from aiogram.enums import ParseMode
from sqlalchemy import desc, select

from ..deepseek_client import deepseek
from ..knowledge import search_store
from ..knowledge.text_search import STRUCTURED_DIR
from ..knowledge import image_mapper
from .. import prompt_config
from ..db.chat_history import get_chat_history, save_chat_message
from ..db.user_profile import get_or_create_user_profile, update_user_profile, get_user_profile, reset_user_profile_fields, check_status_changed
from ..handlers.booking import BookingStates
from ..handlers.policy import show_policy_window
from ..stt_client import transcribe_file


router = Router()

LINKS_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "knowledge", "data", "links.txt")
)

PRIMARY_SOURCE_LABELS: dict[str, str] = {
    "2.1.2_Правила игры Корона_structured.txt": "Правила игры Корона_2021.pdf",
    "2.1.1_Международные правила_structured.txt": "Международные правила Пирамиды_2018.pdf",
    "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt": (
        "Технические требования к бильярдным столам и оборудованию ФБСР_2020.pdf"
    ),
}
CORONA_SOURCE = "2.1.2_Правила игры Корона_structured.txt"
TECHNICAL_REQUIREMENTS_SOURCE = "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt"

PRIMARY_SOURCE_ALIASES: dict[str, str] = {
    "корона": "2.1.2_Правила игры Корона_structured.txt",
    "игре корона": "2.1.2_Правила игры Корона_structured.txt",
    "правила корона": "2.1.2_Правила игры Корона_structured.txt",
    "международ": "2.1.1_Международные правила_structured.txt",
    "пирамида": "2.1.1_Международные правила_structured.txt",
    "правила": "2.1.1_Международные правила_structured.txt",
    "требован": "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt",
    "технич": "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt",
    "размер": "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt",
    "аксес": "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt",
    "оборуд": "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt",
}

STOP_WORDS_FOR_PRIMARY = {"обучен", "биса", "методик", "абонемент", "курс", "урок", "заняти", "оплат",}

# Стоп-слова в ответе LLM, при наличии которых кнопка "Первоисточник" не показывается
STOP_WORDS_IN_LLM_RESPONSE = {"извините", "затрудня", "запрос", "консульт"}

# КРИТИЧЕСКИЕ стоп-слова в ответе LLM - жесткая блокировка кнопки "Первоисточник"
# Даже для правил (rule_query=True) кнопка НЕ показывается, если в ответе есть эти слова
CRITICAL_STOP_WORDS_IN_LLM_RESPONSE = {"затрудн", "извин"}

RULE_SOURCE_PATTERNS = (
    "2.1.1_",
    "2.1.2_",
    "2.2_",
)

RULE_PRIMARY_ALLOWED_SOURCES = {
    "2.1.1_Международные правила_structured.txt",
    "2.1.2_Правила игры Корона_structured.txt",
    "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt",
}

RULE_INTENT_KEYWORDS = (
    "правил",
    "требован",
    "техническ",
    "игр",
    "корона",
    "международ",
    "фбср",
    "оборуд",
    "аксес",
    "биток",
    "прицел",
    "удар",
)

# Ключевые слова для Темы 1 (Информация по школе)
SCHOOL_TOPIC_KEYWORDS = (
    "школ", "обучен", "курс", "урок", "занят", "тренировк", "методик",
    "сертификат", "абонемент", "программ", "тренер", "наставник",
    "абриколь", "биса", "система", "виды обуч", "стоимость", "цена",
    "начальн",  # "начальный" относится к школе (начальный курс), а не к правилам
)

PRIMARY_SOURCE_TELEGRAM_LIMIT = 3500


def classify_topic(query: str) -> tuple[str, float]:
    """
    Классифицирует запрос по темам общения.

    Args:
        query: Текст запроса пользователя

    Returns:
        tuple: (topic, confidence) где topic может быть:
            - "school" (Тема 1: Информация по школе)
            - "rules" (Тема 2: Правила и справка по бильярду)
            - "unknown" (неопределенная тема)
        confidence: уверенность от 0.0 до 1.0
    """
    if not query:
        return "unknown", 0.0

    query_lower = query.lower()

    # Подсчитываем совпадения по каждой теме
    school_matches = sum(1 for kw in SCHOOL_TOPIC_KEYWORDS if kw in query_lower)
    rules_matches = sum(1 for kw in RULE_INTENT_KEYWORDS if kw in query_lower)

    # Исключаем слова из Темы 2, которые могут быть в Теме 1
    # Например, "игр" может быть и в "играть на бильярде" и в "правила игры"
    # Но если есть специфичные слова правил - это точно Тема 2
    rules_specific = ["правил", "требован", "техническ", "корона", "международ", "фбср"]
    has_rules_specific = any(kw in query_lower for kw in rules_specific)

    # Если есть специфичные слова правил - это определенно Тема 2
    if has_rules_specific:
        return "rules", min(1.0, 0.5 + rules_matches * 0.1)

    # Если больше совпадений по школе - Тема 1
    if school_matches > rules_matches:
        return "school", min(1.0, 0.3 + school_matches * 0.15)

    # Если больше совпадений по правилам - Тема 2
    if rules_matches > school_matches:
        return "rules", min(1.0, 0.3 + rules_matches * 0.15)

    # Если равное количество или нет совпадений - неопределенная тема
    return "unknown", 0.0


def _unique_preserving(seq: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _normalize_source_name(source: str | None) -> str:
    if not source:
        return ""
    return re.sub(r"\s+", "", source.lower())


def _collect_fragments_by_source(
    fragments: list[dict],
    main_source: str | None,
    source_name: str,
) -> list[dict]:
    if not fragments or not source_name:
        return []
    try:
        normalized_target = _normalize_source_name(source_name)
        collected: list[dict] = []
        for fragment in fragments:
            if not isinstance(fragment, dict):
                continue
            fragment_source = fragment.get("source") or main_source
            if fragment_source and _normalize_source_name(fragment_source) == normalized_target:
                collected.append(fragment)
        return collected
    except Exception:
        return []


def _fragments_contain_keywords(
    fragments: list[dict],
    keywords: tuple[str, ...],
    exclude_keywords: tuple[str, ...] | None = None,
) -> bool:
    if not fragments or not keywords:
        return False
    try:
        excludes = exclude_keywords or ()
        for fragment in fragments:
            if not isinstance(fragment, dict):
                continue
            text = (fragment.get("text") or "").lower()
            if not text:
                continue
            if excludes and any(exclude in text for exclude in excludes):
                continue
            if any(keyword in text for keyword in keywords):
                return True
        return False
    except Exception:
        return False


def _is_rules_source(source: str | None) -> bool:
    normalized = _normalize_source_name(source)
    return any(normalized.startswith(pattern.replace(" ", "")) for pattern in RULE_SOURCE_PATTERNS)


def is_rule_intent(query: str) -> bool:
    """
    Определяет, относится ли запрос к правилам игры.
    Использует более строгую проверку для избежания ложных срабатываний.
    """
    if not query or len(query.strip()) < 3:
        return False

    lowered = query.lower().strip()

    # Исключаем запросы, которые точно не про правила
    # (вопросы о боте, приветствия, общие вопросы)
    excluded_patterns = [
        "ты кто", "кто ты", "что ты", "что такое ты",
        "помощь", "помоги", "что умеешь", "что можешь",
        "привет", "здравствуй", "добрый", "доброе",
        "как дела", "как поживаешь",
    ]
    for pattern in excluded_patterns:
        if pattern in lowered:
            return False

    # Проверяем ключевые слова, но только если запрос достаточно информативен
    # Для коротких запросов (менее 10 символов) требуем более специфичные ключевые слова
    has_rule_keyword = any(word in lowered for word in RULE_INTENT_KEYWORDS)

    if len(lowered) < 10:
        # Для коротких запросов требуем более специфичные ключевые слова
        # Включаем "аксес" и "оборуд" для технических требований
        specific_keywords = ["правил", "требован", "техническ", "корона", "международ", "пирамида", "фбср", "аксес", "оборуд"]
        has_specific = any(kw in lowered for kw in specific_keywords)
        return has_specific and has_rule_keyword

    return has_rule_keyword


def _load_download_links() -> dict[str, str]:
    links: dict[str, str] = {}
    if not os.path.exists(LINKS_FILE_PATH):
        return links
    try:
        with open(LINKS_FILE_PATH, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line or " - " not in line:
                    continue
                left, url = line.split(" - ", 1)
                left = re.sub(r"^\d+\.\s*", "", left.strip())
                url = url.strip()
                if left and url:
                    links[left] = url
    except OSError:
        return {}
    return links


def _get_download_info_for_source(source: str | None) -> dict[str, str] | None:
    if not source:
        return None
    label = PRIMARY_SOURCE_LABELS.get(source)
    if not label:
        return None
    url = _load_download_links().get(label)
    if not url:
        return None
    return {"label": label, "url": url}


def remove_hash_and_trash(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"#+", "", text)
    cleaned = re.sub(r"[\s•→\*]+$", "", cleaned)
    cleaned = re.sub(r"^рис\.\s*", "", cleaned, flags=re.IGNORECASE)
    # НЕ удаляем цифры в начале, если это часть "РАЗДЕЛ 5." или "РАЗДЕЛ 1."
    if not re.match(r'РАЗДЕЛ\s+\d+\.', cleaned, re.IGNORECASE):
        cleaned = re.sub(r"^[\d. ]+", "", cleaned)
    return cleaned.strip()


def _truncate_primary_source_text(text: str) -> str:
    if len(text) <= PRIMARY_SOURCE_TELEGRAM_LIMIT:
        return text
    # Обрезаем по границам строк, чтобы не обрезать посередине
    max_length = PRIMARY_SOURCE_TELEGRAM_LIMIT - 70
    if len(text) <= max_length:
        return text

    # Находим последний перенос строки перед лимитом
    trimmed = text[:max_length]
    last_newline = trimmed.rfind('\n')
    if last_newline > max_length * 0.8:  # Если перенос строки не слишком далеко от конца
        trimmed = text[:last_newline].rstrip()
    else:
        # Если переноса строки нет близко, обрезаем по последнему пробелу
        last_space = trimmed.rfind(' ')
        if last_space > max_length * 0.8:
            trimmed = text[:last_space].rstrip()
        else:
            trimmed = trimmed.rstrip()

    return f"{trimmed}\n… (фрагмент сокращён, превышен лимит Telegram)"


_BOLD_LINE_PATTERN = re.compile(r"^\s*\*\*(.+?)\*\*\s*$", re.MULTILINE)
CTA_KEYWORDS = (
    "запис",
    "оставит заявку",
    "оставь заявку",
    "свяж",
    "напиш",
    "напис",
    "позвон",
    "хотите",
    "узна",
    "жела",
    "помогу",
    "помочь",
    "скаж",
    "сказ",
    "телеф",
    "готов",
    "могу",
)

BRACKETED_COUNT_FIGURE_PATTERN = re.compile(
    r"\[\s*\d+\s+(?:упражнен\w*|задач\w*)\s*\]",
    re.IGNORECASE,
)

COUNT_FIGURE_PATTERN = re.compile(
    r"\b\d+\s+(?:упражнен\w*|задач\w*)\b",
    re.IGNORECASE,
)

GENERIC_SECTION_MARKERS = {"раздел"}


def _normalize_primary_body(text: str) -> str:
    if not text:
        return text

    lines = text.splitlines()
    paragraphs: list[str] = []
    current: list[str] = []
    enum_pattern = re.compile(r"^(?:\(?\d+[\).]|[-•])\s")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            i += 1
            continue

        # Если строка начинается с паттерна списка, всегда создаем отдельный параграф
        # И продолжаем читать следующие строки до следующего пункта списка или пустой строки
        if enum_pattern.match(stripped) or stripped.lower().startswith("примечание"):
            if current:
                paragraphs.append(" ".join(current))
                current = []

            # Собираем все строки пункта списка в один параграф
            list_item_lines = [stripped]
            i += 1
            # Продолжаем читать следующие строки, пока не встретим новый пункт списка или пустую строку
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    # Пустая строка - конец пункта списка
                    break
                # Если следующая строка - новый пункт списка, останавливаемся
                if enum_pattern.match(next_line) or next_line.lower().startswith("примечание"):
                    break
                # Иначе это продолжение текущего пункта списка
                list_item_lines.append(next_line)
                i += 1

            # Объединяем все строки пункта списка в один параграф
            paragraphs.append(" ".join(list_item_lines))
            continue

        current.append(stripped)
        i += 1

    if current:
        paragraphs.append(" ".join(current))

    # Объединяем параграфы: пункты списка разделяем одним переносом строки
    # обычные параграфы - двойным переносом строки
    cleaned_parts = []
    for i, para in enumerate(paragraphs):
        if i > 0:
            prev_enum = bool(enum_pattern.match(paragraphs[i-1]) or paragraphs[i-1].lower().startswith("примечание"))
            curr_enum = bool(enum_pattern.match(para) or para.lower().startswith("примечание"))
            # Если предыдущий или текущий параграф - пункт списка, используем один перенос строки
            if prev_enum or curr_enum:
                cleaned_parts.append("\n")
            else:
                cleaned_parts.append("\n\n")
        cleaned_parts.append(para)

    cleaned = "".join(cleaned_parts)
    # Убираем множественные пробелы, но сохраняем переносы строк
    # Важно: не разбиваем предложения на переносах строк внутри параграфа
    # Объединяем строки внутри параграфа пробелом, но сохраняем переносы между параграфами
    cleaned = re.sub(r"[ \t]+", " ", cleaned)  # Только пробелы и табы, не переносы строк
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # Максимум 2 переноса строки подряд

    # Исправляем случаи, когда текст обрывается на полуслове из-за неправильного разбиения
    # Проблема: короткие строки (1-3 буквы) могут быть разорванными словами
    # Объединяем их с предыдущей или следующей строкой
    lines = cleaned.split('\n')
    fixed_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            fixed_lines.append(line)
            i += 1
            continue

        # Проверяем, является ли строка пунктом списка
        is_list_item = enum_pattern.match(stripped)

        # Если строка короткая (1-3 буквы) и не пункт списка
        if not is_list_item and len(stripped) <= 3:
            # Проверяем предыдущую строку - если она заканчивается коротким словом
            # и не заканчивается пунктуацией (точка, двоеточие, точка с запятой), объединяем
            if fixed_lines:
                prev_line = fixed_lines[-1].strip()
                # Проверяем, заканчивается ли предыдущая строка коротким словом (1-3 буквы)
                # и не заканчивается ли пунктуацией
                if prev_line and not prev_line.endswith(('.', ':', ';', '-', '—')):
                    # Находим последнее слово в предыдущей строке
                    words = prev_line.split()
                    if words:
                        last_word = words[-1].rstrip('.,;:!?')
                        if len(last_word) <= 3 and last_word.isalpha():
                            # Объединяем с предыдущей строкой
                            fixed_lines[-1] = fixed_lines[-1].rstrip() + ' ' + stripped
                            i += 1
                            continue

            # Если не объединили с предыдущей, проверяем следующую строку
            if i + 1 < len(lines):
                next_stripped = lines[i + 1].strip()
                # Объединяем только если следующая строка не пустая и не пункт списка
                if next_stripped and not enum_pattern.match(next_stripped):
                    # Объединяем строки
                    fixed_lines.append(stripped + ' ' + next_stripped)
                    i += 2
                    continue

        fixed_lines.append(line)
        i += 1

    cleaned = '\n'.join(fixed_lines)

    # Дополнительная проверка: объединяем строки, которые заканчиваются короткими словами
    # и продолжаются на следующей строке
    lines = cleaned.split('\n')
    final_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            final_lines.append(line)
            i += 1
            continue

        is_list_item = enum_pattern.match(stripped)

        # Если строка заканчивается коротким словом (1-3 буквы), проверяем следующую
        # Это может быть часть пункта списка или обычного текста
        if i + 1 < len(lines):
            words = stripped.split()
            if words:
                last_word = words[-1].rstrip('.,;:!?')
                # Если последнее слово короткое (1-3 буквы) и строка не заканчивается пунктуацией
                if len(last_word) <= 3 and last_word.isalpha() and not stripped.rstrip().endswith(('.', ':', ';')):
                    next_stripped = lines[i + 1].strip()
                    # Объединяем, если следующая строка не пустая и не новый пункт списка
                    # (но может быть продолжением текущего пункта)
                    if next_stripped and not enum_pattern.match(next_stripped):
                        # Не объединяем, если следующая строка начинается с заглавной буквы после двоеточия
                        # (это может быть новое предложение)
                        if not (is_list_item and next_stripped[0].isupper() and ':' in stripped):
                            # Объединяем строки
                            final_lines.append(stripped.rstrip() + ' ' + next_stripped)
                            i += 2
                            continue

        final_lines.append(line)
        i += 1

    cleaned = '\n'.join(final_lines)
    return cleaned.strip()


def _is_generic_section_marker(text: str) -> bool:
    if not text:
        return False
    normalized = re.sub(r"[#:\s]+", "", text.lower())
    return normalized in GENERIC_SECTION_MARKERS


def _truncate_to_single_point(text: str, header_line: str | None = None, rule_number: str | None = None) -> str:
    """
    Обрезает текст до первого пункта/подпункта, чтобы в окне показывался только один пункт.
    Это соответствует общим правилам формирования окон.
    """
    if not text:
        return text

    lines = text.split('\n')
    if not lines:
        return text

    # Определяем номер первого пункта из header_line или rule_number
    first_point_number = None
    if header_line:
        # Извлекаем номер из header_line (например, "1. Название" -> "1")
        match = re.match(r'^(\d+(?:\.\d+)*)', header_line.strip())
        if match:
            first_point_number = match.group(1)
    elif rule_number:
        # Используем rule_number
        first_point_number = rule_number.strip().rstrip('.')

    # Если не нашли номер из header_line/rule_number, пытаемся найти в первой строке текста
    if not first_point_number:
        first_line = lines[0].strip() if lines else ""
        match = re.match(r'^(\d+(?:\.\d+)*)', first_line)
        if match:
            first_point_number = match.group(1)

    if not first_point_number:
        # Если не нашли номер, возвращаем весь текст
        return text

    # Определяем уровень первого пункта (количество точек в номере)
    first_level = first_point_number.count('.') + 1

    # Ищем следующий пункт того же или более высокого уровня
    result_lines = [lines[0]]  # Всегда включаем первую строку

    for i in range(1, len(lines)):
        line = lines[i].strip()
        if not line:
            # Пустые строки включаем, но проверяем следующую строку
            result_lines.append(lines[i])
            continue

        # Проверяем, является ли строка началом нового пункта/подпункта
        # Паттерн: номер пункта в начале строки (например, "1.", "1.1.", "2.", "2.1." и т.д.)
        point_match = re.match(r'^(\d+(?:\.\d+)*)(?:\.)?\s+', line)
        if point_match:
            current_point_number = point_match.group(1)
            current_level = current_point_number.count('.') + 1

            # Если это пункт того же или более высокого уровня - останавливаемся
            if current_level <= first_level:
                # Проверяем, что это действительно другой пункт (не продолжение текущего)
                if current_point_number != first_point_number:
                    break

        # Включаем строку в результат
        result_lines.append(lines[i])

    return '\n'.join(result_lines)


def _remove_generic_section_lines(text: str) -> str:
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        if _is_generic_section_marker(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _is_emoji_only(text: str) -> bool:
    meaningful = [ch for ch in text if unicodedata.category(ch) not in {"Mn", "Me", "Cf", "Cc"}]
    if not meaningful:
        return False
    if len(meaningful) > 4:
        return False
    if any(ch.isalnum() for ch in meaningful):
        return False
    return all(unicodedata.category(ch).startswith("S") for ch in meaningful)


def _remove_lonely_emojis(text: str) -> str:
    if not text:
        return text
    lines = text.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and _is_emoji_only(stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _normalize_cta_block(text: str) -> str:
    if not text:
        return text
    lines = text.splitlines()
    cta_index: int | None = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        lower = stripped.lower()
        has_cta_keyword = any(keyword in lower for keyword in CTA_KEYWORDS)
        is_question = stripped.endswith("?")
        if has_cta_keyword or is_question:
            cta_index = i
            break
    if cta_index is None:
        return text
    stripped_cta = lines[cta_index].lstrip()
    if stripped_cta.startswith("🎯"):
        content = stripped_cta[1:].lstrip()
    else:
        content = stripped_cta
    stripped_content = content.lstrip("".join(ch for ch in content if _is_emoji_only(ch)))
    lines[cta_index] = f"🎯 {stripped_content.strip()}"
    return "\n".join(lines)


# Вспомогательная функция: гарантировать пустую строку перед блоком CTA/вопросов
def _ensure_cta_spacing(text: str) -> str:
    if not text:
        return text

    lines = text.splitlines()
    cta_index: int | None = None

    # Находим последнюю строку с СТА (ищем с конца)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        lower = stripped.lower()
        has_cta_keyword = any(keyword in lower for keyword in CTA_KEYWORDS)
        is_question = stripped.endswith("?")
        if has_cta_keyword or is_question:
            cta_index = i
            break

    if cta_index is None or cta_index == 0:
        return text

    # Убеждаемся, что перед СТА есть одна пустая строка
    if lines[cta_index - 1].strip():
        lines.insert(cta_index, "")
        cta_index += 1

    # Добавляем эмодзи к СТА, если его нет
    current = lines[cta_index].lstrip()
    if current and not current.startswith("🎯"):
        lines[cta_index] = f"🎯 {current}"
    elif not current:
        lines[cta_index] = "🎯"

    # Находим конец СТА блока (может быть несколько строк)
    cta_end = cta_index
    while cta_end < len(lines) - 1:
        next_line = lines[cta_end + 1].strip()
        if not next_line:
            cta_end += 1
        elif any(keyword in next_line.lower() for keyword in CTA_KEYWORDS) or next_line.endswith("?"):
            cta_end += 1
        else:
            break

    # Проверяем количество пустых строк после СТА блока
    # Находим первую непустую строку после СТА блока
    first_non_empty_after_cta = None
    for i in range(cta_end + 1, len(lines)):
        if lines[i].strip():
            first_non_empty_after_cta = i
            break

    if first_non_empty_after_cta is not None:
        # Подсчитываем пустые строки между СТА и основным текстом
        empty_lines_count = first_non_empty_after_cta - cta_end - 1

        # Если пустых строк больше одной, оставляем только одну
        if empty_lines_count > 1:
            # Удаляем лишние пустые строки, оставляя только одну
            lines_to_remove = empty_lines_count - 1
            for _ in range(lines_to_remove):
                lines.pop(cta_end + 1)
        # Если пустых строк нет, добавляем одну
        elif empty_lines_count == 0:
            lines.insert(cta_end + 1, "")

    return "\n".join(lines)


def _bold_to_arrow(text: str) -> str:
    """Преобразует строки вида **Курсы:** в маркер-стрелку."""
    if not text or not isinstance(text, str):
        return text if isinstance(text, str) else ""

    def _replace(match: re.Match[str]) -> str:
        content = match.group(1).strip()
        if not content:
            return ""
        return f"→ {content}"

    return _BOLD_LINE_PATTERN.sub(_replace, text)


def _split_into_sentences(text: str) -> list[str]:
    """Разделяет текст на предложения по критериям:
    
    Предложение:
    - Начинается с заглавной буквы (или цифры для списков)
    - Заканчивается на ".", "?", "!" или "..."
    - После конечных символов следует пробел или конец строки
    
    Args:
        text: Текст для разделения
        
    Returns:
        Список предложений (без пустых)
    """
    if not text:
        return []
    
    # Нормализуем текст: заменяем все пробельные символы на один пробел
    # Также нормализуем многоточие: заменяем символ многоточия (…) на три точки
    normalized_text = re.sub(r'…', '...', text.strip())
    normalized_text = re.sub(r'\s+', ' ', normalized_text)
    if not normalized_text:
        return []
    
    # Разделяем по знакам препинания (включая "...") с пробелом или концом строки после них
    # Паттерн: многоточие или одиночный знак препинания, за которым следует пробел или конец строки
    # Используем lookahead для проверки пробела или конца строки
    parts = re.split(r'(\.\.\.|[.!?])(?=\s+|$)', normalized_text)
    
    sentences = []
    current_sentence = ''
    
    i = 0
    while i < len(parts):
        part = parts[i]
        if not part:
            i += 1
            continue
        
        # Если это знак препинания (многоточие или одиночный знак)
        if part in ['.', '!', '?', '...']:
            current_sentence += part
            # Завершаем предложение (знак препинания означает конец предложения)
            if current_sentence.strip():
                sentences.append(current_sentence.strip())
                current_sentence = ''
            i += 1
        else:
            # Это текст предложения (может содержать пробелы в начале)
            # Убираем пробелы в начале, если это не первая часть предложения
            if current_sentence:
                part = part.lstrip()  # Убираем пробелы в начале, если уже есть текст
            current_sentence += part
            i += 1
    
    # Добавляем последнее предложение, если оно есть (без знака препинания в конце)
    if current_sentence.strip():
        sentences.append(current_sentence.strip())
    
    # Фильтруем предложения: должны начинаться с заглавной буквы или цифры
    filtered_sentences = []
    for sentence in sentences:
        stripped = sentence.strip()
        if not stripped:
            continue
        
        # Убираем пробелы в начале и проверяем первую букву
        # Проверяем, начинается ли с заглавной буквы или цифры
        first_char = stripped.lstrip()[0] if stripped.lstrip() else ''
        if first_char and (first_char.isupper() or first_char.isdigit()):
            filtered_sentences.append(stripped)
    
    return filtered_sentences


def _move_cta_to_end(text: str) -> str:
    """Анализирует конец текста на наличие критериев CTA и формирует блок CTA.
    
    ВАЖНО: 
    1. Ищется фрагмент в конце основного текста, который отвечает критериям CTA
    2. Формируется из него CTA блок со знаком 🎯, с новой строки, с одной пустой строкой сверху
    3. В CTA входит ЛЮБОЙ текст в конце основного сообщения, отвечающий критериям CTA
    
    Критерии CTA:
    - Предложения с вопросами (знак "?") ИЛИ ключевыми словами CTA
    """
    if not text:
        return text

    # ВАЖНО: Текст может прийти уже с переносами строк (после _format_llm_response_layout)
    # Используем функцию _split_into_sentences для правильного разделения на предложения
    sentences = _split_into_sentences(text)
    if not sentences:
        return text
    
    # Ограничиваем поиск последними 5 предложениями
    # Ищем СВЕРХУ ВНИЗ (с начала последних 5 предложений) первое релевантное предложение
    search_limit = min(5, len(sentences))  # Последние 5 предложений
    last_5_start = len(sentences) - search_limit  # Начало последних 5 предложений
    
    cta_start_index = None
    cta_start_index_by_keyword = None
    
    # Идем СВЕРХУ ВНИЗ в пределах последних 5 предложений (с начала последних 5 к концу)
    # Сначала ищем предложения с вопросами (приоритет)
    for i in range(last_5_start, len(sentences)):
        sentence = sentences[i]
        stripped = sentence.strip()
        if not stripped:
            continue
        
        is_question = "?" in stripped or stripped.endswith("?")
        if is_question:
            # Нашли первое предложение с вопросом - это начало CTA блока
            cta_start_index = i
            break
    
    # Если не нашли предложение с вопросом, ищем предложения с ключевыми словами
    if cta_start_index is None:
        for i in range(last_5_start, len(sentences)):
            sentence = sentences[i]
            stripped = sentence.strip()
            if not stripped:
                continue
            
        lower = stripped.lower()
        has_cta_keyword = any(keyword in lower for keyword in CTA_KEYWORDS)
            if has_cta_keyword:
                # Нашли первое предложение с ключевым словом - это начало CTA блока
                cta_start_index = i
                break
    
    # Если CTA не найден в последних 5 предложениях, возвращаем исходный текст
    if cta_start_index is None:
        return text

    # Разделяем на основной текст и CTA блок
    # В CTA идут ВСЕ предложения начиная с первого найденного релевантного предложения до конца
    # (независимо от наличия критериев в последующих предложениях)
    other_sentences = sentences[:cta_start_index]
    cta_sentences = sentences[cta_start_index:]
    
    # Формируем основной текст и CTA блок
    main_part = " ".join(other_sentences).strip()
    cta_part = " ".join(cta_sentences).strip()

    if main_part and cta_part:
        return f"{main_part}\n\n{cta_part}"
    if cta_part:
        return cta_part
    return main_part


def _normalize_arrows(text: str) -> str:
    """Заменяет повторяющиеся стрелки → на единый маркер 👉."""
    if not text:
        return text

    def _replace_line(line: str) -> str:
        stripped = line.lstrip()
        if stripped.startswith("-") or stripped.startswith("•"):
            return line
        replaced = re.sub(r"(→\s*){1,}", "👉 ", line)
        replaced = re.sub(r"^(\s*)(👉\s*){1,}", r"\1👉 ", replaced)
        return replaced

    return "\n".join(_replace_line(line) for line in text.split("\n"))


def _strip_unwanted_symbols(text: str) -> str:
    """Удаляет служебные символы оформления."""
    if not text:
        return text
    text = text.replace("**", "")
    text = text.replace("→", "")
    text = text.replace("#", "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _validate_anketa_answer(answer: str, question_num: int) -> tuple[bool, str]:
    """
    Проверяет релевантность ответа на вопрос анкеты без использования LLM.

    Args:
        answer: Ответ пользователя
        question_num: Номер вопроса (1-4)

    Returns:
        tuple[bool, str]: (is_valid, reason)
        - is_valid: True если ответ релевантен, False если нет
        - reason: Причина отклонения (если is_valid=False) или пустая строка
    """
    if not answer:
        return False, "Ответ пустой"

    answer_lower = answer.lower().strip()
    answer_length = len(answer_lower)

    # Для вопроса 4 (Да/Нет) разрешаем короткие ответы "да"/"нет"
    if question_num == 4:
        yes_words = ["да", "yes"]
        no_words = ["нет", "no"]
        if answer_lower in yes_words or answer_lower in no_words:
            # Для явных "да"/"нет" пропускаем проверку на минимальную длину
            pass
        elif answer_length < 3:
            return False, "Слишком короткий ответ"
    else:
        # Проверка на слишком короткий ответ (меньше 3 символов) для остальных вопросов
        if answer_length < 3:
            return False, "Слишком короткий ответ"

    # Проверка на явные признаки непонимания или отказа отвечать
    skip_phrases = [
        "не знаю", "не понимаю", "не понял", "не поняла",
        "не знаю что", "не знаю как", "не могу", "не хочу",
        "затрудняюсь", "не уверен", "не уверена",
        "?", "??", "???",  # Только знаки вопроса
        "что", "как", "почему", "зачем",  # Вопросы вместо ответов
    ]

    # Если ответ состоит только из знаков вопроса или начинается с вопроса
    if answer_lower.strip() in ["?", "??", "???"] or answer_lower.startswith("?"):
        return False, "Ответ содержит только вопрос"

    # Проверка на попытку задать свой вопрос вместо ответа
    question_words = ["что", "как", "почему", "зачем", "когда", "где", "кто"]
    if any(answer_lower.startswith(word + " ") for word in question_words):
        return False, "Ответ начинается с вопроса"

    # Проверка на явные фразы пропуска
    if any(phrase in answer_lower for phrase in skip_phrases):
        # Но если это не единственное содержимое, то может быть нормально
        if answer_length < 20:  # Если короткий и содержит skip_phrase - отклоняем
            return False, "Ответ содержит фразу непонимания"

    # Специфичные проверки для каждого вопроса
    if question_num == 1:  # Опыт игры
        # Ключевые слова, связанные с опытом
        experience_keywords = [
            "играю", "играл", "играла", "игра", "опыт", "лет", "год", "года",
            "месяц", "месяцев", "раз", "раза", "разов", "играть", "играл", "играла",
            "новичок", "начинающ", "умею", "умею играть", "не умею", "не играл",
            "бильярд", "пирамида", "стол", "шары", "кий"
        ]
        if not any(keyword in answer_lower for keyword in experience_keywords):
            # Если нет ключевых слов, но ответ достаточно длинный - принимаем
            if answer_length < 10:
                return False, "Ответ не содержит информации об опыте"

    elif question_num == 2:  # Уровень подготовки
        level_keywords = [
            "уровень", "новичок", "начинающ", "средн", "продвинут", "профессионал",
            "любитель", "начальн", "базов", "высок", "низк", "слаб", "сильн",
            "опытн", "неопытн", "умею", "не умею", "знаю", "не знаю", "кий"
        ]
        if not any(keyword in answer_lower for keyword in level_keywords):
            if answer_length < 8:
                return False, "Ответ не содержит информации об уровне"

    elif question_num == 3:  # Цели обучения
        goals_keywords = [
            "хочу", "желаю", "нужно", "надо", "цель", "цели", "научиться", "изучить",
            "освоить", "улучшить", "развить", "получить", "приобрести", "навык",
            "техник", "играть", "игра", "бильярд", "кий", "пирамида", "турнир", "соревнован"
        ]
        if not any(keyword in answer_lower for keyword in goals_keywords):
            if answer_length < 8:
                return False, "Ответ не содержит информации о целях"

    elif question_num == 4:  # Обучение ранее (Да/Нет)
        # Для 4-го вопроса проверка проще - ищем "да"/"нет" или похожие слова
        yes_words = ["да", "yes", "учил", "обучал", "училась", "обучалась", "был", "была"]
        no_words = ["нет", "no", "не учил", "не обучал", "не училась", "не обучалась", "не был", "не была"]

        has_yes = any(word in answer_lower for word in yes_words)
        has_no = any(word in answer_lower for word in no_words)

        if not (has_yes or has_no):
            # Если нет явного да/нет, но ответ короткий - отклоняем
            if answer_length < 5:
                return False, "Ответ не содержит явного согласия или отказа"
            # Если ответ длинный, возможно пользователь объясняет - принимаем

    # Если все проверки пройдены
    return True, ""


def _format_pointers_and_bold(text: str) -> str:
    """Форматирует фразы типа '👉текст:', '📅 текст:' (с любым эмодзи) и '*текст*'."""
    if not text:
        return text

    # Сначала обрабатываем фразы типа "*текст*" - заменяем на <b>текст</b> ДО обработки эмодзи
    # Это важно, чтобы не перепутать звездочки с другими символами
    def replace_bold(match):
        content = match.group(1).strip()
        full_match = match.group(0)  # Полное совпадение со звездочками
        # НЕ выделяем жирным и НЕ удаляем звездочки, если внутри есть знаки препинания (. ! ?)
        # Это означает, что звездочки обрамляют целое предложение, а не отдельное слово/фразу
        if re.search(r'[.!?]', content):
            # Возвращаем с звездочками, но без выделения жирным
            return full_match
        # Заменяем *текст* на <b>текст</b> ТОЛЬКО если внутри нет знаков препинания
        return f'<b>{content}</b>'

    # Заменяем *текст* на <b>текст</b>
    # Обрабатываем все варианты: *текст*, * текст*, *текст *, * текст *
    # Ищем одиночные звездочки, которые не являются частью двойных
    # Паттерн: *текст*, где текст может содержать пробелы, буквы, цифры и знаки препинания
    # Используем нежадный поиск (?) для корректной обработки нескольких вхождений
    # Важно: обрабатываем до того, как другие функции могут удалить звездочки
    text = re.sub(r'(?<!\*)\*\s*([^*]+?)\s*\*(?!\*)', replace_bold, text)

    # Удаляем 👉 если после него идет другое эмодзи (например "👉 📚 Курсы:" -> "📚 Курсы:")
    # Паттерн для эмодзи
    emoji_pattern = r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002700-\U000027BF\U0001F900-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF\U00002000-\U0000206F\U00002070-\U0000209F\U00002190-\U000021FF\U00002B00-\U00002BFF]'
    # Удаляем 👉 если после него (с пробелами) идет другое эмодзи
    text = re.sub(r'👉\s+({})'.format(emoji_pattern), r'\1', text)

    # Обрабатываем фразы типа "📅 текст:" или "👉текст:" - переносим на новую строку, если они не на новой строке
    # Ищем любой символ, который может быть эмодзи (широкий диапазон Unicode)

    # Обрабатываем фразы с эмодзи в начале, за которым следует текст и двоеточие
    # Ищем паттерн: эмодзи + пробелы (опционально) + текст + двоеточие
    # Улучшенный паттерн: эмодзи может быть один или несколько подряд
    text = re.sub(r'([^\n])({}+\s*[^\n:]+:)'.format(emoji_pattern), r'\1\n\2', text)
    # Убеждаемся, что эмодзи в начале строки не имеет лишних пробелов перед ним
    text = re.sub(r'(\n|^)\s+({}+\s*[^\n:]+:)'.format(emoji_pattern), r'\1\2', text, flags=re.MULTILINE)

    # Переносим <b>текст</b> на новую строку, если они не на новой строке
    # Ищем <b>текст</b> которые идут после текста на той же строке
    text = re.sub(r'([^\n])(<b>[^<]+</b>)', r'\1\n\2', text)
    # Убеждаемся, что <b>текст</b> в начале строки не имеет лишних пробелов
    text = re.sub(r'(\n|^)\s+(<b>[^<]+</b>)', r'\1\2', text, flags=re.MULTILINE)

    return text


def _format_llm_response_layout(text: str) -> str:
    """
    Форматирует ответ LLM перед отправкой в чат согласно правилам:
    1. Каждое предложение с новой строки
    2. Строки типа "N. текст", "* текст", "👉 текст", "👉 текст:" на новую строку
    3. Строки типа "* текст *" - убрать **, сделать жирным, на новую строку
    4. Строки типа "— текст" НЕ переносятся на новую строку
    """
    if not text:
        return text

    # Шаг 0: Объединяем строки, начинающиеся с "—", с предыдущей строкой (делаем это ПЕРВЫМ делом)
    lines = text.split('\n')
    merged_lines = []

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            merged_lines.append('')
            continue

        # Если строка начинается с "—", объединяем её с предыдущей строкой
        if line_stripped.startswith('—'):
            if merged_lines:
                # Объединяем с предыдущей строкой (убираем перенос строки)
                merged_lines[-1] = merged_lines[-1].rstrip() + ' ' + line_stripped
            else:
                # Если это первая строка, оставляем как есть
                merged_lines.append(line_stripped)
        else:
            merged_lines.append(line)

    text = '\n'.join(merged_lines)

    # Шаг 1: Обрабатываем строки типа "* текст *" - убираем ** и делаем жирным
    # ВРЕМЕННО ОТКЛЮЧЕНО: выделение жирным
    # def replace_double_bold(match):
    #     content = match.group(1).strip()
    #     return f'\n<b>{content}</b>'
    #
    # # Заменяем **текст** на <b>текст</b> с переносом на новую строку
    # text = re.sub(r'\*\*([^*]+?)\*\*', replace_double_bold, text)
    #
    # # Обрабатываем строки типа "* текст *" (одиночные звездочки с пробелами)
    # text = re.sub(r'(?<!\*)\*\s+([^*]+?)\s+\*(?!\*)', replace_double_bold, text)

    # Шаг 2: Разделяем предложения на новые строки
    # Разделяем по точкам, восклицательным и вопросительным знакам
    # Но сохраняем части с "—" вместе с предыдущим предложением

    # Сначала объединяем весь текст в одну строку для правильного разделения предложений
    # Затем обрабатываем построчно
    lines = text.split('\n')
    all_sentences = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            all_sentences.append('')
            continue

        # Разделяем предложения, но защищаем части с "—" и нумерованные списки
        # Сначала защищаем нумерованные списки от разделения
        # Заменяем паттерны типа "число. текст" на временные маркеры
        numbered_list_pattern = re.compile(r'(\d+\.\s+[^\n.!?]+?)(?=[.!?]|$)')
        numbered_markers = {}
        marker_counter = 0

        def protect_numbered_list(match):
            nonlocal marker_counter
            marker = f"__NUMBERED_{marker_counter}__"
            numbered_markers[marker] = match.group(0)
            marker_counter += 1
            return marker

        # Защищаем нумерованные списки
        protected_line = numbered_list_pattern.sub(protect_numbered_list, line_stripped)

        # Разделяем предложения по знакам препинания (включая многоточие)
        # Сначала нормализуем многоточие
        protected_line = re.sub(r'…', '...', protected_line)
        # Разделяем: многоточие или одиночные знаки препинания, за которыми следует пробел или конец строки
        parts = re.split(r'(\.\.\.|[.!?]+)(?=\s+|$)', protected_line)
        current_sentence = ''

        i = 0
        while i < len(parts):
            part = parts[i]
            if not part:
                i += 1
                continue

            # Если это знак препинания (многоточие или одиночные знаки)
            if part == '...' or re.match(r'^[.!?]+$', part):
                # Проверяем следующую часть
                next_part = parts[i + 1] if i + 1 < len(parts) else ''
                next_part_stripped = next_part.strip() if next_part else ''

                # Если следующая часть начинается с "—", не разделяем
                if next_part_stripped.startswith('—'):
                    # Не разделяем - добавляем знак препинания и часть с "—" к текущему предложению
                    current_sentence += part + next_part
                    i += 2  # Пропускаем следующую часть
                # Если следующая часть начинается с числа и точки (нумерованный список), РАЗДЕЛЯЕМ
                # Это нужно, чтобы "2. Отдельные занятия:" переносилось на новую строку
                elif re.match(r'^\d+\.\s+', next_part_stripped):
                    # Разделяем - завершаем текущее предложение, нумерованный список будет на новой строке
                    current_sentence += part.rstrip()
                    if current_sentence.strip():
                        all_sentences.append(current_sentence.strip())
                        current_sentence = ''
                    # Начинаем новое предложение с нумерованного списка
                    current_sentence = next_part
                    i += 2  # Пропускаем следующую часть
                # Если следующая часть содержит маркер нумерованного списка, разделяем
                elif '__NUMBERED_' in next_part:
                    # Разделяем - завершаем текущее предложение
                    current_sentence += part.rstrip()
                    if current_sentence.strip():
                        all_sentences.append(current_sentence.strip())
                        current_sentence = ''
                    # Начинаем новое предложение с нумерованного списка
                    current_sentence = next_part
                    i += 2  # Пропускаем следующую часть
                else:
                    # Разделяем - завершаем текущее предложение
                    current_sentence += part.rstrip()
                    if current_sentence.strip():
                        all_sentences.append(current_sentence.strip())
                        current_sentence = ''
                    i += 1
            else:
                # Если часть содержит "—", добавляем её к текущему предложению (не разделяем)
                if '—' in part.strip():
                    current_sentence += part
                else:
                    current_sentence += part
                i += 1

        # Добавляем оставшееся предложение
        if current_sentence.strip():
            all_sentences.append(current_sentence.strip())

        # Восстанавливаем нумерованные списки
        restored_sentences = []
        for sentence in all_sentences:
            restored = sentence
            for marker, original in numbered_markers.items():
                restored = restored.replace(marker, original)
            restored_sentences.append(restored)

        all_sentences = restored_sentences
        
        # Фильтруем предложения: должны начинаться с заглавной буквы или цифры
        # (исключаем пустые строки и строки с "—", которые уже обработаны)
        filtered_sentences = []
        for sentence in all_sentences:
            if not sentence.strip():
                filtered_sentences.append(sentence)
                continue
            
            # Проверяем, начинается ли с заглавной буквы или цифры
            first_char = sentence.strip()[0]
            if first_char.isupper() or first_char.isdigit() or '—' in sentence:
                filtered_sentences.append(sentence)
        
        all_sentences = filtered_sentences

    # Объединяем - каждое предложение на отдельной строке
    text = '\n'.join(all_sentences)

    # Шаг 3: Обрабатываем специальные паттерны, которые должны быть на новой строке
    # НО исключаем строки, начинающиеся с "—" (они не должны переноситься)
    # Защищаем строки с "—" от всех обработок регулярными выражениями
    lines = text.split('\n')
    formatted_lines = []

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            formatted_lines.append('')
            continue

        # Если строка содержит "—" (длинный дефис) в любом месте, не обрабатываем её
        # Это защищает от любых переносов строк с "—"
        if '—' in line_stripped:
            formatted_lines.append(line_stripped)
            continue

        # Обрабатываем специальные паттерны только для строк, НЕ содержащих "—"
        # Если строка содержит "—", не применяем к ней никакие регулярные выражения
        # Строки типа "N. текст" (нумерованный список) - ВСЕГДА на новую строку
        if '—' not in line:
            # Нумерованные списки: добавляем перенос перед "число. текст" даже если идет после точки
            # Используем более точный паттерн, который находит нумерованные списки в любом месте строки
            line = re.sub(r'([.!?]\s+)(\d+\.\s+[^\n]+?)(?=\s|$)', r'\1\n\2', line, flags=re.MULTILINE)
            # Также обрабатываем случаи, когда нумерованный список идет в начале строки или после пробела
            line = re.sub(r'(\S)\s+(\d+\.\s+[^\n]+?)(?=\s|$)', r'\1\n\2', line, flags=re.MULTILINE)

            # Строки типа "* текст" (маркированный список без точки в конце)
            line = re.sub(r'([^\n])(\*\s+[^\n]+?)(?<!\.)(?=\s|$)(?!\s*—)', r'\1\n\2', line, flags=re.MULTILINE)

            # Строки типа "👉 текст" (без точки и двоеточия в конце)
            line = re.sub(r'([^\n])(👉\s+[^\n]+?)(?<![:.])(?=\s|$)(?!\s*—)', r'\1\n\2', line, flags=re.MULTILINE)

            # Строки типа "👉 текст:" (с двоеточием в конце)
            line = re.sub(r'([^\n])(👉\s+[^\n]+?:)(?!\s*—)', r'\1\n\2', line, flags=re.MULTILINE)

        # Если после обработки строка разделилась на несколько, добавляем все части
        # Но проверяем каждую часть на наличие "—"
        if '\n' in line:
            for part in line.split('\n'):
                part_stripped = part.strip()
                if part_stripped:
                    # Если часть содержит "—", сохраняем как есть
                    if '—' in part_stripped:
                        formatted_lines.append(part_stripped)
                    else:
                        formatted_lines.append(part_stripped)
        else:
            formatted_lines.append(line_stripped)

    text = '\n'.join(formatted_lines)

    # Шаг 4: Убираем лишние пустые строки (более одной подряд)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Шаг 5: Убираем пробелы в начале строк (кроме строк, содержащих "—")
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if '—' in line.strip():
            # Сохраняем строку с "—" как есть
            cleaned_lines.append(line)
        else:
            cleaned_lines.append(line.lstrip())

    text = '\n'.join(cleaned_lines)

    return text.strip()


def _enhance_layout(text: str) -> str:
    """Нормализует переносы строк для эмодзи и маркеров."""
    if not text:
        return text

    # Защищаем строки, начинающиеся с "—" или содержащие "—" после знака препинания, от обработки
    # Временно заменяем их на маркеры
    protected_lines = {}
    marker_counter = 0

    lines = text.split('\n')
    protected_text_parts = []

    for line in lines:
        line_stripped = line.strip()
        # Защищаем ВСЕ строки, содержащие "—" (длинный дефис) в любом месте
        # Это защищает от любых переносов строк с "—"
        if '—' in line_stripped:
            marker = f"__PROTECTED_DASH_{marker_counter}__"
            protected_lines[marker] = line
            protected_text_parts.append(marker)
            marker_counter += 1
        else:
            protected_text_parts.append(line)

    text = '\n'.join(protected_text_parts)

    # Разделить пункты списков, даже если они были вплотную через маркер или цифры
    # НО не обрабатываем строки с "—" (они уже защищены маркерами)
    # Обрабатываем построчно, пропуская строки с маркерами защищенных строк
    lines = text.split('\n')
    processed_lines = []
    for line in lines:
        # Если строка содержит маркер защищенной строки, не обрабатываем её
        is_protected = any(marker in line for marker in protected_lines.keys())
        if is_protected:
            processed_lines.append(line)
        else:
            # Обрабатываем только строки без маркеров
            processed_line = re.sub(r'(\S)\s*(- |• |\d+[.)])', r'\1\n\2', line)
            processed_line = re.sub(r'(\S)\s*(\d+[.)])', r'\1\n\2', processed_line)
            processed_line = re.sub(r"(\S)\s*👉", r"\1\n👉", processed_line)
            processed_line = re.sub(r"^\s*👉", "👉", processed_line, flags=re.MULTILINE)
            processed_line = re.sub(r"\s*([🧿🔹▶️🔸✓➡️])", r"\n\1", processed_line)
            processed_line = re.sub(r"(\n|^)\s*- ", r"\1- ", processed_line)
            processed_line = re.sub(r"(\n|^)\s*• ", r"\1• ", processed_line)
            processed_lines.append(processed_line)

    text = '\n'.join(processed_lines)

    # Восстанавливаем защищенные строки ПОСЛЕ всех обработок
    for marker, original in protected_lines.items():
        text = text.replace(marker, original)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _highlight_search_terms(text: str, found_words: list[str], found_phrases: list[str]) -> str:
    """
    Выделяет жирным найденные слова и фразы в тексте используя HTML-теги <b>.
    Работает для всех файлов проекта.

    Args:
        text: Текст для выделения
        found_words: Список найденных слов
        found_phrases: Список найденных фраз
    """
    if not text or (not found_words and not found_phrases):
        return text

    result = text

    # Сначала выделяем фразы (в порядке убывания длины, чтобы более длинные фразы обрабатывались первыми)
    sorted_phrases = sorted(found_phrases, key=len, reverse=True)
    for phrase in sorted_phrases:
        if not phrase:
            continue
        # Находим все вхождения фразы (регистронезависимо)
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        result = pattern.sub(lambda m: f"<b>{m.group(0)}</b>", result)

    # Затем выделяем отдельные слова (обычный поиск подстроки)
    for word in found_words:
        if not word or len(word) < 2:
            continue

        # Для всех слов ищем подстроку (без границ слов), чтобы находить части слов
        word_pattern = re.escape(word)
        pattern = re.compile(word_pattern, re.IGNORECASE)

        def replace_word(match):
            matched_text = match.group(0)
            start = match.start()
            # Проверяем, не находится ли слово внутри уже выделенного фрагмента (между <b> и </b>)
            # Считаем количество открывающих и закрывающих тегов до начала совпадения
            before = result[:start]
            # Проверяем, находимся ли мы внутри тега <b>...</b>
            open_tags = before.count('<b>')
            close_tags = before.count('</b>')
            if open_tags > close_tags:
                return matched_text  # Уже внутри выделенного фрагмента, не выделяем
            return f"<b>{matched_text}</b>"

        result = pattern.sub(replace_word, result)

    return result


def _format_primary_source_fragment(
    fragment: dict,
    index: int,
    total: int,
    download_info: dict[str, str] | None,
) -> str:
    header = f"📄 Первоисточник ({index + 1}/{total})"
    section_raw = fragment.get("section") or ""
    section = remove_hash_and_trash(section_raw)
    if _is_generic_section_marker(section):
        section = ""
    body_raw = (fragment.get("text") or "").replace("###", "").strip()
    rule_number = (fragment.get("rule_number") or "").strip().rstrip('.')
    rule_label = (fragment.get("rule_label") or "").strip()
    fragment_source = fragment.get("source") or ""

    pdf_title = ""
    if download_info and download_info.get("label"):
        pdf_title = download_info["label"]
    elif fragment_source:
        pdf_title = PRIMARY_SOURCE_LABELS.get(fragment_source, "")

    header_line = None
    display_body = body_raw

    # Проверяем, содержит ли section полный заголовок раздела (например, "РАЗДЕЛ 5. Оборудование...")
    # Если section уже содержит полный заголовок, не создаем header_line из body
    section_has_full_header = section and re.match(r'РАЗДЕЛ\s+\d+\.', section, re.IGNORECASE)

    # Выделяем заголовок основного пункта отдельно, если нет подпунктов
    # НЕ делаем это, если section уже содержит полный заголовок раздела
    if not section_has_full_header:
        first_line_split = display_body.split('\n', 1)
        first_line = first_line_split[0].strip() if first_line_split else ""
        rest_body = first_line_split[1] if len(first_line_split) > 1 else ""
        header_match = None
        if first_line and rest_body.strip():
            header_match = re.match(r"^(\d+(?:\.\d+)*)(?:\.)?\s+(.*)$", first_line)
        if header_match:
            number_part = header_match.group(1)
            title_part = header_match.group(2).strip()
            # Основной пункт — когда номер без вложенных подпунктов
            if number_part and '.' not in number_part:
                clean_title = title_part.rstrip('.')
                header_line = f"{number_part}. {clean_title}" if clean_title else f"{number_part}."
                display_body = rest_body.lstrip('\n')

    # Добавляем номер правила в начало текста, только если нет header_line
    # И только если section не содержит полный заголовок раздела (для технических требований)
    if rule_number and not header_line and not section_has_full_header:
        rule_prefix = f"{rule_number}."
        if not display_body.lstrip().startswith(rule_prefix):
            display_body = f"{rule_prefix} {display_body.lstrip()}"

    lines: list[str] = [header]

    # Добавляем название раздела всегда, если оно есть
    # (название раздела должно показываться для контекста)
    if section:
        lines.append(section)
        lines.append("")
    if header_line:
        lines.append(header_line)
    if rule_label and rule_label.lower() not in section.lower():
        lines.append(rule_label)
    if display_body:
        display_body = _normalize_primary_body(display_body)
        display_body = _remove_generic_section_lines(display_body)

        # ОБРЕЗАЕМ текст до первого пункта/подпункта, чтобы в окне показывался только один пункт
        # Это соответствует общим правилам формирования окон
        display_body = _truncate_to_single_point(display_body, header_line, rule_number)

        # Выделяем жирным найденные слова и фразы для всех файлов
        found_words = fragment.get('found_words', [])
        found_phrases = fragment.get('found_phrases', [])
        if found_words or found_phrases:
            display_body = _highlight_search_terms(display_body, found_words, found_phrases)

        if not header_line and lines and lines[-1] != "":
            lines.append("")
        lines.append(display_body)
    if pdf_title:
        lines.append("")
        lines.append(pdf_title)

    text = "\n".join(line for line in lines if line is not None)
    return _truncate_primary_source_text(text)


def _get_figures_for_fragment(fragment: dict, main_source: str | None) -> list[str]:
    """Определяет, какие рисунки нужно показать для данного фрагмента первоисточника.
    Проверяет ключевые слова только в релевантном блоке (тексте пункта/подпункта), без учета section.
    """
    figures: list[str] = []
    if not isinstance(fragment, dict):
        return figures

    fragment_source = fragment.get("source") or main_source
    if not fragment_source:
        return figures

    # Проверяем ключевые слова только в тексте релевантного блока (без section)
    fragment_text = (fragment.get("text") or "").lower()
    if not fragment_text:
        return figures

    # Проверяем для Корона
    if fragment_source == CORONA_SOURCE or _normalize_source_name(fragment_source) == _normalize_source_name(CORONA_SOURCE):
        corona_keywords = ("расстанов", "располож", "ряд")
        if any(keyword in fragment_text for keyword in corona_keywords):
            figures.append("Рис.2.1.2.1")

    # Проверяем для Технических требований
    if fragment_source == TECHNICAL_REQUIREMENTS_SOURCE or _normalize_source_name(fragment_source) == _normalize_source_name(TECHNICAL_REQUIREMENTS_SOURCE):
        tech_fig_221_keywords = ("коридор", "радиус", "размер луз", "закруглен", "угол", "ширин", "створ", "средн луз", "углов луз")
        if any(keyword in fragment_text for keyword in tech_fig_221_keywords):
            figures.append("Рис.2.2.1")

        tech_fig_222_keywords = ("валик", "резин", "кромк борт", "наклон")
        if any(keyword in fragment_text for keyword in tech_fig_222_keywords):
            figures.append("Рис.2.2.2")

        tech_fig_223_224_keywords = ("светильник", "свет зон", "освещ", "ламп", "плафон")
        if any(keyword in fragment_text for keyword in tech_fig_223_224_keywords):
            figures.extend(["Рис.2.2.3", "Рис.2.2.4"])

        # Рис.2.2.5: проверяем наличие "игров зон" в тексте (разные формы: игровая зона, игровой зоны и т.д.)
        if re.search(r"игров\w*\s+зон\w*", fragment_text):
            figures.append("Рис.2.2.5")

        tech_fig_226_keywords = ("аксес", "табло", "полк", "стол-полк", "табло-счет")
        if any(keyword in fragment_text for keyword in tech_fig_226_keywords):
            figures.append("Рис.2.2.6")

    return _unique_preserving(figures)


def _build_primary_source_markup(
    current_index: int,
    total: int,
    download_info: dict[str, str] | None,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    if total > 1:
        # Вычисляем индекс для кнопки "Назад" с циклической навигацией
        prev_index = (current_index - 1) % total
        row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"primary_source:goto:{prev_index}"))

    if download_info and download_info.get("url"):
        row.append(InlineKeyboardButton(text="📥 Скачать", url=download_info["url"]))

    if total > 1:
        # Вычисляем индекс для кнопки "Вперед" с циклической навигацией
        next_index = (current_index + 1) % total
        row.append(InlineKeyboardButton(text="▶️ Вперёд", callback_data=f"primary_source:goto:{next_index}"))

    row.append(InlineKeyboardButton(text="✖️ Закрыть", callback_data="primary_source:close"))
    buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Глобальная переменная для хранения file_id анимированного стикера с глазами
# Будет автоматически обновляться, когда пользователь отправит стикер боту
WAITING_STICKER_FILE_ID: str | None = None


async def _send_waiting_sticker(message: Message) -> Message | None:
    """
    Отправляет анимированный эмодзи-стикер ожидания (маленькие глаза).
    Использует file_id анимированного эмодзи-стикера с глазами.
    Если file_id не установлен, пробует использовать известные file_id из стандартных наборов.
    """
    global WAITING_STICKER_FILE_ID
    logger = logging.getLogger(__name__)

    # Сначала пробуем использовать сохраненный file_id
    if WAITING_STICKER_FILE_ID:
        try:
            sticker_message = await message.answer_sticker(WAITING_STICKER_FILE_ID)
            logger.debug("Анимированный эмодзи-стикер отправлен успешно (из сохраненного file_id)")
            return sticker_message
        except Exception as e:
            logger.warning(f"Не удалось отправить стикер по сохраненному file_id: {e}")

    # Популярные анимированные эмодзи-стикеры с глазами из стандартных наборов Telegram
    # Это стикеры из набора "Animated Emoji" - пробуем несколько вариантов
    # File ID может отличаться в зависимости от бота, но некоторые могут работать
    POPULAR_ANIMATED_EYES_STICKERS = [
        # Популярные file_id для анимированного эмодзи с глазами (👀)
        # Эти file_id могут работать для стандартных наборов Telegram
        "CAACAgIAAxkBAAIBY2ZgZQABAX9kZWQAAUfQZWRkZGQAAQACAgADwDxPAAH4ZWRkZGQAAQACAgADwDxP",
        "CAACAgIAAxkBAAIBZGZgZQABAYBkZWQAAUfQZWRkZGQAAQACAgADwDxPAAH4ZWRkZGQAAQACAgADwDxP",
        "CAACAgIAAxkBAAIBZmZgZQABAYFkZWQAAUfQZWRkZGQAAQACAgADwDxPAAH4ZWRkZGQAAQACAgADwDxP",
    ]

    # Пробуем отправить стикер по известным file_id
    for sticker_id in POPULAR_ANIMATED_EYES_STICKERS:
        try:
            sticker_message = await message.answer_sticker(sticker_id)
            logger.debug(f"Анимированный эмодзи-стикер отправлен успешно (из стандартного набора)")
            # Сохраняем рабочий file_id для будущего использования
            WAITING_STICKER_FILE_ID = sticker_id
            return sticker_message
        except Exception:
            continue

    # Если ни один стикер не работает, используем эмодзи как fallback
    # В этом случае пользователь увидит текстовый эмодзи "👀"
    logger.warning("Не удалось отправить анимированный стикер, используем эмодзи как fallback")
    try:
        sticker_message = await message.answer("👀")
        return sticker_message
    except Exception:
        return None


@router.message(F.sticker)
async def handle_sticker_for_waiting(message: Message) -> None:
    """
    Обработчик для получения file_id анимированного стикера с глазами.
    Когда пользователь отправляет стикер боту, сохраняем его file_id для использования в качестве стикера ожидания.
    """
    global WAITING_STICKER_FILE_ID

    if message.sticker:
        sticker = message.sticker
        # Проверяем, что это анимированный стикер (эмодзи-стикер обычно анимированный)
        if sticker.is_animated or sticker.is_video:
            WAITING_STICKER_FILE_ID = sticker.file_id
            logger = logging.getLogger(__name__)
            logger.info(f"File_id анимированного стикера сохранен: {WAITING_STICKER_FILE_ID[:30]}...")
            await message.answer(
                f"✅ <b>Стикер сохранен!</b>\n\n"
                f"File ID: <code>{WAITING_STICKER_FILE_ID}</code>\n\n"
                f"Теперь этот стикер будет использоваться как индикатор ожидания.",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer("⚠️ Пожалуйста, отправьте <b>анимированный</b> стикер с глазами.", parse_mode=ParseMode.HTML)


async def _delete_waiting_sticker(waiting_sticker_message: Message | None) -> None:
    """Удаляет стикер ожидания, если он существует."""
    if waiting_sticker_message:
        try:
            await waiting_sticker_message.delete()
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Не удалось удалить стикер ожидания: {e}")


async def _show_intent_selection_window(
    message: Message,
    state: FSMContext,
    waiting_sticker_message: Message | None = None,
) -> None:
    """Показать окно выбора намерения (Обучение/Консультация/Продолжить)"""
    logger = logging.getLogger(__name__)

    try:
        if not message:
            logger.error("_show_intent_selection_window: message is None")
            return

        if not message.from_user:
            logger.error("_show_intent_selection_window: message.from_user is None")
            return

        text = (
            "⏸️ <b>Пожалуйста, уточните, что Вы хотите:</b>\n"
            "👉 - Записаться на Обучение\n"
            "👉 - Записаться на Консультацию по телефону\n"
            "👉 - Продолжить общение в чате"
        )

        buttons = [
            InlineKeyboardButton(text="🟢 Обучение", callback_data="intent:training"),
            InlineKeyboardButton(text="🟣 Консультация", callback_data="intent:consultation"),
            InlineKeyboardButton(text="▶️ Продолжить", callback_data="intent:continue"),
        ]

        markup = InlineKeyboardMarkup(inline_keyboard=[buttons])

        # Удаляем стикер ожидания перед показом окна
        await _delete_waiting_sticker(waiting_sticker_message)

        await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        # Сохраняем исходный запрос пользователя для обработки при нажатии "Продолжить"
        original_query = message.text or ""

        # ОБНУЛЯЕМ все поля профиля (кроме name_sys) при показе окна намерения
        profile = await get_user_profile(message.from_user.id)
        old_status = (profile.status or "").strip() if profile else ""
        await reset_user_profile_fields(message.from_user.id)
        await state.update_data(
            intent_selection_shown=True,
            original_query_for_continue=original_query,
            old_status_before_intent=old_status  # Сохраняем старый статус для проверки изменения
        )

        await save_chat_message(message.from_user.id, "assistant", text)

        logger.info(f"Показано окно выбора намерения для пользователя {message.from_user.id}, поля профиля обнулены")
    except Exception as e:
        logger.error(f"Ошибка в _show_intent_selection_window: {e}", exc_info=True)
        # Удаляем стикер ожидания при ошибке
        await _delete_waiting_sticker(waiting_sticker_message)
        # Пробрасываем исключение дальше, чтобы оно было обработано в вызывающем коде
        raise


async def _show_phase4_booking_window(
    message: Message,
    state: FSMContext,
    waiting_sticker_message: Message | None = None,
) -> None:
    """Показать окно записи Фазы 4 с кнопками"""
    logger = logging.getLogger(__name__)

    try:
        if not message:
            logger.error("_show_phase4_booking_window: message is None")
            return

        if not message.from_user:
            logger.error("_show_phase4_booking_window: message.from_user is None")
            return

        text = (
            "===📝З А П И С Ь===\n"
            "Предлагаю следующие варианты:\n"
            "👉 Запишитесь САМОСТОЯТЕЛЬНО, позвонив по телефону школы 📱 +7 983 205 2230.\n"
            "👉 Оставьте свои контакты - ИМЯ и ТЕЛЕФОН, тогда я сделаю запись за Вас 😎.\n"
            "<b>Что выбираете?</b>"
        )

        buttons = [
            InlineKeyboardButton(text="📞 САМ", callback_data="phase4:self"),
            InlineKeyboardButton(text="👨‍🎓 КОНТАКТЫ", callback_data="phase4:contacts"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="phase4:cancel"),
        ]

        markup = InlineKeyboardMarkup(inline_keyboard=[buttons])

        # Удаляем стикер ожидания перед показом окна
        await _delete_waiting_sticker(waiting_sticker_message)

        await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await state.update_data(phase4_window_shown=True)

        await save_chat_message(message.from_user.id, "assistant", text)

        logger.info(f"Показано окно записи Фазы 4 для пользователя {message.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка в _show_phase4_booking_window: {e}", exc_info=True)
        # Удаляем стикер ожидания при ошибке
        await _delete_waiting_sticker(waiting_sticker_message)
        raise


async def _answer_with_sticker_cleanup(
    message: Message,
    text: str,
    waiting_sticker_message: Message | None = None,
    **kwargs
) -> Message | None:
    """Отправляет сообщение и удаляет стикер ожидания. Возвращает отправленное сообщение."""
    sent_message = await message.answer(text, **kwargs)
    await _delete_waiting_sticker(waiting_sticker_message)
    return sent_message


async def _process_faq_query(
    message: Message,
    state: FSMContext,
    user_q: str,
    *,
    input_mode: str = "text",
    waiting_sticker_message: Message | None = None,
) -> None:
    logger = logging.getLogger(__name__)

    user_id = message.from_user.id if message.from_user else 0

    # Получаем системное имя пользователя
    name_sys = "друг"
    if message.from_user:
        if message.from_user.first_name:
            name_sys = message.from_user.first_name
        elif message.from_user.username:
            name_sys = message.from_user.username

    # Получаем или создаем профиль пользователя
    profile = await get_or_create_user_profile(user_id, name_sys)

    # Получаем текущую фазу из state
    state_data = await state.get_data()
    current_phase = state_data.get("phase", 1)
    continue_button_pressed = state_data.get("continue_button_pressed", False)

    user_q = (user_q or "").strip()
    if not user_q:
        await _answer_with_sticker_cleanup(message, "Задайте вопрос о школе или русском бильярде и я помогу.", waiting_sticker_message)
        return

    # Обработка приветствий без обращения к Базе знаний
    normalized = re.sub(r"[\s!.,?;:()\-]+", " ", user_q.lower()).strip()
    greeting_words = {
        "привет", "здравствуйте", "добрый день", "доброе утро", "добрый вечер",
        "приветствую", "здравствуй", "йо", "хай", "здарова"
    }
    if any(normalized == gw or normalized.startswith(gw) for gw in greeting_words):
        await _answer_with_sticker_cleanup(message, "Здравствуйте, я весь - внимание!", waiting_sticker_message)
        return

    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: Если окно Политика активно, показываем его снова
    # Пользователь ДОЛЖЕН выбрать одну из двух кнопок (ДА или НЕТ), иначе окно будет показываться снова
    if state_data.get("policy_shown") and current_phase == 2:
        logger.info(f"Окно Политика активно - показываем его снова для запроса: '{user_q[:50]}'")
        if not message:
            logger.error("message is None при попытке показать окно Политика")
            await _delete_waiting_sticker(waiting_sticker_message)
            return
        try:
            # Получаем user_intent из state для показа окна политики
            user_intent = state_data.get("user_intent", "Обучение")
            await show_policy_window(message, state, user_intent, waiting_sticker_message)
            return  # Выходим, не производя поиск и отправку в LLM
        except Exception as e:
            logger.error(f"Ошибка при показе окна Политика: {e}", exc_info=True)
            # Удаляем стикер ожидания при ошибке
            await _delete_waiting_sticker(waiting_sticker_message)
            # Показываем сообщение об ошибке
            if message:
                try:
                    await message.answer("⚠️ Произошла ошибка при обработке запроса. Попробуйте еще раз.")
                except Exception as msg_error:
                    logger.error(f"Не удалось отправить сообщение об ошибке: {msg_error}")
            return

    # Проверка: если мы в Фазе 2 (Политика), не производим поиск и общение с LLM
    if current_phase == 2:
        logger.info(f"Пользователь {user_id} в Фазе 2 (Политика) - поиск и LLM отключены")
        return

    # Обработка Фазы 3: Отслеживание ответов на вопросы анкеты (ДО блокировки поиска)
    if current_phase == 3 and state_data.get("anketa_started"):
        anketa_question = state_data.get("anketa_question", 1)
        anketa_retry_count = state_data.get("anketa_retry_count", 0)
        invalid_messages = state_data.get("anketa_invalid_messages", [])  # Список ID нерелевантных сообщений

        # Валидация ответа
        is_valid, validation_reason = _validate_anketa_answer(user_q, anketa_question)

        if not is_valid:
            # Если ответ не релевантен, сохраняем ID текущего сообщения для последующего удаления
            if message and message.message_id:
                invalid_messages.append(message.message_id)
                await state.update_data(anketa_invalid_messages=invalid_messages)

            # Увеличиваем счетчик попыток
            anketa_retry_count += 1
            await state.update_data(anketa_retry_count=anketa_retry_count)

            # Если попыток больше 2, возвращаемся к Фазе 1
            if anketa_retry_count > 2:
                logger.warning(f"Пользователь {user_id} не смог ответить на вопрос {anketa_question} после {anketa_retry_count} попыток")
                # Удаляем все нерелевантные сообщения (включая ответы бота) перед выходом
                if invalid_messages and message and message.chat:
                    for msg_id in invalid_messages:
                        try:
                            await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
                            logger.info(f"Удалено нерелевантное сообщение {msg_id} для пользователя {user_id}")
                        except Exception as e:
                            logger.warning(f"Не удалось удалить сообщение {msg_id}: {e}")
                await state.update_data(
                    phase=1,
                    anketa_started=False,
                    anketa_question=None,
                    anketa_retry_count=0,
                    anketa_invalid_messages=[]
                )
                await _answer_with_sticker_cleanup(
                    message,
                    "😕Жаль, что Вы не ответили на все вопросы!\n▶️ Я снова готов к Вашим вопросам.",
                    waiting_sticker_message
                )
                await save_chat_message(user_id, "assistant", "😕Жаль, что Вы не ответили на все вопросы!\n▶️ Я снова готов к Вашим вопросам.")
                return

            # Задаем вопрос повторно с сообщением "💤 Простите?"
            question_texts = {
                1: "<b>1. Какой у Вас ОПЫТ игры на бильярде?</b>\n(Например: играю 2 года, новичок, не играл, умею играть, играл в детстве и т.д.)",
                2: "<b>2. Какой УРОВЕНЬ подготовки, по Вашему мнению?</b>\n(Например: новичок, начинающий, средний, продвинутый, любитель, профессионал и т.д.)",
                3: "<b>3. Каковы Ваши ЦЕЛИ в обучении?</b>\n(Например: научиться играть, улучшить технику, подготовиться к турниру, освоить правила и т.д.)",
                4: "<b>4. Учились ли Вы РАНЕЕ в ШБ «Абриколь»?</b>\n(Да или Нет)"
            }

            retry_message = f"💤 Простите?\n\n{question_texts.get(anketa_question, '')}"
            sent_message = await _answer_with_sticker_cleanup(
                message,
                retry_message,
                waiting_sticker_message,
                parse_mode=ParseMode.HTML
            )
            # Сохраняем ID ответа бота для последующего удаления
            if sent_message and sent_message.message_id:
                invalid_messages.append(sent_message.message_id)
                await state.update_data(anketa_invalid_messages=invalid_messages)
            await save_chat_message(user_id, "assistant", retry_message)
            logger.info(f"Ответ пользователя {user_id} на вопрос {anketa_question} не релевантен: {validation_reason}. Попытка {anketa_retry_count}")
            return

        # Если ответ валиден, удаляем все нерелевантные сообщения (включая ответы бота)
        if invalid_messages and message and message.chat:
            for msg_id in invalid_messages:
                try:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
                    logger.info(f"Удалено нерелевантное сообщение {msg_id} для пользователя {user_id}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить сообщение {msg_id}: {e}")
            await state.update_data(anketa_invalid_messages=[])

        # Сбрасываем счетчик попыток и сохраняем ответ
        await state.update_data(anketa_retry_count=0)

        # Определяем, на какой вопрос отвечает пользователь
        # Вопрос 1: Опыт
        if anketa_question == 1:
            await update_user_profile(user_id, exp=user_q)
            await state.update_data(anketa_question=2)
            logger.info(f"Сохранен ответ на вопрос 1 (Опыт): {user_q[:50]}")
            # Задаем следующий вопрос
            next_question = (
                "<b>2. Какой УРОВЕНЬ подготовки, по Вашему мнению?</b>\n"
                "(Например: новичок, начинающий, средний, продвинутый, любитель, профессионал и т.д.)"
            )
            await _answer_with_sticker_cleanup(
                message,
                next_question,
                waiting_sticker_message,
                parse_mode=ParseMode.HTML
            )
            await save_chat_message(user_id, "assistant", next_question)
            return  # Выходим, не производя поиск и LLM

        # Вопрос 2: Уровень
        elif anketa_question == 2:
            await update_user_profile(user_id, level=user_q)
            await state.update_data(anketa_question=3)
            logger.info(f"Сохранен ответ на вопрос 2 (Уровень): {user_q[:50]}")
            # Задаем следующий вопрос
            next_question = (
                "<b>3. Каковы Ваши ЦЕЛИ в обучении?</b>\n"
                "(Например: научиться играть, улучшить технику, подготовиться к турниру, освоить правила и т.д.)"
            )
            await _answer_with_sticker_cleanup(
                message,
                next_question,
                waiting_sticker_message,
                parse_mode=ParseMode.HTML
            )
            await save_chat_message(user_id, "assistant", next_question)
            return  # Выходим, не производя поиск и LLM

        # Вопрос 3: Цели
        elif anketa_question == 3:
            await update_user_profile(user_id, goals=user_q)
            await state.update_data(anketa_question=4)
            logger.info(f"Сохранен ответ на вопрос 3 (Цели): {user_q[:50]}")
            # Задаем следующий вопрос
            next_question = (
                "<b>4. Учились ли Вы РАНЕЕ в ШБ «Абриколь»?</b>\n"
                "(Да или Нет)"
            )
            await _answer_with_sticker_cleanup(
                message,
                next_question,
                waiting_sticker_message,
                parse_mode=ParseMode.HTML
            )
            await save_chat_message(user_id, "assistant", next_question)
            return  # Выходим, не производя поиск и LLM

        # Вопрос 4: Обучение ранее (Да/Нет)
        elif anketa_question == 4:
            before_value = "Да" if any(word in user_q.lower() for word in ["да", "yes", "учил", "обучал", "училась", "обучалась", "был", "была"]) else "Нет"
            await update_user_profile(user_id, before=before_value)
            await state.update_data(anketa_question=5, anketa_completed=True)
            logger.info(f"Сохранен ответ на вопрос 4 (Обучение ранее): {before_value}")

            # Выводим сводку после всех 4 ответов
            profile = await get_user_profile(user_id)
            if profile:
                summary = f"""🌈 Отлично! Вот Ваши ответы:

1. Опыт: <b>{profile.exp or '—'}</b>

2. Уровень: <b>{profile.level or '—'}</b>

3. Цель: <b>{profile.goals or '—'}</b>

4. Обучение ранее: <b>{profile.before or '—'}</b>

😎 <b>Вы большой молодец, анкетирование окончено!</b>
Ваши ответы сохранены, что поможет нам подобрать для Вас ОПТИМАЛЬНУЮ программу обучения 🔥."""

                # Если Before=Нет, добавляем информацию о приветственном бонусе
                if profile.before and profile.before.strip().lower() == "нет":
                    summary += "\n\nКроме того, Вам, как новому ученику, полагается приветственный бонус 🎁 - полностью БЕСПЛАТНЫЙ первый урок 1,5 часа."

                await _answer_with_sticker_cleanup(
                    message,
                    summary,
                    waiting_sticker_message,
                    parse_mode=ParseMode.HTML
                )
                await save_chat_message(user_id, "assistant", summary)

            # После всех 4 ответов переходим к Фазе 4
            await state.update_data(phase=4, phase4_check_contacts=False, phase4_window_shown=False)
            logger.info(f"Переход к Фазе 4 (Запись) для пользователя {user_id}")

            # Сохранение в Excel будет происходить только при выборе "Сам" (если статус изменился) или "Контакт" (после ввода телефона)

            # Показываем окно записи с кнопками
            await _show_phase4_booking_window(message, state, waiting_sticker_message)
            return  # Выходим, не производя поиск и LLM

    # Проверка: если мы в Фазе 3 (Анкетирование), но anketa_started=False, не производим поиск и общение с LLM
    if current_phase == 3:
        logger.info(f"Пользователь {user_id} в Фазе 3 (Анкетирование) - поиск и LLM отключены")
        await _delete_waiting_sticker(waiting_sticker_message)
        return

    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: Если окно Фазы 4 активно, показываем его снова
    # Пользователь ДОЛЖЕН выбрать одну из трех кнопок, иначе окно будет показываться снова
    if state_data.get("phase4_window_shown") and current_phase == 4:
        logger.info(f"Окно Фазы 4 активно - показываем его снова для запроса: '{user_q[:50]}'")
        if not message:
            logger.error("message is None при попытке показать окно Фазы 4")
            await _delete_waiting_sticker(waiting_sticker_message)
            return
        try:
            await _show_phase4_booking_window(message, state, waiting_sticker_message)
            return  # Выходим, не производя поиск и LLM
        except Exception as e:
            logger.error(f"Ошибка при показе окна Фазы 4: {e}", exc_info=True)
            await _delete_waiting_sticker(waiting_sticker_message)
            if message:
                try:
                    await message.answer("⚠️ Произошла ошибка при обработке запроса. Попробуйте еще раз.")
                except Exception as msg_error:
                    logger.error(f"Не удалось отправить сообщение об ошибке: {msg_error}")
            return

    # Обработка Фазы 4: Запись (имя и телефон) - только если окно не показано (пользователь вводит данные)
    if current_phase == 4 and not state_data.get("phase4_window_shown"):
        phase4_state = state_data.get("phase4_state", None)  # "waiting_name", "waiting_phone", None

        if phase4_state == "waiting_name":
            # Получаем имя (без валидации)
            name = user_q.strip()
            if name:
                await update_user_profile(user_id, name=name)
                logger.info(f"Получено имя: {name}")
                # Переходим к запросу телефона - очищаем список нерелевантных сообщений
                await state.update_data(phase4_state="waiting_phone", phase4_invalid_messages=[])
                phone_message = "<b>Ваш Номер телефона?</b>\n(в формате +7(8)...)"
                await _answer_with_sticker_cleanup(
                    message,
                    phone_message,
                    waiting_sticker_message,
                    parse_mode=ParseMode.HTML
                )
                await save_chat_message(user_id, "assistant", phone_message)
                return

        elif phase4_state == "waiting_phone":
            # Получаем список ID нерелевантных сообщений
            invalid_messages = state_data.get("phase4_invalid_messages", [])

            # Проверяем формат телефона: 8 ХХХ ХХХ ХХХХ или +7 ХХХ ХХХ ХХХХ
            phone_pattern = r"^(\+?7|8)[\s\-\(]?(\d{3})[\s\-\)]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})$"
            match = re.match(phone_pattern, user_q.strip())

            if match:
                # Телефон валиден - нормализуем формат
                phone = re.sub(r"[\s\-\(\)]", "", user_q.strip())
                if phone.startswith("8"):
                    phone = "+7" + phone[1:]
                elif not phone.startswith("+7"):
                    phone = "+7" + phone

                await update_user_profile(user_id, phone=phone)
                logger.info(f"Получен телефон: {phone}")

                # Отправляем стикер ожидания после получения телефона
                phone_waiting_sticker = await _send_waiting_sticker(message)

                # Удаляем все нерелевантные сообщения (включая ответы бота) перед завершением
                if invalid_messages and message and message.chat:
                    for msg_id in invalid_messages:
                        try:
                            await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
                            logger.info(f"Удалено нерелевантное сообщение {msg_id} для пользователя {user_id}")
                        except Exception as e:
                            logger.warning(f"Не удалось удалить сообщение {msg_id}: {e}")

                # Сохраняем в Excel после записи Name и Phone
                profile = await get_user_profile(user_id)
                if profile and (profile.status or "").strip() in ("Обучение", "Консультация"):
                    try:
                        from ..db.leads_excel import save_lead_to_excel
                        logger.info(f"🔄 Сохранение в Excel для пользователя {user_id} (Контакт, Name и Phone записаны)")
                        await save_lead_to_excel(profile, profile.name_sys or "")
                        logger.info(f"✅ Данные лида сохранены в Excel: статус='{profile.status}'")
                    except Exception as e:
                        logger.error(f"❌ Ошибка при сохранении в Excel: {e}", exc_info=True)

                # Завершаем запись
                await state.update_data(
                    phase=1,
                    phase4_state=None,
                    phase4_window_shown=False,
                    phase4_invalid_messages=[]
                )
                completion_message = (
                    "🤝Рад знакомству.\n"
                    "Все Ваши данные сохранены, ЗАПИСЬ ЗАВЕРШЕНА!\n"
                    "<b>Ждите нашего звонка</b> ☎️\n▶️ ... а я - снова готов к Вашим вопросам."
                )
                await _answer_with_sticker_cleanup(
                    message,
                    completion_message,
                    phone_waiting_sticker,  # Используем стикер, отправленный после получения телефона
                    parse_mode=ParseMode.HTML
                )
                await save_chat_message(user_id, "assistant", completion_message)
                logger.info(f"Запись завершена для пользователя {user_id}")
                return
            else:
                # Телефон не валиден - сохраняем ID текущего сообщения и ответа для последующего удаления
                if message and message.message_id:
                    invalid_messages.append(message.message_id)
                    await state.update_data(phase4_invalid_messages=invalid_messages)

                # Отправляем сообщение об ошибке
                retry_message = "💤 Неправильный формат телефона!\n<b>Ваш Номер телефона?</b>\n(в формате +7(8)...)"
                sent_message = await _answer_with_sticker_cleanup(
                    message,
                    retry_message,
                    waiting_sticker_message,
                    parse_mode=ParseMode.HTML
                )
                # Сохраняем ID ответа бота для последующего удаления
                if sent_message and sent_message.message_id:
                    invalid_messages.append(sent_message.message_id)
                    await state.update_data(phase4_invalid_messages=invalid_messages)

                await save_chat_message(user_id, "assistant", retry_message)
                return

        # Если не в состоянии ожидания имени/телефона, блокируем поиск и LLM
        logger.info(f"Пользователь {user_id} в Фазе 4 (Запись) - поиск и LLM отключены")
        await _delete_waiting_sticker(waiting_sticker_message)
        return

    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: Если окно выбора намерения активно, показываем его снова
    # Пользователь ДОЛЖЕН выбрать одну из трех кнопок, иначе окно будет показываться снова
    if state_data.get("intent_selection_shown") and current_phase == 1:
        logger.info(f"Окно выбора намерения активно - показываем его снова для запроса: '{user_q[:50]}'")
        if not message:
            logger.error("message is None при попытке показать окно выбора намерения")
            await _delete_waiting_sticker(waiting_sticker_message)
            return
        try:
            await _show_intent_selection_window(message, state, waiting_sticker_message)
            return  # Выходим, не производя поиск и отправку в LLM
        except Exception as e:
            logger.error(f"Ошибка при показе окна выбора намерения: {e}", exc_info=True)
            # Удаляем стикер ожидания при ошибке
            await _delete_waiting_sticker(waiting_sticker_message)
            # Показываем сообщение об ошибке
            if message:
                try:
                    await message.answer("⚠️ Произошла ошибка при обработке запроса. Попробуйте еще раз.")
                except Exception as msg_error:
                    logger.error(f"Не удалось отправить сообщение об ошибке: {msg_error}")
            return

    # Если была нажата кнопка "Продолжить", пропускаем проверку на ключевые слова
    # чтобы избежать повторного показа окна выбора
    if continue_button_pressed:
        logger.info(f"Кнопка 'Продолжить' была нажата - пропускаем проверку на ключевые слова для запроса '{user_q}'")
        # Сбрасываем флаг после использования
        await state.update_data(continue_button_pressed=False)
    else:
        # Проверяем ключевые слова для перехода к Фазе 2 (ДО поиска и LLM)
        user_q_lower = user_q.lower()
        intent_keywords = [
            "консультац", "запис", "позвон", "перезвон",
            "связаться", "хочу", "желаю", "начать", "тренинг", "решил", "решен"
        ]
        has_intent_keywords = any(kw in user_q_lower for kw in intent_keywords)

        # Проверяем, была ли нажата кнопка "Записаться"
        is_booking_button = user_q.strip() == "📝 Записаться" or user_q.strip() == "Записаться"

        logger.info(f"Проверка намерений: user_q='{user_q}', has_intent_keywords={has_intent_keywords}, is_booking_button={is_booking_button}, current_phase={current_phase}, intent_selection_shown={state_data.get('intent_selection_shown')}")

        # Если обнаружены ключевые слова или кнопка "Записаться" в Фазе 1 - показываем окно выбора БЕЗ поиска и LLM
        if (has_intent_keywords or is_booking_button) and current_phase == 1 and not state_data.get("intent_selection_shown"):
            logger.info(f"Обнаружены ключевые слова для перехода к Фазе 2 - показываем окно выбора без поиска и LLM")
            if not message:
                logger.error("message is None при попытке показать окно выбора намерения")
                await _delete_waiting_sticker(waiting_sticker_message)
                return
            try:
                await _show_intent_selection_window(message, state, waiting_sticker_message)
                return  # Выходим, не производя поиск и отправку в LLM
            except Exception as e:
                logger.error(f"Ошибка при показе окна выбора намерения: {e}", exc_info=True)
                # Удаляем стикер ожидания при ошибке
                await _delete_waiting_sticker(waiting_sticker_message)
                # Показываем сообщение об ошибке
                if message:
                    try:
                        await message.answer("⚠️ Произошла ошибка при обработке запроса. Попробуйте еще раз.")
                    except Exception as msg_error:
                        logger.error(f"Не удалось отправить сообщение об ошибке: {msg_error}")
                return

    logger.info(f"Обработка вопроса ({input_mode}) от пользователя {user_id}: {user_q[:50]}, фаза: {current_phase}")

    try:
        stored_user_q = user_q if input_mode == "text" else f"[voice] {user_q}"
        await save_chat_message(user_id, "user", stored_user_q)
    except Exception as save_user_error:
        logger.warning(f"Не удалось сохранить сообщение пользователя: {save_user_error}")

    # Явная классификация темы запроса перед поиском
    detected_topic, topic_confidence = classify_topic(user_q)
    logger.info(f"Классификация темы для запроса '{user_q[:50]}': тема={detected_topic}, уверенность={topic_confidence:.2f}")

    purchase_keywords = ["куп", "покуп", "оплат", "стоим", "цена", "плат"]
    purchase_inquiry = any(kw in user_q.lower() for kw in purchase_keywords)

    # Получаем историю чата (последние 10 сообщений для контекста)
    try:
        chat_history = await get_chat_history(user_id, limit=10)
    except Exception as history_error:
        logger.warning(f"Не удалось получить историю чата: {history_error}")
        chat_history = []

    try:
        hits = search_store.search(user_q, top_k=5)
        logger.info(f"Поиск по запросу '{user_q}': найдено {len(hits)} результатов")

        # Анализируем источники найденных результатов для проверки классификации
        if hits:
            school_sources = sum(1 for h in hits if h.source and h.source.startswith("1."))
            rules_sources = sum(1 for h in hits if h.source and h.source.startswith("2."))
            logger.info(f"Распределение источников до фильтрации: Тема 1 (школа)={school_sources}, Тема 2 (правила)={rules_sources}, всего={len(hits)}")

        # Фильтрация результатов на основе классификации темы
        if hits and detected_topic != "unknown" and topic_confidence >= 0.4:
            filtered_hits = []
            for h in hits:
                if not h.source:
                    # Если источник не указан, оставляем результат
                    filtered_hits.append(h)
                    continue

                source = h.source
                # Если тема определена как "school" - приоритизируем файлы 1.x_
                if detected_topic == "school":
                    if source.startswith("1."):
                        filtered_hits.append(h)
                    # Если уверенность высокая, исключаем файлы 2.x_
                    elif topic_confidence < 0.7:
                        # При средней уверенности оставляем, но с пониженным приоритетом
                        filtered_hits.append(h)

                # Если тема определена как "rules" - приоритизируем файлы 2.x_
                elif detected_topic == "rules":
                    if source.startswith("2."):
                        filtered_hits.append(h)
                    # Если уверенность высокая, исключаем файлы 1.x_
                    elif topic_confidence < 0.7:
                        # При средней уверенности оставляем, но с пониженным приоритетом
                        filtered_hits.append(h)

            # Если после фильтрации остались результаты - используем их
            if filtered_hits:
                # Приоритизируем: сначала результаты из нужной темы, потом остальные
                prioritized_hits = []
                other_hits = []

                for h in filtered_hits:
                    if not h.source:
                        other_hits.append(h)
                        continue

                    if detected_topic == "school" and h.source.startswith("1."):
                        prioritized_hits.append(h)
                    elif detected_topic == "rules" and h.source.startswith("2."):
                        prioritized_hits.append(h)
                    else:
                        other_hits.append(h)

                # Объединяем: сначала приоритетные, потом остальные
                hits = prioritized_hits + other_hits

                # Ограничиваем количество результатов
                hits = hits[:5]

                logger.info(f"После фильтрации по теме '{detected_topic}': осталось {len(hits)} результатов")
                if hits:
                    school_after = sum(1 for h in hits if h.source and h.source.startswith("1."))
                    rules_after = sum(1 for h in hits if h.source and h.source.startswith("2."))
                    logger.info(f"Распределение источников после фильтрации: Тема 1 (школа)={school_after}, Тема 2 (правила)={rules_after}")
            else:
                # Если все результаты отфильтровались, используем исходные (на случай ошибки классификации)
                logger.warning(f"Все результаты отфильтровались для темы '{detected_topic}', используем исходные результаты")

    except Exception as search_error:
        logger.error(f"Ошибка при поиске: {search_error}", exc_info=True)
        await _answer_with_sticker_cleanup(message, "⚠️ Однако, произошел системный сбой. Повторите Ваш запрос/ответ.", waiting_sticker_message)
        return

    # Реранжирование результатов для общих запросов про программы/виды обучения
    try:
        norm_for_rerank = re.sub(r"\s+", " ", user_q.lower()).strip()
        general_training_phrases = [
            "виды обуч", "программы обуч", "формы обуч", "типы обуч", "варианты обуч",
            "учебные программ", "учебные программы",
            "предложения по обуч", "предложения по обучению",
            "образовательные продукт", "образовательные продукты",
        ]
        is_general_programs = any(p in norm_for_rerank for p in general_training_phrases)
        if is_general_programs and hits:
            def _bonus(h):
                src = (h.source or "")
                if src.startswith("1.2_"):
                    return 1.0
                if src.startswith("1.4_"):
                    return -0.6
                return 0.0
            hits = sorted(hits, key=lambda h: (h.score + _bonus(h)), reverse=True)
            # Жесткая фильтрация 1.4_ если есть хотя бы один 1.2_
            has_12 = any((h.source or "").startswith("1.2_") for h in hits)
            if has_12:
                hits = [h for h in hits if not (h.source or "").startswith("1.4_")]
    except Exception:
        pass

    # Приоритизация документа 1.2 для точного запроса "начальный курс"
    try:
        user_q_lower = user_q.lower().strip()
        if "начальный курс" in user_q_lower and hits:
            # Приоритизируем документ 1.2_Виды обучения
            def _initial_course_priority(h):
                if h.source and "1.2_Виды обучения" in h.source:
                    return 2.0  # Большой бонус для документа 1.2
                return 0.0

            hits = sorted(hits, key=lambda h: (h.score + _initial_course_priority(h)), reverse=True)
            logger.info(f"Приоритизирован документ 1.2_Виды обучения для запроса 'начальный курс'")
    except Exception:
        pass

    # Проверяем, есть ли среди документов, отправляемых в LLM, документы из раздела "О школе" (1.1, 1.2, 1.3, 1.4)
    # Это нужно сделать ДО формирования контекстов, чтобы правильно заблокировать поиск первоисточников
    # ВАЖНО: проверяем начало строки (startswith), а не просто наличие подстроки, чтобы не перепутать 2.1.1_ с 1.1_
    has_school_sources_in_llm = False
    school_sources_in_hits = []
    if hits:
        school_source_prefixes = ("1.1_", "1.2_", "1.3_", "1.4_")
        # Проверяем только первые 3 результата, которые реально отправляются в LLM
        hits_for_llm = hits[:3]
        school_sources_in_hits = [h.source for h in hits_for_llm if h.source and any(h.source.startswith(prefix) for prefix in school_source_prefixes)]

        # Если в топ-3 есть документы из раздела "О школе", всегда блокируем поиск первоисточников
        if school_sources_in_hits:
            has_school_sources_in_llm = True
            logger.info(f"Обнаружены документы из раздела 'О школе' в контексте для LLM: {school_sources_in_hits} - поиск первоисточников будет отключен")

    # Формируем контексты с указанием источника для лучшей структуры
    contexts = []
    for i, h in enumerate(hits[:3], 1):
        contexts.append(f"[Источник {i}: {h.source}]\n{h.text}")

    # Для общих запросов по программам добавляем сводку из 1.2 в начало контекстов
    try:
        if 'is_general_programs' in locals() and is_general_programs:
            programs_file = os.path.join(STRUCTURED_DIR, "1.2_Виды обучения_structured.txt")
            if os.path.exists(programs_file):
                with open(programs_file, "r", encoding="utf-8") as f:
                    txt = f.read()
                lines = []
                for block in txt.split("Сертификат "):
                    if "|" not in block:
                        continue
                    title_part = block.split("|", 1)[1]
                    title_clean = title_part.split("Рис.")[0]
                    title_clean = title_clean.split("###")[0].strip()
                    if not title_clean:
                        continue
                    m_cost = re.search(r"стоимость\s+([0-9\s]+\s*руб\.?(:?/час)?)", block, re.IGNORECASE)
                    if m_cost:
                        lines.append(f"- {title_clean} — {m_cost.group(1).strip()}")
                    else:
                        lines.append(f"- {title_clean}")
                if lines:
                    summary_ctx = "[Источник: 1.2_Виды обучения_structured.txt]\n" + "\n".join(lines)
                    contexts.insert(0, summary_ctx)
    except Exception:
        pass

    # Если явный запрос цены/стоимости, добавляем структурированный прайс из 1.2
    price_intent = any(kw in user_q.lower() for kw in [
        "стоимость", "цена", "сколько стоит", "сколько стоит обучение",
        "сколько стоит курс", "прайс", "оплата", "руб", "руб.", "руб/час"
    ])
    if price_intent:
        try:
            price_file = os.path.join(STRUCTURED_DIR, "1.2_Виды обучения_structured.txt")
            if os.path.exists(price_file):
                with open(price_file, "r", encoding="utf-8") as f:
                    txt = f.read()
                import re as _re
                entries = []
                for block in txt.split("Сертификат "):
                    if "|" not in block or "стоимость" not in block:
                        continue
                    title_part = block.split("|", 1)[1]
                    title_clean = title_part.split("Рис.")[0]
                    title_clean = title_clean.split("###")[0].strip()
                    m_cost = _re.search(r"стоимость\s+([0-9\s]+\s*руб\.?(:?/час)?)", block, _re.IGNORECASE)
                    if title_clean and m_cost:
                        cost = m_cost.group(1).strip()
                        entries.append((title_clean, cost))
                if entries:
                    price_lines = [f"- {t} — {c}" for t, c in entries]
                    price_context = "[Источник: 1.2_Виды обучения_structured.txt]\n" + "\n".join(price_lines)
                    contexts.insert(0, price_context)
        except Exception:
            pass

    # Если нет контекстов из БЗ — возвращаем стандартное сообщение
    if not contexts:
        logger.warning(f"Нет результатов поиска для запроса: '{user_q}'")
        await _answer_with_sticker_cleanup(message, "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос.", waiting_sticker_message)
        return

    # Формируем промпт с учётом истории чата
    history_context = ""
    if chat_history:
        recent_history = chat_history[-5:] if len(chat_history) > 5 else chat_history
        history_lines = []
        for msg in recent_history:
            role_ru = "Пользователь" if msg["role"] == "user" else "Ассистент"
            history_lines.append(f"{role_ru}: {msg['content']}")
        history_context = "\n\nПредыдущий диалог:\n" + "\n".join(history_lines) + "\n"

    prompt = f"""Контексты из Базы знаний:

{chr(10).join([f"--- Контекст {i+1} ---{chr(10)}{ctx}" for i, ctx in enumerate(contexts[:3])])}

{history_context}

Вопрос клиента: {user_q}

Инструкция: Ответь на вопрос клиента на основе ПРЕДОСТАВЛЕННЫХ КОНТЕКСТОВ. Следуй системному промпту (ты Леонидыч, ассистент школы бильярда «Абриколь»). Используй ТОЛЬКО информацию из контекстов выше. Если информации недостаточно, скажи об этом. Отвечай кратко, естественно, как живой человек."""

    logger.info(
        f"Отправка запроса в DeepSeek API. Длина системного промпта: {len(prompt_config.SYSTEM_PROMPT)} символов"
    )
    logger.debug(f"Системный промпт: {prompt_config.SYSTEM_PROMPT[:200]}...")
    logger.debug(f"Пользовательский промпт: {prompt[:300]}...")

    try:
        answer = await deepseek.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=prompt_config.SYSTEM_PROMPT,
            temperature=prompt_config.TEMPERATURE,
            max_tokens=prompt_config.MAX_TOKENS,
        )
        logger.info(f"Получен ответ от DeepSeek: {answer[:100]}...")
        if not answer or len(answer.strip()) < 10:
            answer = contexts[0] if contexts else "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос."
    except Exception as e:
        logger.warning(f"Ошибка при вызове DeepSeek API: {e}")
        answer = "\n\n".join(contexts[:2]) if contexts else "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос."

    try:
        data = await state.get_data()
    except Exception as state_get_error:
        logger.warning(f"Не удалось получить данные state: {state_get_error}")
        data = {}

    # ========== ОБРАБОТКА ФАЗ ОБЩЕНИЯ ==========

    # Проверяем ответ LLM на наличие фразы о начале анкетирования (Фаза 3)
    answer_lower = answer.lower() if answer else ""
    has_anketa_phrase = "проведём небольшое анкетирование" in answer_lower or "анкетирование" in answer_lower
    has_ready_phrase = "я снова готов к вашим вопросам" in answer_lower or "я готов к вашим вопросам" in answer_lower

    # has_school_sources_in_llm уже установлен выше на основе наличия документов из раздела "О школе" в топ-3
    # Если в топ-3 есть документы из раздела "О школе" (1.1, 1.2, 1.3, 1.4), поиск первоисточников всегда блокируется

    # Если LLM начал анкетирование, переходим к Фазе 3
    # НО не переходим, если пользователь только что нажал "Продолжить"
    continue_button_pressed = data.get("continue_button_pressed", False)
    if has_anketa_phrase and current_phase < 3 and not continue_button_pressed:
        await state.update_data(phase=3, anketa_started=True, anketa_question=1)
        logger.info(f"Переход к Фазе 3 (Анкетирование) для пользователя {user_id}")
    elif continue_button_pressed:
        # Сбрасываем флаг после обработки запроса
        await state.update_data(continue_button_pressed=False)

    # Если LLM сказал "готов к вопросам", возвращаемся к Фазе 1
    if has_ready_phrase:
        await state.update_data(phase=1)
        logger.info(f"Возврат к Фазе 1 для пользователя {user_id}")

    # ========== КОНЕЦ ОБРАБОТКИ ФАЗ ==========

    user_lower = user_q.lower()

    # СНАЧАЛА определяем, является ли запрос исключенным
    # Исключаем слишком короткие или общие запросы из поиска по правилам
    # (например, "ты кто", "кто ты", "помощь" и т.д.)
    excluded_general_queries = [
        "ты кто", "кто ты", "что ты", "что такое ты",
        "помощь", "помоги", "что умеешь", "что можешь",
        "привет", "здравствуй", "добрый", "доброе",
        "как дела", "как поживаешь",
    ]
    # Проверяем исключенные запросы более строго
    # Для коротких запросов проверяем точное совпадение
    is_excluded_query = any(pattern in user_lower for pattern in excluded_general_queries)

    # КРИТИЧЕСКАЯ ПРОВЕРКА: Если запрос содержит "ты кто" или "кто ты" - ВСЕГДА блокируем
    # независимо от других условий (это может быть часть более длинного запроса, но все равно блокируем)
    critical_excluded = ["ты кто", "кто ты"]
    if any(pattern in user_lower for pattern in critical_excluded):
        is_excluded_query = True
        logger.info(f"КРИТИЧЕСКАЯ БЛОКИРОВКА: Запрос '{user_q}' содержит критический исключенный паттерн")

    # Дополнительная проверка: если запрос очень короткий (<= 10 символов) и содержит только исключенные слова
    if len(user_lower.strip()) <= 10 and is_excluded_query:
        # Усиливаем проверку для очень коротких запросов
        words = user_lower.strip().split()
        excluded_words = ["ты", "кто", "что", "помощь", "помоги", "привет", "здравствуй", "добрый", "доброе", "как", "дела", "поживаешь", "умеешь", "можешь"]
        if all(w in excluded_words for w in words if len(w) > 1):
            is_excluded_query = True
            logger.info(f"Усиленная блокировка для короткого исключенного запроса '{user_q}'")

    matched_corpus_from_alias = None

    # Приоритет специфичным ключевым словам (технич, размер, требован, аксес, оборуд) над общими (правила)
    # Сначала проверяем специфичные ключевые слова для технических требований
    # НО: не устанавливаем для исключенных запросов
    if not is_excluded_query:
        technical_keywords = ["технич", "размер", "требован", "аксес", "оборуд"]
        for kw in technical_keywords:
            if kw in user_lower and kw in PRIMARY_SOURCE_ALIASES:
                matched_corpus_from_alias = PRIMARY_SOURCE_ALIASES[kw]
                break

    # Если специфичных ключевых слов нет, проверяем остальные
    # НО: для общего алиаса "правила" требуем более строгую проверку
    # И НЕ устанавливаем matched_corpus_from_alias для исключенных запросов
    if not matched_corpus_from_alias and not is_excluded_query:
        for alias, file_name in PRIMARY_SOURCE_ALIASES.items():
            if alias in user_lower:
                # Для общего алиаса "правила" требуем, чтобы это было частью значимого контекста
                # (не просто случайное совпадение в коротком запросе)
                if alias == "правила":
                    # Проверяем, что запрос достаточно информативен (не менее 8 символов)
                    # или содержит другие ключевые слова, связанные с правилами
                    if len(user_lower) < 8:
                        # Для коротких запросов требуем дополнительные ключевые слова
                        rule_context_words = ["игр", "корона", "пирамида", "международ", "бильярд"]
                        has_rule_context = any(word in user_lower for word in rule_context_words)
                        if not has_rule_context:
                            continue  # Пропускаем этот алиас для коротких запросов без контекста
                matched_corpus_from_alias = file_name
                break

    # Сначала определяем rule_query на основе стандартных проверок
    # НО: если запрос исключен из общих запросов, не считаем его запросом о правилах
    rule_query = False
    if not is_excluded_query:
        rule_query = is_rule_intent(user_q) or (
            matched_corpus_from_alias in RULE_PRIMARY_ALLOWED_SOURCES if matched_corpus_from_alias else False
        )
        if rule_query:
            logger.info(f"rule_query=True для запроса '{user_q}': is_rule_intent={is_rule_intent(user_q)}, matched_corpus_from_alias={matched_corpus_from_alias}")
    else:
        logger.info(f"Запрос '{user_q}' исключен из поиска по правилам (общий запрос), is_excluded_query=True")

    # Проверяем, есть ли в hits источники из правил (2.x_), даже если классификация темы была "school"
    # Это важно для случаев, когда запрос может быть про технические требования, но классифицирован как "school"
    # НО: не переопределяем rule_query для исключенных запросов
    has_rules_sources_in_hits = any(h.source and h.source.startswith("2.") for h in hits) if hits else False

    # Если есть источники из правил в hits, но классификация была "school", переопределяем rule_query
    # НО только если запрос не был исключен
    if has_rules_sources_in_hits and detected_topic == "school" and not is_excluded_query:
        # Проверяем, есть ли среди источников технические требования
        has_technical_in_hits = any(
            h.source and "2.2_Технические требования" in h.source
            for h in hits
        )
        if has_technical_in_hits:
            # Если есть технические требования в hits, это точно запрос по правилам
            rule_query = True
            logger.info(f"Переопределен rule_query=True: обнаружены технические требования в hits при классификации 'school'")

    # Определяем, есть ли в запросе специфические ключевые слова для конкретных документов
    # Если есть "корона", "пирамида", "международ" - ограничиваемся конкретным документом
    specific_game_keywords = ["корона", "пирамида", "международ", "правила корона", "игре корона"]
    has_specific_game = any(kw in user_lower for kw in specific_game_keywords)

    # Устанавливаем allowed_sources ТОЛЬКО если запрос не исключен
    if is_excluded_query:
        allowed_sources = []
        logger.info(f"allowed_sources заблокирован для исключенного запроса '{user_q}'")
    elif matched_corpus_from_alias and matched_corpus_from_alias in RULE_PRIMARY_ALLOWED_SOURCES:
        # Если есть специфическое ключевое слово игры - ограничиваемся конкретным документом
        if has_specific_game:
            allowed_sources = [matched_corpus_from_alias]
        # Если запрос связан с правилами - ищем по всем документам правил
        elif rule_query:
            allowed_sources = list(RULE_PRIMARY_ALLOWED_SOURCES)
        else:
            # Для других запросов ограничиваемся одним документом
            allowed_sources = [matched_corpus_from_alias]
    elif matched_corpus_from_alias:
        # Для других запросов ограничиваемся одним документом
        allowed_sources = [matched_corpus_from_alias]
    else:
        # Если нет совпадений в PRIMARY_SOURCE_ALIASES, но запрос связан с правилами - ищем по всем документам правил
        if rule_query:
            allowed_sources = list(RULE_PRIMARY_ALLOWED_SOURCES)
            logger.info(f"allowed_sources установлен на все источники правил для rule_query=True")
        else:
            allowed_sources = []

    primary_sources_blocked = any(stop_word in user_lower for stop_word in STOP_WORDS_FOR_PRIMARY)
    candidate_sources: list[str] = []
    for alias, file_name in PRIMARY_SOURCE_ALIASES.items():
        if alias in user_lower:
            candidate_sources.append(file_name)
    for h in hits:
        if h.source:
            candidate_sources.append(h.source)
    candidate_sources = _unique_preserving(candidate_sources)
    if not candidate_sources and hits:
        first_src = hits[0].source
        if first_src:
            candidate_sources.append(first_src)
    main_source = candidate_sources[0] if candidate_sources else None

    # === Блок построения первоисточников ===
    primary_sources = []
    allow_rule_button = False

    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: Для исключенных запросов полностью блокируем поиск первоисточников
    if is_excluded_query:
        logger.info(f"ЖЕСТКАЯ БЛОКИРОВКА: Поиск первоисточников и кнопка 'Первоисточник' ЗАПРЕЩЕНЫ для исключенного запроса '{user_q}'")
        primary_sources = []
        allow_rule_button = False
        stored_primary_sources = []
    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: Для Фаз 3 и 4 полностью блокируем поиск первоисточников и показ кнопки
    elif current_phase == 3 or current_phase == 4:
        logger.info(f"ЖЕСТКАЯ БЛОКИРОВКА: Поиск первоисточников и кнопка 'Первоисточник' ЗАПРЕЩЕНЫ для Фазы {current_phase}")
        primary_sources = []
        allow_rule_button = False
        stored_primary_sources = []
    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: Если есть документы из раздела "О школе" в контексте для LLM,
    # ПОЛНОСТЬЮ запрещаем поиск первоисточников и показ кнопки "Первоисточник"
    # НО только если запрос НЕ относится к правилам (rule_query=False)
    # Если запрос относится к правилам (rule_query=True), кнопка должна показываться независимо от наличия документов "О школе"
    elif has_school_sources_in_llm and not rule_query:
        logger.info(f"ЖЕСТКАЯ БЛОКИРОВКА: Поиск первоисточников и кнопка 'Первоисточник' ЗАПРЕЩЕНЫ для раздела 'О школе' (rule_query=False)")
        primary_sources = []
        allow_rule_button = False
        stored_primary_sources = []
    else:
        try:
            # если есть блокировка (по стоп-словам) — ничего не делаем
            if primary_sources_blocked:
                allowed_sources = []

            # если есть хоть что-то разрешённое — строим
            if allowed_sources:
                logger.info(f"Поиск первоисточников для запроса '{user_q}' с allowed_sources={allowed_sources}")
                primary_sources = search_store.get_primary_source_fragments(
                    hits[:5],
                    user_q,
                    allowed_sources=allowed_sources,
                )
                logger.info(f"Найдено фрагментов: {len(primary_sources)}")
                # Логируем источники фрагментов для отладки
                if primary_sources:
                    sources_in_fragments = set(f.get('source', '') for f in primary_sources if isinstance(f, dict))
                    logger.info(f"Источники в найденных фрагментах: {sources_in_fragments}")
                    technical_fragments = [f for f in primary_sources if isinstance(f, dict) and '2.2_Технические требования' in f.get('source', '')]
                    logger.info(f"Фрагментов из технических требований: {len(technical_fragments)}")

                    # Проверяем релевантность найденных фрагментов для исключенных запросов
                    # Если запрос был исключен из общих запросов, но фрагменты найдены - проверяем их релевантность
                    if is_excluded_query:
                        logger.info(f"Запрос '{user_q}' был исключен из общих, но найдены фрагменты - проверяем релевантность")
                        # Фильтруем фрагменты: оставляем только те, которые содержат ключевые слова из запроса
                        # (исключая служебные слова)
                        query_words = [w for w in user_lower.split() if len(w) > 2 and w not in ["ты", "кто", "что", "как", "где", "когда", "это", "для", "при", "над", "под"]]
                        if query_words:
                            relevant_fragments = []
                            for frag in primary_sources:
                                if isinstance(frag, dict):
                                    frag_text = (frag.get('text', '') or '').lower()
                                    # Проверяем, содержит ли фрагмент хотя бы одно значимое слово из запроса
                                    if any(word in frag_text for word in query_words):
                                        relevant_fragments.append(frag)
                            if not relevant_fragments:
                                logger.info(f"Найденные фрагменты не релевантны запросу '{user_q}' - блокируем кнопку")
                                primary_sources = []
                                allow_rule_button = False
                            else:
                                primary_sources = relevant_fragments
                                logger.info(f"Оставлено релевантных фрагментов: {len(primary_sources)}")
                        else:
                            # Если нет значимых слов в запросе - блокируем
                            logger.info(f"Запрос '{user_q}' не содержит значимых слов - блокируем кнопку")
                            primary_sources = []
                            allow_rule_button = False

                    allow_rule_button = bool(primary_sources)
                    if primary_sources:
                        logger.info(f"allow_rule_button установлен в True для запроса '{user_q}', найдено {len(primary_sources)} фрагментов")
                    # Если не нашли фрагменты с ограничениями, но запрос связан с правилами - пробуем без ограничений
                    if not primary_sources and rule_query and not primary_sources_blocked:
                        logger.info(f"Фрагменты не найдены с ограничениями, пробуем без ограничений для запроса '{user_q}'")
                        primary_sources = search_store.get_primary_source_fragments(
                            hits[:5],
                            user_q,
                        )
                        logger.info(f"Найдено фрагментов без ограничений: {len(primary_sources)}")
                        allow_rule_button = bool(primary_sources)
                # если не было стоп-слов, но у нас вообще нет ограничений — пробуем просто по hits
                # НО только если запрос не был исключен из общих запросов
                elif not primary_sources_blocked and rule_query and not is_excluded_query:
                    logger.info(f"Поиск первоисточников для запроса '{user_q}' без ограничений (rule_query=True)")
                    primary_sources = search_store.get_primary_source_fragments(
                        hits[:5],
                        user_q,
                    )
                    logger.info(f"Найдено фрагментов: {len(primary_sources)}")
                    allow_rule_button = bool(primary_sources)
                elif is_excluded_query:
                    logger.info(f"Поиск первоисточников заблокирован для исключенного запроса '{user_q}'")
                    primary_sources = []
                    allow_rule_button = False
                # если иначе — всё пусто
                else:
                    logger.info(f"Поиск первоисточников заблокирован для запроса '{user_q}'")
        except Exception as primary_error:
            logger.warning(f"Ошибка при построении первоисточников: {primary_error}", exc_info=True)
            primary_sources = []
            allow_rule_button = False

    fragment_sources: set[str] = {
        fr.get("source") for fr in primary_sources if isinstance(fr, dict) and fr.get("source")
    }
    logger.info(f"fragment_sources после извлечения из primary_sources: {fragment_sources}, primary_sources count: {len(primary_sources)}")
    if not fragment_sources and main_source:
        fragment_sources = {main_source}
        logger.info(f"fragment_sources установлен из main_source: {fragment_sources}")

    # Дополнительная проверка: если fragment_sources пуст, но в hits есть источники из правил (2.x_)
    # Это важно для технических требований (2.2), которые могут быть отфильтрованы
    if not fragment_sources and hits:
        rules_sources_in_hits = {h.source for h in hits if h.source and h.source in RULE_PRIMARY_ALLOWED_SOURCES}
        if rules_sources_in_hits:
            fragment_sources = rules_sources_in_hits
            logger.info(f"fragment_sources установлен из hits (источники правил): {fragment_sources}")
            # Если main_source не установлен, устанавливаем его из первого найденного источника
            if not main_source:
                main_source = list(rules_sources_in_hits)[0]
                logger.info(f"main_source установлен из fragment_sources: {main_source}")

    # Если fragment_sources все еще пуст, но есть primary_sources и allowed_sources - используем allowed_sources
    # Это важно для случаев, когда фрагменты не имеют поля "source"
    if not fragment_sources and primary_sources and allowed_sources:
        # Используем первый источник из allowed_sources, который есть в RULE_PRIMARY_ALLOWED_SOURCES
        for src in allowed_sources:
            if src in RULE_PRIMARY_ALLOWED_SOURCES:
                fragment_sources = {src}
                if not main_source:
                    main_source = src
                logger.info(f"fragment_sources установлен из allowed_sources: {fragment_sources} для запроса '{user_q}'")
                break

    # Если fragment_sources все еще пуст, но есть primary_sources - пытаемся получить источники из hits
    # Это важно для случаев, когда фрагменты не имеют поля "source"
    if not fragment_sources and primary_sources and rule_query:
        logger.info(f"fragment_sources пуст, но есть primary_sources, пытаемся получить источники из hits")
        for h in hits[:5]:
            if h.source and h.source in RULE_PRIMARY_ALLOWED_SOURCES:
                fragment_sources.add(h.source)
                if not main_source:
                    main_source = h.source
                logger.info(f"Добавлен источник {h.source} из hits для запроса '{user_q}'")
                break

    # Если фрагменты не найдены, но есть hits из документов правил - добавляем их источники
    # Это важно для запросов типа "оборуд" и "аксес"
    if not fragment_sources and rule_query:
        for h in hits[:5]:
            if h.source and h.source in RULE_PRIMARY_ALLOWED_SOURCES:
                fragment_sources.add(h.source)
                if not main_source:
                    main_source = h.source
                logger.info(f"Добавлен источник {h.source} из hits для запроса '{user_q}'")
                break

    if not rule_query and fragment_sources:
        if any(src in RULE_PRIMARY_ALLOWED_SOURCES for src in fragment_sources):
            rule_query = True

    logger.info(f"Проверка перед блокировкой: allow_rule_button={allow_rule_button}, rule_query={rule_query}, fragment_sources={fragment_sources}, allowed_sources={allowed_sources}")

    # Если в LLM были отправлены документы из раздела "О школе", полностью блокируем кнопку
    # НО только если запрос НЕ относится к правилам (rule_query=False)
    # Если запрос относится к правилам (rule_query=True), кнопка должна показываться независимо от наличия документов "О школе"
    if has_school_sources_in_llm and not rule_query:
        allow_rule_button = False
        primary_sources = []
        logger.info(f"Кнопка 'Первоисточник' заблокирована: обнаружены документы из раздела 'О школе' в контексте для LLM (rule_query=False)")

    if allow_rule_button:
        # Если fragment_sources пуст, но есть allowed_sources - используем их
        if not fragment_sources and allowed_sources:
            for src in allowed_sources:
                if src in RULE_PRIMARY_ALLOWED_SOURCES:
                    fragment_sources = {src}
                    logger.info(f"fragment_sources установлен из allowed_sources в проверке: {fragment_sources}")
                    break

        # Если fragment_sources пуст или не содержит источников из правил, проверяем hits
        if not fragment_sources or not any(src in RULE_PRIMARY_ALLOWED_SOURCES for src in fragment_sources):
            # Проверяем, есть ли источники из правил в hits
            # Это важно для технических требований (2.2) и других случаев
            rules_sources_in_hits = [h.source for h in hits if h.source and h.source in RULE_PRIMARY_ALLOWED_SOURCES]
            if rules_sources_in_hits:
                # Если есть источники из правил в hits, добавляем их в fragment_sources
                fragment_sources = set(rules_sources_in_hits)
                logger.info(f"fragment_sources обновлен из hits: {fragment_sources}")
                # Также обновляем rule_query, если он был False
                if not rule_query:
                    rule_query = True
                    logger.info(f"rule_query обновлен на True на основе источников из hits")
                # Если primary_sources пуст, но rule_query=True, разрешаем кнопку
                if not primary_sources and rule_query:
                    allow_rule_button = True
                    logger.info(f"allow_rule_button установлен в True для rule_query=True, даже если primary_sources пуст")
            elif not rule_query:
                logger.warning(f"Кнопка заблокирована: fragment_sources {fragment_sources} не содержит источников из RULE_PRIMARY_ALLOWED_SOURCES и нет источников в hits, rule_query=False")
                allow_rule_button = False
                primary_sources = []
                allowed_sources = []

        # Финальная проверка: если rule_query=True и есть fragment_sources из правил, разрешаем кнопку
        if rule_query and fragment_sources and any(src in RULE_PRIMARY_ALLOWED_SOURCES for src in fragment_sources):
            if not allow_rule_button:
                allow_rule_button = True
                logger.info(f"allow_rule_button установлен в True для rule_query=True с fragment_sources={fragment_sources}")

        if allow_rule_button and not any(src in RULE_PRIMARY_ALLOWED_SOURCES for src in fragment_sources):
            logger.warning(f"Кнопка заблокирована: fragment_sources {fragment_sources} не содержит источников из RULE_PRIMARY_ALLOWED_SOURCES")
            allow_rule_button = False
            primary_sources = []
            allowed_sources = []
        elif allow_rule_button and not rule_query:
            logger.warning(f"Кнопка заблокирована: rule_query={rule_query} для запроса '{user_q}'")
            allow_rule_button = False
            primary_sources = []
            allowed_sources = []
        elif allow_rule_button:
            logger.info(f"Кнопка разрешена: allow_rule_button={allow_rule_button}, rule_query={rule_query}, fragment_sources={fragment_sources}")
    # Если фрагменты не найдены, но запрос связан с правилами и есть hits из документов правил - показываем кнопку
    # НО: не выполняем поиск, если в LLM были отправлены документы из раздела "О школе"
    if not allow_rule_button and rule_query and fragment_sources and not has_school_sources_in_llm:
        if any(src in RULE_PRIMARY_ALLOWED_SOURCES for src in fragment_sources):
            # Пробуем еще раз найти фрагменты без ограничений
            if not primary_sources and not primary_sources_blocked:
                logger.info(f"Повторный поиск фрагментов для запроса '{user_q}' без ограничений")
                primary_sources = search_store.get_primary_source_fragments(
                    hits[:5],
                    user_q,
                )
                if primary_sources:
                    allow_rule_button = True
                    logger.info(f"Найдено фрагментов при повторном поиске: {len(primary_sources)}")
                else:
                    # Если фрагменты все еще не найдены, но есть hits из документов правил -
                    # создаем минимальный фрагмент на основе первого hit
                    for h in hits[:5]:
                        if h.source and h.source in RULE_PRIMARY_ALLOWED_SOURCES:
                            logger.info(f"Создаем фрагмент на основе hit для источника {h.source}, запрос '{user_q}'")
                            # Создаем минимальный фрагмент для показа кнопки
                            # Используем текст из hit, если доступен
                            hit_text = ""
                            if hasattr(h, 'text') and h.text:
                                hit_text = h.text[:500]
                            elif hasattr(h, 'content') and h.content:
                                hit_text = h.content[:500]

                            primary_sources = [{
                                "source": h.source,
                                "text": hit_text,
                                "section": "",
                                "_position": 0
                            }]
                            allow_rule_button = True
                            fragment_sources = {h.source}
                            if not main_source:
                                main_source = h.source
                            logger.info(f"Фрагмент создан, allow_rule_button={allow_rule_button}, fragment_sources={fragment_sources}")
                            break

    if allow_rule_button:
        # не показываем кнопку, если "правила" есть, а конкретной игры нет (для документов 2.1.x)
        # НО: если в fragment_sources есть технические требования (2.2), то проверка на игру не применяется
        # ИЛИ: если запрос содержит "оборуд" или "аксес", то проверка на игру не применяется
        # ИЛИ: если запрос содержит только базовые термины бильярда, то проверка на игру не применяется
        TECHNICAL_REQUIREMENTS_SOURCE = "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt"
        has_technical_requirements = TECHNICAL_REQUIREMENTS_SOURCE in fragment_sources
        is_equipment_query = "оборуд" in user_lower or "аксес" in user_lower

        # Базовые термины бильярда, которые не требуют указания конкретной игры
        # Эти термины являются общими для всех игр и не требуют уточнения
        BASIC_BILLIARD_TERMS = (
            "биток", "бит", "прицел", "прицельн", "шар", "шары", "шарик", "шарики",
            "штраф", "нарушен", "удар", "удара", "кий", "кием", "стол",
            "луза", "лузы", "борт", "борта", "разметк", "разметка"
        )
        is_basic_term_query = any(term in user_lower for term in BASIC_BILLIARD_TERMS)

        if not has_technical_requirements and not is_equipment_query and not is_basic_term_query:
            # Проверка на игру применяется только если нет технических требований И запрос не про оборудование/аксессуары И не только базовые термины
            RULE_DISCIPLINE_HINTS = (
                "корона", "пирамида", "свободная", "комбинированная", "динамичная", "классическая",
                "71 очко", "51 очко", "8 очков"
            )
            game_required_sources = RULE_PRIMARY_ALLOWED_SOURCES - {
                TECHNICAL_REQUIREMENTS_SOURCE,
            }
            requires_game_hint = any(src in game_required_sources for src in fragment_sources)
            if requires_game_hint:
                no_game = not any(hint in user_lower for hint in RULE_DISCIPLINE_HINTS)
                if is_rule_intent(user_q) and no_game:
                    logger.warning(f"Кнопка заблокирована: требуется указание игры для источников {fragment_sources}")
                    allow_rule_button = False
                else:
                    logger.info(f"Проверка игры пройдена: requires_game_hint={requires_game_hint}, no_game={no_game}")
        else:
            if has_technical_requirements:
                logger.info(f"Проверка игры пропущена: есть технические требования в fragment_sources {fragment_sources}")
            if is_equipment_query:
                logger.info(f"Проверка игры пропущена: запрос про оборудование/аксессуары '{user_q}'")
            if is_basic_term_query:
                logger.info(f"Проверка игры пропущена: запрос содержит базовые термины бильярда '{user_q}'")

    focused_fragments = primary_sources[:1] if primary_sources else []

    # Автоматически находим рисунки в релевантных контекстах
    used_hits = hits[:3] if len(hits) > 3 else hits
    figures_found = []
    forced_figures: set[str] = set()

    try:
        for hit in used_hits:
            if hit.figures:
                for fig in hit.figures.split(","):
                    fig = fig.strip()
                    if fig:
                        # Рис.1.2.1 добавляется только если в ответе LLM есть "начальный курс"
                        if fig == "Рис.1.2.1":
                            if answer and "начальный курс" in answer.lower():
                                figures_found.append(fig)
                        else:
                            figures_found.append(fig)

        figures_in_answer = image_mapper.find_figures_in_text(answer) if answer else []
        figures_in_question = image_mapper.find_figures_in_text(user_q) if user_q else []
        for fig in figures_in_question:
            forced_figures.add(fig)

        # Фильтруем Рис.1.2.1 из figures_in_answer - он должен добавляться только если в ответе есть "начальный курс"
        # НО НЕ добавляем его, если он найден только через find_figures_in_text (т.е. только упоминание "Рис.1.2.1" в тексте)
        # Рис.1.2.1 должен добавляться только через явную проверку наличия фразы "начальный курс" в ответе
        filtered_figures_in_answer = []
        for fig in figures_in_answer:
            if fig == "Рис.1.2.1":
                # НЕ добавляем Рис.1.2.1 из figures_in_answer - он будет добавлен позже только если есть "начальный курс"
                # Это предотвращает добавление Рис.1.2.1, если он найден только по упоминанию в тексте (например, в названии)
                pass
            else:
                filtered_figures_in_answer.append(fig)

        figures_found.extend(filtered_figures_in_answer)
        figures_found.extend(figures_in_question)
    except Exception as e:
        logger.warning(f"Ошибка при поиске рисунков в тексте: {e}")

    lowered_q = user_lower

    # Рисунки для Корона и Технических требований теперь определяются при открытии окна первоисточника
    # и не добавляются в figures_found здесь

    figures_found = _unique_preserving(figures_found + list(forced_figures))

    blocked_figures: set[str] = set()
    if re.search(r"разм\w*\s+луз", lowered_q):
        blocked_figures.add("Рис.2.2.5")

    if blocked_figures:
        figures_found = [fig for fig in figures_found if fig not in blocked_figures]
        forced_figures.difference_update(blocked_figures)

    question_keywords = {w for w in re.findall(r"\w+", user_q.lower()) if len(w) >= 3}
    all_keywords = set(question_keywords)
    stop_keywords = {"сертификат", "сертификата", "сертификаты"}
    all_keywords = {w for w in all_keywords if w not in stop_keywords}

    # Остальные фразы проверяются в запросе пользователя
    course_figures_user_query = {
        "начальный курс": "Рис.1.2.1",
        "к1": "Рис.1.2.1",
        "сертификат 1": "Рис.1.2.1",
        "сертификат к1": "Рис.1.2.1",
        "сертификат №1": "Рис.1.2.1",
        "сертификат № 1": "Рис.1.2.1",
        "базовый курс": "Рис.1.2.2",
        "к2": "Рис.1.2.2",
        "сертификат 2": "Рис.1.2.2",
        "сертификат к2": "Рис.1.2.2",
        "сертификат №2": "Рис.1.2.2",
        "сертификат № 2": "Рис.1.2.2",
        "экспресс": "Рис.1.2.3",
        "к3": "Рис.1.2.3",
        "сертификат 3": "Рис.1.2.3",
        "сертификат к3": "Рис.1.2.3",
        "сертификат №3": "Рис.1.2.3",
        "сертификат № 3": "Рис.1.2.3",
        "тестирован": "Рис.1.2.4",
        "т1": "Рис.1.2.4",
        "сертификат т1": "Рис.1.2.4",
        "сертификат №4": "Рис.1.2.4",
        "сертификат № 4": "Рис.1.2.4",
        "тренинг": "Рис.1.2.5",
        "у1": "Рис.1.2.5",
        "сертификат у1": "Рис.1.2.5",
        "сертификат №5": "Рис.1.2.5",
        "сертификат № 5": "Рис.1.2.5",
        "абонемент": "Рис.1.2.6",
        "мастер": "Рис.1.2.6",
        "сертификат а1": "Рис.1.2.6",
        "сертификат №6": "Рис.1.2.6",
        "сертификат № 6": "Рис.1.2.6",
        "юниор": "Рис.1.2.7",
        "сертификат а2": "Рис.1.2.7",
        "сертификат №7": "Рис.1.2.7",
        "сертификат № 7": "Рис.1.2.7",
        "профи": "Рис.1.2.8",
        "сертификат а3": "Рис.1.2.8",
        "сертификат №8": "Рис.1.2.8",
        "сертификат № 8": "Рис.1.2.8",
    }
    course_figure_selected = False
    course_selected_figures: set[str] = set()
    # ПРИОРИТЕТНАЯ ПРОВЕРКА: Если в ответе LLM есть "начальный курс" (НЕ "начальный удар"),
    # то НЕ добавляем рисунки по запросу пользователя, а сразу устанавливаем флаг для Рис.1.2.1
    has_initial_course_in_answer = False
    if answer and isinstance(answer, str):
        answer_lower = answer.lower()
        # Проверяем ТОЧНУЮ фразу "начальный курс" (не "начальный удар")
        has_initial_course_phrase = "начальный курс" in answer_lower
        # Проверяем, что это НЕ про правила (нет "начальный удар")
        has_initial_strike = "начальный удар" in answer_lower
        has_initial_course_in_answer = has_initial_course_phrase and not has_initial_strike and has_school_sources_in_llm

        if has_initial_course_in_answer:
            logger.info(f"✅ ОБНАРУЖЕН 'начальный курс' в ответе LLM - блокируем добавление других рисунков по запросу пользователя")

    # Добавляем рисунки по запросу пользователя ТОЛЬКО если нет "начальный курс" в ответе LLM
    if not has_initial_course_in_answer:
        for phrase, fig_key in course_figures_user_query.items():
            if phrase in user_q.lower():
                figures_found.append(fig_key)
                course_figure_selected = True
                course_selected_figures.add(fig_key)

    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: Рис.1.2.1 показывается ТОЛЬКО когда:
    # 1. В ответе LLM есть ТОЧНАЯ фраза "начальный курс" (НЕ "начальный удар")
    # 2. И это относится к разделу "О школе" (has_school_sources_in_llm = True)
    # 3. И нет признаков правил (удар, биток и т.д.)
    # 4. При показе Рис.1.2.1 все остальные рисунки (включая 1.2.2, 1.2.3) НЕ показываются
    if answer and has_school_sources_in_llm:
        answer_lower = answer.lower()
        # Проверяем ТОЧНУЮ фразу "начальный курс" (регистронезависимо)
        has_initial_course_phrase = "начальный курс" in answer_lower
        # Проверяем, что это НЕ "начальный удар" из правил
        has_initial_strike = "начальный удар" in answer_lower

        # Рис.1.2.1 показывается ТОЛЬКО если есть "начальный курс" И НЕТ "начальный удар"
        if has_initial_course_phrase and not has_initial_strike:
            # Дополнительная проверка: не добавляем, если в ответе есть другие признаки правил
            rules_indicators_in_answer = ["биток", "прицел", "шар", "луза", "пирамида", "правила игры", "штраф", "соударение"]
            has_rules_in_answer = any(indicator in answer_lower for indicator in rules_indicators_in_answer)

            if not has_rules_in_answer:
                # Добавляем Рис.1.2.1, если его еще нет
                if "Рис.1.2.1" not in figures_found:
                    figures_found.append("Рис.1.2.1")
                course_figure_selected = True
                course_selected_figures.add("Рис.1.2.1")
                # ЖЕСТКО: При показе Рис.1.2.1 удаляем ВСЕ остальные рисунки (включая 1.2.2, 1.2.3 и все остальные)
                # Оставляем только Рис.1.2.1
                figures_found = ["Рис.1.2.1"]
                course_selected_figures = {"Рис.1.2.1"}
                forced_figures = set()  # Очищаем forced_figures, чтобы не добавлялись другие рисунки
                logger.info(f"✅ Рис.1.2.1 добавлен при наличии 'начальный курс' в ответе LLM. ВСЕ остальные рисунки удалены, оставлен только Рис.1.2.1.")
            else:
                logger.info(f"Рис.1.2.1 НЕ добавлен: обнаружены признаки правил в ответе")
        else:
            logger.info(f"Рис.1.2.1 НЕ добавлен: нет 'начальный курс' в ответе (has_initial_course_phrase={has_initial_course_phrase}, has_initial_strike={has_initial_strike})")
    elif answer and not has_school_sources_in_llm:
        # Если это НЕ раздел "О школе", Рис.1.2.1 не показывается
        if "Рис.1.2.1" in figures_found:
            figures_found = [fig for fig in figures_found if fig != "Рис.1.2.1"]
            if "Рис.1.2.1" in course_selected_figures:
                course_selected_figures.remove("Рис.1.2.1")
            if "Рис.1.2.1" in forced_figures:
                forced_figures.remove("Рис.1.2.1")
            logger.info(f"Рис.1.2.1 удален: это НЕ раздел 'О школе'")

    # Если в ответе LLM есть "начальный курс", НЕ добавляем другие рисунки по ключевым словам
    if not has_initial_course_in_answer:
        figure_keyword_hints = {
            "лого школы": "Рис.1.1.1",
            "логотип школы": "Рис.1.1.1",
            "баннер": "Рис.1.1.2",
            "лого биса": "Рис.1.4.1",
            "логотип биса": "Рис.1.4.1",
            "форма ввода": "Рис.1.4.2",
            "навигация": "Рис.1.4.3",
            "состав упражнений": "Рис.1.4.4",
            "база данных": "Рис.1.4.5",
            "полезности": "Рис.1.4.6",
        }
        for keyword, fig in figure_keyword_hints.items():
            if keyword in lowered_q:
                figures_found.append(fig)
                forced_figures.add(fig)

    # Если в ответе LLM есть "начальный курс", НЕ добавляем другие рисунки
    if not has_initial_course_in_answer:
        if answer and (
            BRACKETED_COUNT_FIGURE_PATTERN.search(answer)
            or COUNT_FIGURE_PATTERN.search(answer)
        ):
            figures_found.append("Рис.1.4.4")
            forced_figures.add("Рис.1.4.4")

    try:
        title_candidates = image_mapper.find_figures_by_keywords(all_keywords)
        figures_found.extend(title_candidates)
    except Exception as title_error:
        logger.warning(f"Ошибка при поиске рисунков по ключевым словам: {title_error}")

    # ЖЕСТКАЯ ФИНАЛЬНАЯ ФИЛЬТРАЦИЯ: Если в ответе LLM есть "начальный курс", удаляем ВСЕ рисунки кроме Рис.1.2.1
    # И удаляем Рис.1.2.1, если его не должно быть
    if answer and isinstance(answer, str):
        answer_lower = answer.lower()
        has_initial_course_phrase = "начальный курс" in answer_lower
        has_initial_strike = "начальный удар" in answer_lower

        if has_initial_course_phrase and not has_initial_strike and has_school_sources_in_llm:
            # Если есть "начальный курс", оставляем ТОЛЬКО Рис.1.2.1
            rules_indicators = ["биток", "прицел", "шар", "луза", "пирамида", "правила игры", "штраф", "соударение"]
            has_rules = any(indicator in answer_lower for indicator in rules_indicators)

            if not has_rules:
                # Оставляем ТОЛЬКО Рис.1.2.1, удаляем все остальные
                figures_found = ["Рис.1.2.1"] if "Рис.1.2.1" in figures_found else []
                course_selected_figures = {"Рис.1.2.1"} if "Рис.1.2.1" in figures_found else set()
                forced_figures = set()
                logger.info(f"✅ ЖЕСТКАЯ ФИЛЬТРАЦИЯ: При наличии 'начальный курс' оставлен ТОЛЬКО Рис.1.2.1, все остальные удалены")
        elif "Рис.1.2.1" in figures_found:
            # Если Рис.1.2.1 есть, но нет "начальный курс" - удаляем его
            if not has_initial_course_phrase or has_initial_strike or not has_school_sources_in_llm:
                figures_found = [fig for fig in figures_found if fig != "Рис.1.2.1"]
                if "Рис.1.2.1" in course_selected_figures:
                    course_selected_figures.remove("Рис.1.2.1")
                if "Рис.1.2.1" in forced_figures:
                    forced_figures.remove("Рис.1.2.1")
                logger.info(f"ЖЕСТКАЯ ФИЛЬТРАЦИЯ: Рис.1.2.1 удален - нет 'начальный курс' в ответе")

    try:
        figure_scores: list[tuple[str, int, bool]] = []
        for fig in figures_found:
            try:
                fig_lower = fig.lower()
                explicit = fig_lower in user_q.lower() or (answer and fig_lower in answer.lower())
                score = 0
                if explicit:
                    score += 100
                if fig in course_selected_figures:
                    score += 100
                title = image_mapper.get_figure_title(fig)
                if title:
                    title_lower = title.lower()
                    score += sum(1 for kw in all_keywords if kw in title_lower)
                if score > 0:
                    figure_scores.append((fig, score, explicit))
            except Exception as fig_error:
                logger.warning(f"Ошибка при обработке рисунка {fig}: {fig_error}")
                continue
    except Exception as scoring_error:
        logger.warning(f"Ошибка при оценке рисунков: {scoring_error}")
        figure_scores = []

    filtered_figures: list[str] = []
    if figure_scores:
        max_score = max(score for _, score, _ in figure_scores)
        for fig, score, explicit in figure_scores:
            if explicit or score == max_score:
                filtered_figures.append(fig)

    if forced_figures:
        filtered_figures = _unique_preserving(list(forced_figures) + filtered_figures)

    filtered_figures = _unique_preserving(filtered_figures)
    if blocked_figures:
        filtered_figures = [fig for fig in filtered_figures if fig not in blocked_figures]

    image_intent_words = [
        "покажи", "покажите", "показать", "покажи-ка", "покаж",
        "изображение", "картинка", "рисунок", "рис.", "схема", "фото",
        "логотип", "логотип школы", "сертификат",
        "прикрепи", "прикрепить", "отправь", "покажи фото"
    ]
    has_image_intent = any(w in user_q.lower() for w in image_intent_words)
    has_explicit_fig_ref = bool(figures_in_question or figures_in_answer)

    training_keywords = {
        "курс", "начальный", "базовый", "экспресс", "абонемент",
        "тестирование", "тренинг", "тренинг-класс", "юниор", "мастер", "профи"
    }
    is_training_topic = any(k in user_q.lower() for k in training_keywords)
    try:
        if not is_training_topic:
            is_training_topic = any("1.2_Виды обучения" in (h.source or "") for h in used_hits)
    except Exception:
        pass
    has_cert_fig = any((image_mapper.get_figure_title(f) or "").lower().find("сертификат") >= 0 for f in filtered_figures)
    allow_auto_images = is_training_topic and has_cert_fig

    norm_q = re.sub(r"\s+", " ", user_q.lower()).strip()
    general_training_phrases = [
        "виды обуч", "программы обуч", "формы обуч", "типы обуч", "варианты обуч",
        "учебные программы", "предложения по обуч"
    ]
    has_general_training_phrase = any(p in norm_q for p in general_training_phrases)
    has_specific_course_marker = any(s in norm_q for s in [
        "начальн", "базов", "экспресс", "абонем", "тестирован", "тренинг",
        "к1", "к2", "к3", "а1", "а2", "а3", "т1"
    ])
    generic_training = has_general_training_phrase and not has_specific_course_marker

    if not (has_image_intent or has_explicit_fig_ref or allow_auto_images or course_figure_selected or forced_figures):
        filtered_figures = []
    if generic_training and not forced_figures:
        filtered_figures = []
    if purchase_inquiry and not (course_figure_selected or has_explicit_fig_ref or has_image_intent or forced_figures):
        filtered_figures = []

    # КРИТИЧЕСКАЯ ФИНАЛЬНАЯ ПРОВЕРКА: Если в ответе LLM есть фраза "начальный курс", показываем ТОЛЬКО Рис.1.2.1
    # Проверяем ТОЛЬКО в ответе LLM, не в запросе пользователя
    # Эта проверка должна быть ПОСЛЕ всех операций с рисунками, но ПЕРЕД финальной фильтрацией
    if answer and isinstance(answer, str):
        answer_lower = answer.lower()
        # Проверяем ТОЧНУЮ фразу "начальный курс" (регистронезависимо)
        has_initial_course_phrase = "начальный курс" in answer_lower

        if has_initial_course_phrase and has_school_sources_in_llm:
            # Проверяем, что нет признаков правил
            rules_indicators = ["начальный удар", "биток", "прицел", "шар", "луза", "пирамида", "правила игры", "штраф", "соударение"]
            has_rules = any(indicator in answer_lower for indicator in rules_indicators)

            if not has_rules:
                # КРИТИЧНО: Оставляем ТОЛЬКО Рис.1.2.1, удаляем ВСЕ остальные рисунки
                # Это должно происходить ПОСЛЕ всех операций с рисунками
                original_figures = filtered_figures.copy()
                filtered_figures = ["Рис.1.2.1"]
                logger.info(f"КРИТИЧЕСКАЯ ФИЛЬТРАЦИЯ: При наличии фразы 'начальный курс' в ответе LLM оставлен ТОЛЬКО Рис.1.2.1. Было: {original_figures}, стало: {filtered_figures}")

    if not answer or not isinstance(answer, str):
        answer = "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос."

    try:
        final_answer = answer.strip() if answer and isinstance(answer, str) else ""
        if not final_answer:
            final_answer = "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос."

        # Применяем функции обработки текста с защитой от ошибок
        # Глобальная защита строк с "—" теперь встроена в _format_llm_response_layout (объединение в шаге 0)
        # и _enhance_layout (защита маркерами)
        # Сначала обрабатываем основной текст сообщения
        processing_functions_main = [
            _bold_to_arrow,
            _format_pointers_and_bold,  # Форматирование "👉текст:" и "*текст*"
            _format_llm_response_layout,  # Форматирование ответа LLM: предложения с новой строки, специальные паттерны, объединение строк с "—"
            _normalize_arrows,
            _strip_unwanted_symbols,
            _enhance_layout,  # Защищает строки с "—" маркерами от дальнейших обработок
            _remove_lonely_emojis,
        ]
        
        # Затем обрабатываем блок CTA (в самом конце)
        processing_functions_cta = [
            _move_cta_to_end,  # Переносит CTA в конец
            _ensure_cta_spacing,  # Добавляет пустую строку перед CTA и гарантирует 🎯
            _normalize_cta_block,  # Нормализует блок CTA
        ]
        
        # Применяем обработку основного текста
        for func in processing_functions_main:
            try:
                final_answer = func(final_answer) if final_answer else ""
                if not final_answer:
                    break
            except Exception as func_error:
                logger.warning(f"Ошибка в функции {func.__name__}: {func_error}")
                continue
        
        # Применяем обработку CTA блока (в самом конце)
        for func in processing_functions_cta:
            try:
                final_answer = func(final_answer) if final_answer else ""
                if not final_answer:
                    break
            except Exception as func_error:
                logger.warning(f"Ошибка в функции {func.__name__}: {func_error}")
                continue

        for func in processing_functions:
            try:
                final_answer = func(final_answer) if final_answer else ""
                if not final_answer:
                    break
            except Exception as func_error:
                logger.warning(f"Ошибка в функции {func.__name__}: {func_error}")
                continue

        if not final_answer:
            final_answer = "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос."
    except Exception as text_error:
        logger.error(f"Ошибка при обработке текста ответа: {text_error}", exc_info=True)
        final_answer = "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос."

    if not purchase_inquiry and final_answer:
        try:
            sentences = _split_into_sentences(final_answer)
            filtered_sentences = [
                s for s in sentences
                if s and not re.search(r"покупк|предоплат|оплата производится|оформ", s, re.IGNORECASE)
            ]
            if filtered_sentences:
                final_answer = " ".join(filtered_sentences).strip()
                if final_answer:
                    try:
                        final_answer = _move_cta_to_end(final_answer)
                        final_answer = _ensure_cta_spacing(final_answer)
                        final_answer = _remove_lonely_emojis(final_answer)
                        final_answer = _normalize_cta_block(final_answer)
                    except Exception as post_error:
                        logger.warning(f"Ошибка при пост-обработке предложений: {post_error}")
        except Exception as sent_error:
            logger.warning(f"Ошибка при обработке предложений: {sent_error}")
    elif purchase_inquiry:
        try:
            replacements = [
                (r"\bДополнительные занятия\b", "Отдельные занятия"),
                (r"\bдополнительные занятия\b", "Отдельные занятия"),
                (r"\bДополнительные уроки\b", "Отдельные уроки"),
                (r"\bдополнительные уроки\b", "Отдельные уроки"),
                (r"\bДополнительное обучение\b", "Отдельные занятия"),
                (r"\bдополнительное обучение\b", "Отдельные занятия"),
            ]
            for pat, repl in replacements:
                final_answer = re.sub(pat, repl, final_answer)
        except Exception:
            pass
        finally:
            final_answer = _move_cta_to_end(final_answer)
            final_answer = _ensure_cta_spacing(final_answer)
            final_answer = _remove_lonely_emojis(final_answer)
            final_answer = _normalize_cta_block(final_answer)

    # Финальная проверка: если в LLM были отправлены документы из раздела "О школе", полностью блокируем кнопку
    # НО только если запрос НЕ относится к правилам (rule_query=False)
    # Если запрос относится к правилам (rule_query=True), кнопка должна показываться независимо от наличия документов "О школе"
    if has_school_sources_in_llm and not rule_query:
        allow_rule_button = False
        primary_sources = []
        logger.info(f"Финальная блокировка: обнаружены документы из раздела 'О школе' в контексте для LLM (rule_query=False)")

    # ЖЕСТКОЕ ОГРАНИЧЕНИЕ: stored_primary_sources сохраняется ТОЛЬКО если allow_rule_button = True
    # Это гарантирует, что кнопка не показывается, если первоисточники не разрешены
    stored_primary_sources = primary_sources if (allow_rule_button and primary_sources) else []
    logger.info(f"Финальная проверка перед показом кнопки: allow_rule_button={allow_rule_button}, primary_sources count={len(primary_sources)}, stored_primary_sources count={len(stored_primary_sources)}")

    # Убеждаемся, что фрагменты сериализуемы (преобразуем в словари, если нужно)
    # И ТОЛЬКО если allow_rule_button = True
    if stored_primary_sources and allow_rule_button:
        serializable_sources = []
        for frag in stored_primary_sources:
            if isinstance(frag, dict):
                serializable_sources.append(frag)
            else:
                # Если фрагмент не словарь, пытаемся преобразовать
                try:
                    serializable_sources.append(dict(frag) if hasattr(frag, '__dict__') else frag)
                except:
                    logger.warning(f"Не удалось сериализовать фрагмент: {frag}")
        stored_primary_sources = serializable_sources
        logger.info(f"Фрагменты подготовлены для сериализации: count={len(stored_primary_sources)}")

    try:
        # Сохраняем в state если allow_rule_button = True
        # Для rule_query=True и наличия источников в fragment_sources разрешаем кнопку даже если фрагменты не найдены
        # (фрагменты будут найдены при нажатии на кнопку)
        if allow_rule_button:
            # Если есть stored_primary_sources - сохраняем их
            # Если stored_primary_sources пуст, но rule_query=True и есть fragment_sources - все равно разрешаем
            # Сохраняем hits в сериализуемом формате для использования при нажатии на кнопку
            hits_serializable = []
            for h in hits[:5]:
                if hasattr(h, 'text') and hasattr(h, 'source'):
                    hits_serializable.append({
                        "text": h.text,
                        "source": h.source,
                        "score": getattr(h, 'score', 0.0),
                        "title": getattr(h, 'title', ""),
                        "figures": getattr(h, 'figures', ""),
                        "section": getattr(h, 'section', "")
                    })

            if stored_primary_sources:
                await state.update_data(
                    primary_sources=stored_primary_sources,
                    primary_source_index=0,
                    primary_source_main_source=main_source,
                    primary_source_is_rules=True,
                    primary_source_hits=hits_serializable,  # Сохраняем hits для повторного поиска
                )
                logger.info(f"State обновлен: primary_sources count={len(stored_primary_sources)}, primary_source_is_rules=True, main_source={main_source}")
            elif rule_query and fragment_sources and any(src in RULE_PRIMARY_ALLOWED_SOURCES for src in fragment_sources):
                # Для rule_query=True разрешаем кнопку даже без фрагментов (они будут найдены при нажатии)
                await state.update_data(
                    primary_sources=[],
                    primary_source_index=0,
                    primary_source_main_source=main_source or (list(fragment_sources)[0] if fragment_sources else None),
                    primary_source_is_rules=True,
                    primary_source_hits=hits_serializable,  # Сохраняем hits для повторного поиска
                )
                logger.info(f"State обновлен для rule_query=True: primary_source_is_rules=True, main_source={main_source or (list(fragment_sources)[0] if fragment_sources else None)}, fragment_sources={fragment_sources}")
            else:
                # Если первоисточники не разрешены, очищаем state
                await state.update_data(
                    primary_sources=[],
                    primary_source_index=0,
                    primary_source_main_source=None,
                    primary_source_is_rules=False,
                )
                logger.info(f"State очищен: allow_rule_button={allow_rule_button}, stored_primary_sources count={len(stored_primary_sources) if stored_primary_sources else 0}, rule_query={rule_query}")
        else:
            # Если первоисточники не разрешены, очищаем state
            await state.update_data(
                primary_sources=[],
                primary_source_index=0,
                primary_source_main_source=None,
                primary_source_is_rules=False,
            )
            logger.info(f"State очищен: allow_rule_button={allow_rule_button}, stored_primary_sources count={len(stored_primary_sources) if stored_primary_sources else 0}")
    except Exception as state_error:
        logger.warning(f"Не удалось обновить state для первоисточника: {state_error}", exc_info=True)

    # Проверяем ответ LLM на наличие стоп-слов
    # Если в ответе есть стоп-слова, кнопка "Первоисточник" не показывается
    llm_response_blocked = False
    critical_llm_response_blocked = False
    if final_answer and isinstance(final_answer, str):
        final_answer_lower = final_answer.lower()
        llm_response_blocked = any(stop_word in final_answer_lower for stop_word in STOP_WORDS_IN_LLM_RESPONSE)
        if llm_response_blocked:
            logger.info(f"Кнопка 'Первоисточник' заблокирована из-за стоп-слов в ответе LLM")

        # КРИТИЧЕСКАЯ ПРОВЕРКА: жесткая блокировка для критических стоп-слов
        # Эти слова блокируют кнопку даже для правил (rule_query=True)
        critical_llm_response_blocked = any(critical_word in final_answer_lower for critical_word in CRITICAL_STOP_WORDS_IN_LLM_RESPONSE)
        if critical_llm_response_blocked:
            logger.info(f"КРИТИЧЕСКАЯ БЛОКИРОВКА: Кнопка 'Первоисточник' жестко заблокирована из-за критических стоп-слов ('затрудн' или 'извин') в ответе LLM")

    reply_markup = None
    # КРИТИЧЕСКАЯ ПРОВЕРКА: Если запрос был исключен - кнопка НИКОГДА не показывается
    # Проверяем еще раз на всякий случай (переменная is_excluded_query должна быть доступна здесь)
    # Если запрос содержит критические исключенные паттерны - блокируем
    user_q_lower_check = user_q.lower() if user_q else ""
    critical_excluded_check = ["ты кто", "кто ты"]
    is_critically_excluded = any(pattern in user_q_lower_check for pattern in critical_excluded_check)

    # Кнопка показывается если:
    # 0. Запрос НЕ исключен (критическая проверка)
    # 0.5. НЕТ критических стоп-слов в ответе LLM (жесткая блокировка, даже для правил)
    # 1. allow_rule_button = True (первоисточники разрешены)
    # 2. Нет стоп-слов в ответе LLM (НО для правил это не блокирует кнопку, если нет критических)
    # 3. И (stored_primary_sources не пуст ИЛИ rule_query=True с fragment_sources из правил)
    # Для правил (rule_query=True) игнорируем обычную блокировку из-за стоп-слов, НО критическая блокировка применяется всегда
    should_show_button = (
        not is_critically_excluded and
        not critical_llm_response_blocked and
        allow_rule_button and (
            (not llm_response_blocked or rule_query) and (
                stored_primary_sources or
                (rule_query and fragment_sources and any(src in RULE_PRIMARY_ALLOWED_SOURCES for src in fragment_sources))
            )
        )
    )

    if is_critically_excluded:
        logger.info(f"КРИТИЧЕСКАЯ БЛОКИРОВКА КНОПКИ: Запрос '{user_q}' содержит критический исключенный паттерн - кнопка НЕ будет показана")

    if critical_llm_response_blocked:
        logger.info(f"КРИТИЧЕСКАЯ БЛОКИРОВКА КНОПКИ: Ответ LLM содержит критические стоп-слова ('затрудн' или 'извин') - кнопка НЕ будет показана, даже для правил")

    if should_show_button:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📄 Первоисточник", callback_data="primary_source:open")]]
        )
        logger.info(f"Кнопка 'Первоисточник' будет показана: stored_primary_sources count={len(stored_primary_sources) if stored_primary_sources else 0}, allow_rule_button={allow_rule_button}, rule_query={rule_query}, fragment_sources={fragment_sources}")
    else:
        logger.info(f"Кнопка 'Первоисточник' НЕ будет показана: stored_primary_sources count={len(stored_primary_sources) if stored_primary_sources else 0}, allow_rule_button={allow_rule_button}, llm_response_blocked={llm_response_blocked}, rule_query={rule_query}, fragment_sources={fragment_sources}")

    try:
        await save_chat_message(user_id, "assistant", final_answer)
    except Exception as save_error:
        logger.warning(f"Не удалось сохранить сообщение в историю: {save_error}")

    # Проверка Фазы 4: если имя и телефон не получены, выводим сообщение
    if current_phase == 4 and data.get("phase4_check_contacts"):
        profile_check = await get_user_profile(user_id)
        if profile_check:
            has_name = bool(profile_check.name and profile_check.name.strip())
            has_phone = bool(profile_check.phone and profile_check.phone.strip())

            if not has_name or not has_phone:
                await _answer_with_sticker_cleanup(message, "😕 Жаль! Я готов продолжать отвечать на Ваши вопросы.", waiting_sticker_message)
                await save_chat_message(user_id, "assistant", "😕 Жаль! Я готов продолжать отвечать на Ваши вопросы.")
                await state.update_data(phase=1, phase4_check_contacts=False, phase4_no_contacts_shown=False)
                logger.info(f"Имя и/или телефон не получены для пользователя {user_id}, возврат к Фазе 1")

    try:
        if not final_answer or not isinstance(final_answer, str):
            final_answer = "⚠️ Затрудняюсь ответить. Переформулируйте Ваш запрос."

        # Telegram имеет лимит 4096 символов на сообщение
        MAX_MESSAGE_LENGTH = 4096

        if len(final_answer) <= MAX_MESSAGE_LENGTH:
            # Сообщение короткое, отправляем как есть
            await _answer_with_sticker_cleanup(message, final_answer, waiting_sticker_message, reply_markup=reply_markup)
            logger.info(f"Ответ отправлен пользователю {user_id}")
        else:
            # Сообщение длинное, разбиваем на части
            # Разбиваем по предложениям, чтобы не резать текст посередине
            sentences = _split_into_sentences(final_answer)
            parts = []
            current_part = ""

            for sentence in sentences:
                # Если само предложение длиннее лимита, разбиваем его по словам
                if len(sentence) > MAX_MESSAGE_LENGTH:
                    # Сначала сохраняем текущую часть, если она есть
                    if current_part:
                        parts.append(current_part.strip())
                        current_part = ""

                    # Разбиваем длинное предложение по словам
                    words = sentence.split()
                    for word in words:
                        if len(current_part) + len(word) + 1 <= MAX_MESSAGE_LENGTH:
                            current_part += (word + " " if current_part else word)
                        else:
                            if current_part:
                                parts.append(current_part.strip())
                            current_part = word
                # Если добавление предложения не превышает лимит
                elif len(current_part) + len(sentence) + 1 <= MAX_MESSAGE_LENGTH:
                    current_part += (sentence + " " if current_part else sentence)
                else:
                    # Сохраняем текущую часть и начинаем новую
                    if current_part:
                        parts.append(current_part.strip())
                    current_part = sentence

            # Добавляем последнюю часть
            if current_part:
                parts.append(current_part.strip())

            # Отправляем все части, клавиатуру прикрепляем только к последнему сообщению
            # Стикер удаляем после первого сообщения
            for i, part in enumerate(parts):
                is_last = (i == len(parts) - 1)
                if i == 0:
                    # Удаляем стикер после первого сообщения
                    await _answer_with_sticker_cleanup(message, part, waiting_sticker_message, reply_markup=reply_markup if is_last else None)
                else:
                    await message.answer(part, reply_markup=reply_markup if is_last else None)

            logger.info(f"Ответ отправлен пользователю {user_id} ({len(parts)} частей)")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа: {e}", exc_info=True)
        raise

    # АБСОЛЮТНАЯ ФИНАЛЬНАЯ ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ: Если в ответе LLM есть "начальный курс", показываем ТОЛЬКО Рис.1.2.1
    # Это последняя проверка, которая гарантирует правильный результат независимо от всех предыдущих операций
    # Проверяем ТОЛЬКО в ответе LLM (переменная answer), НЕ в запросе пользователя
    if answer and isinstance(answer, str):
        answer_lower = answer.lower()
        has_initial_course_phrase = "начальный курс" in answer_lower

        logger.info(f"🔍 ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ: answer содержит 'начальный курс'? {has_initial_course_phrase}, has_school_sources_in_llm={has_school_sources_in_llm}, filtered_figures={filtered_figures}")
        logger.info(f"🔍 ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ: answer (первые 200 символов): {answer[:200]}")

        if has_initial_course_phrase and has_school_sources_in_llm:
            rules_indicators = ["начальный удар", "биток", "прицел", "шар", "луза", "пирамида", "правила игры", "штраф", "соударение"]
            has_rules = any(indicator in answer_lower for indicator in rules_indicators)

            logger.info(f"🔍 ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ: has_rules={has_rules}")

            if not has_rules:
                # АБСОЛЮТНО: Оставляем ТОЛЬКО Рис.1.2.1, удаляем ВСЕ остальные
                # Это последняя проверка перед отправкой, она переопределяет все предыдущие операции
                original_figures = filtered_figures.copy()
                filtered_figures = ["Рис.1.2.1"]
                logger.info(f"✅✅✅ АБСОЛЮТНАЯ ФИЛЬТРАЦИЯ ПЕРЕД ОТПРАВКОЙ: При наличии 'начальный курс' в ответе LLM оставлен ТОЛЬКО Рис.1.2.1. Было: {original_figures}, стало: {filtered_figures}")
            else:
                logger.info(f"⚠️ ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ: 'начальный курс' найден, но есть признаки правил, Рис.1.2.1 не показывается")
        elif has_initial_course_phrase and not has_school_sources_in_llm:
            logger.info(f"⚠️ ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ: 'начальный курс' найден в ответе, но has_school_sources_in_llm=False, Рис.1.2.1 не показывается")
        else:
            logger.info(f"ℹ️ ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ: 'начальный курс' НЕ найден в ответе LLM, filtered_figures={filtered_figures}")

    images_sent = []

    for fig_key in filtered_figures:
        img_path = image_mapper.get_image_path_for_figure(fig_key)
        if img_path and img_path not in images_sent:
            try:
                photo = FSInputFile(img_path)
                title = image_mapper.get_figure_title(fig_key)
                if title:
                    caption = f"{title} {fig_key}."
                else:
                    caption = f"{fig_key}."
                await message.answer_photo(photo=photo, caption=caption)
                images_sent.append(img_path)
                logger.info(f"Отправлен рисунок {fig_key} пользователю {user_id}")
            except Exception as e:
                logger.warning(f"Не удалось отправить изображение {fig_key}: {e}")
                pass

# Функции истории чата перенесены в db/chat_history.py


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Обработка команды /cancel - нормализация состояния и возврат к Фазе 1"""
    logger = logging.getLogger(__name__)
    user_id = message.from_user.id if message.from_user else 0
    logger.info(f"Получена команда /cancel от пользователя {user_id}")

    try:
        await _normalize_state(state, user_id)
        cancel_message = "▶️ Я готов к Вашим вопросам."
        await message.answer(cancel_message, parse_mode=ParseMode.HTML)
        if message.from_user:
            await save_chat_message(message.from_user.id, "assistant", cancel_message)
        logger.info(f"Команда /cancel обработана для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при обработке /cancel: {e}", exc_info=True)
        try:
            await message.answer("⚠️ Произошла ошибка при обработке команды.")
        except:
            pass


@router.message(lambda m: m.text and not m.text.startswith("/") and m.text != "📝 Запись на обучение")
async def handle_faq(message: Message, state: FSMContext) -> None:
    logger = logging.getLogger(__name__)

    current_state = await state.get_state()
    if current_state and current_state.startswith("BookingStates"):
        logger.debug(f"Пропускаем FAQ обработку - пользователь в состоянии {current_state}")
        return

    if not message.text or message.text.startswith("/"):
        return

    if message.text == "📝 Запись на обучение":
        return

    user_text = message.text
    if user_text.startswith("📚 "):
        user_text = user_text[2:].strip()
    elif user_text.startswith("🔥 "):
        user_text = user_text[2:].strip()

    logger.info(
        f"Получено сообщение для FAQ: '{user_text[:50]}' от пользователя {message.from_user.id if message.from_user else 'unknown'}"
    )

    # Проверяем текущую фазу - для фаз 2, 3 и 4 не отправляем стикер ожидания
    state_data = await state.get_data()
    current_phase = state_data.get("phase", 1)

    # Отправляем стикер ожидания только для Фазы 1
    waiting_sticker_message = None
    if current_phase == 1:
        waiting_sticker_message = await _send_waiting_sticker(message)
    else:
        logger.info(f"Стикер ожидания не отправляется для Фазы {current_phase}")

    try:
        await _process_faq_query(message, state, user_text, input_mode="text", waiting_sticker_message=waiting_sticker_message)
    except Exception as e:
        logger.error(f"Ошибка при обработке FAQ: {e}", exc_info=True)
        try:
            await message.answer("⚠️ Однако, произошел системный сбой. Повторите Ваш запрос/ответ.")
        except Exception:
            pass


@router.message(F.voice)
async def handle_voice_message(message: Message, state: FSMContext) -> None:
    logger = logging.getLogger(__name__)

    current_state = await state.get_state()
    if current_state and current_state.startswith("BookingStates"):
        logger.debug(f"Пропускаем FAQ обработку голосового сообщения - состояние {current_state}")
        return

    # Проверяем текущую фазу - для фаз 2, 3 и 4 не отправляем стикер ожидания
    state_data = await state.get_data()
    current_phase = state_data.get("phase", 1)

    # Отправляем стикер ожидания только для Фазы 1
    waiting_sticker_message = None
    if current_phase == 1:
        waiting_sticker_message = await _send_waiting_sticker(message)
    else:
        logger.info(f"Стикер ожидания не отправляется для Фазы {current_phase}")

    temp_path: str | None = None
    converted_path: str | None = None
    transcript: str = ""
    try:
        # Используем /tmp в Docker контейнере, если доступен, иначе системную временную директорию
        temp_dir = os.getenv("TMPDIR", os.getenv("TEMP", tempfile.gettempdir()))
        # Создаем директорию, если её нет
        os.makedirs(temp_dir, exist_ok=True)

        # Скачиваем голосовое сообщение в .oga формате
        with tempfile.NamedTemporaryFile(delete=False, suffix=".oga", dir=temp_dir) as tmp:
            await message.bot.download(message.voice, destination=tmp.name)
            temp_path = tmp.name

        logger.info(f"Голосовое сообщение скачано: {temp_path}, размер: {os.path.getsize(temp_path) if os.path.exists(temp_path) else 0} байт")

        # Конвертируем .oga в .wav через ffmpeg (faster-whisper лучше работает с .wav)
        import subprocess
        converted_path = temp_path.replace(".oga", ".wav")

        logger.info(f"Конвертация .oga в .wav: {converted_path}")
        try:
            # Конвертируем через ffmpeg
            subprocess.run(
                ["ffmpeg", "-i", temp_path, "-y", "-ar", "16000", "-ac", "1", "-f", "wav", converted_path],
                check=True,
                capture_output=True,
                timeout=30
            )
            logger.info(f"Конвертация завершена успешно: {converted_path}")

            # Используем сконвертированный файл для транскрибации
            audio_file = converted_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка конвертации через ffmpeg: {e.stderr.decode() if e.stderr else str(e)}")
            # Пытаемся использовать оригинальный файл
            audio_file = temp_path
            logger.warning("Используем оригинальный .oga файл (может не работать)")
        except FileNotFoundError:
            logger.warning("ffmpeg не найден, используем оригинальный файл")
            audio_file = temp_path
        except Exception as e:
            logger.error(f"Неожиданная ошибка при конвертации: {e}", exc_info=True)
            audio_file = temp_path

        logger.info(f"Начало транскрибации голосового файла: {audio_file}")
        transcript = await transcribe_file(audio_file)
        logger.info(f"Транскрибация завершена успешно, результат: '{transcript[:100] if transcript else 'ПУСТО'}'...")
    except ImportError as e:
        logger.error(f"STT недоступно: {e}", exc_info=True)
        # Удаляем стикер ожидания при ошибке
        if waiting_sticker_message:
            try:
                await waiting_sticker_message.delete()
            except Exception:
                pass
        await message.answer(
            "Для распознавания речи нужна локальная модель Whisper. Установите 'faster-whisper' и ffmpeg, затем попробуйте снова."
        )
        return
    except Exception as e:
        logger.error(f"Ошибка транскрибации голосового сообщения: {e}", exc_info=True)
        logger.error(f"Путь к временному файлу: {temp_path}, существует: {os.path.exists(temp_path) if temp_path else 'N/A'}")
        logger.error(f"Путь к сконвертированному файлу: {converted_path}, существует: {os.path.exists(converted_path) if converted_path else 'N/A'}")
        logger.error(f"TMPDIR: {os.getenv('TMPDIR')}, TEMP: {os.getenv('TEMP')}, tempfile.gettempdir(): {tempfile.gettempdir()}")
        await _answer_with_sticker_cleanup(message, "Не удалось распознать голос. Попробуйте ещё раз или задайте вопрос текстом.", waiting_sticker_message)
        return
    finally:
        # Удаляем временные файлы
        for file_path in [temp_path, converted_path]:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Удален временный файл: {file_path}")
                except OSError as e:
                    logger.warning(f"Не удалось удалить временный файл {file_path}: {e}")

    transcript = (transcript or "").strip()
    if not transcript:
        await _answer_with_sticker_cleanup(message, "Не удалось распознать голос. Попробуйте ещё раз.", waiting_sticker_message)
        return

    # Удаляем стикер ожидания после появления расшифрованной фразы
    if waiting_sticker_message:
        try:
            await waiting_sticker_message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить стикер ожидания: {e}")

    logger.info(
        f"Получено голосовое сообщение от пользователя {message.from_user.id if message.from_user else 'unknown'}: '{transcript[:50]}'"
    )

    # Показываем распознанный текст пользователю перед обработкой
    # Убираем знаки препинания и делаем первую букву маленькой
    # Оставляем только буквы, цифры и пробелы
    cleaned_transcript = ''.join(c for c in transcript if c.isalnum() or c.isspace()).strip()
    if cleaned_transcript:
        cleaned_transcript = cleaned_transcript[0].lower() + cleaned_transcript[1:] if len(cleaned_transcript) > 1 else cleaned_transcript.lower()
    # Отправляем расшифровку голоса - это текстовое сообщение, поэтому удаляем стикер ожидания
    transcript_message = await message.answer(f"🎤 {cleaned_transcript}")
    await _delete_waiting_sticker(waiting_sticker_message)

    # Проверяем текущую фазу - для фаз 2, 3 и 4 не отправляем стикер ожидания
    state_data_voice = await state.get_data()
    current_phase_voice = state_data_voice.get("phase", 1)

    # Отправляем стикер ожидания только для Фазы 1
    waiting_sticker_message = None
    if current_phase_voice == 1:
        waiting_sticker_message = await _send_waiting_sticker(transcript_message)
    else:
        logger.info(f"Стикер ожидания не отправляется для Фазы {current_phase_voice}")

    await _process_faq_query(message, state, transcript, input_mode="voice", waiting_sticker_message=waiting_sticker_message)


@router.callback_query(F.data.startswith("intent:"))
async def handle_intent_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора намерения из окна выбора"""
    logger = logging.getLogger(__name__)

    # Проверяем наличие пользователя и сообщения
    if not callback.from_user:
        logger.error("callback.from_user is None")
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    if not callback.message:
        logger.error("callback.message is None")
        await callback.answer("Ошибка: сообщение не найдено", show_alert=True)
        return

    user_id = callback.from_user.id
    intent_type = callback.data.split(":")[1] if ":" in callback.data else ""

    # Оставляем сообщение с окном выбора в чате (не удаляем)

    try:
        if intent_type == "training":
            # Пользователь выбрал "Обучение"
            user_intent = "Обучение"
            status = "Обучение"
            # Получаем name_sys из callback
            name_sys = ""
            if callback.from_user:
                if callback.from_user.first_name:
                    name_sys = callback.from_user.first_name
                elif callback.from_user.username:
                    name_sys = callback.from_user.username
            # Получаем профиль для проверки name_sys
            profile = await get_user_profile(user_id)
            if profile and not profile.name_sys and name_sys:
                await update_user_profile(tg_user_id=user_id, status=status, name_sys=name_sys)
            else:
                await update_user_profile(tg_user_id=user_id, status=status)
            await callback.answer("Выбрано: Обучение")
            logger.info(f"Пользователь {user_id} выбрал Обучение")

            # Сбрасываем флаг окна выбора намерения, так как выбор сделан
            await state.update_data(intent_selection_shown=False)

            # Показываем окно политики (waiting_sticker_message не нужен, так как это callback)
            await show_policy_window(callback.message, state, user_intent, None)

        elif intent_type == "consultation":
            # Пользователь выбрал "Консультация"
            user_intent = "Консультация"
            status = "Консультация"
            # Получаем name_sys из callback
            name_sys = ""
            if callback.from_user:
                if callback.from_user.first_name:
                    name_sys = callback.from_user.first_name
                elif callback.from_user.username:
                    name_sys = callback.from_user.username
            # Получаем профиль для проверки name_sys
            profile = await get_user_profile(user_id)
            if profile and not profile.name_sys and name_sys:
                await update_user_profile(tg_user_id=user_id, status=status, name_sys=name_sys)
            else:
                await update_user_profile(tg_user_id=user_id, status=status)
            await callback.answer("Выбрано: Консультация")
            logger.info(f"Пользователь {user_id} выбрал Консультация")

            # Сбрасываем флаг окна выбора намерения, так как выбор сделан
            await state.update_data(intent_selection_shown=False)

            # Показываем окно политики (waiting_sticker_message не нужен, так как это callback)
            await show_policy_window(callback.message, state, user_intent, None)

        elif intent_type == "continue":
            # Пользователь выбрал "Продолжить" - возвращаемся к Фазе 1
            await callback.answer("Продолжаем общение")
            logger.info(f"Пользователь {user_id} выбрал Продолжить - возврат к Фазе 1")

            # Явно устанавливаем фазу в 1 и сбрасываем все флаги
            await state.update_data(
                phase=1,
                intent_selection_shown=False,
                original_query_for_continue="",
                anketa_started=False,
                anketa_question=None,
                continue_button_pressed=False,
            )

            # Отправляем сообщение о готовности к вопросам
            if callback.message:
                try:
                    await callback.message.answer("▶️ Я готов к Вашим вопросам.")
                    if callback.from_user:
                        await save_chat_message(callback.from_user.id, "assistant", "▶️ Я готов к Вашим вопросам.")
                except Exception as e:
                    logger.error(f"Ошибка при отправке сообщения о готовности: {e}")
        else:
            logger.warning(f"Неизвестный тип намерения: {intent_type}")
            await callback.answer("Ошибка: неизвестный выбор", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка при обработке выбора намерения: {e}", exc_info=True)
        await callback.answer("⚠️ Произошла ошибка. Попробуйте еще раз.", show_alert=True)


@router.callback_query(F.data == "primary_source:open")
async def handle_primary_source_open(callback: CallbackQuery, state: FSMContext) -> None:
    logger = logging.getLogger(__name__)
    data = await state.get_data()
    fragments = data.get("primary_sources") or []
    primary_source_is_rules = data.get("primary_source_is_rules", False)
    logger.info(f"Открытие первоисточника: fragments count={len(fragments)}, primary_source_is_rules={primary_source_is_rules}, data keys={list(data.keys())}")

    # Проверяем, что первоисточники разрешены
    if not primary_source_is_rules:
        logger.warning(f"Первоисточники не разрешены для этого запроса (primary_source_is_rules=False)")
        await callback.answer("Первоисточник недоступен для этого запроса.", show_alert=True)
        return

    # Если фрагменты не найдены, но primary_source_is_rules=True, пытаемся найти их заново
    if not fragments:
        main_source = data.get("primary_source_main_source")
        if main_source and main_source in RULE_PRIMARY_ALLOWED_SOURCES:
            # Пытаемся найти фрагменты для источника
            logger.info(f"Фрагменты не найдены в state, пытаемся найти для источника: {main_source}")
            # Получаем последний запрос пользователя из истории
            user_id = callback.from_user.id if callback.from_user else 0
            chat_history = await get_chat_history(user_id, limit=5)
            if chat_history:
                # Берем последний запрос пользователя
                last_user_message = next((msg for msg in reversed(chat_history) if msg["role"] == "user"), None)
                if last_user_message:
                    user_query = last_user_message.get("content", "")
                    # Ищем фрагменты для этого запроса
                    try:
                        # Получаем hits из state, если они сохранены, иначе делаем новый поиск
                        saved_hits_data = data.get("primary_source_hits")
                        search_hits = []
                        if saved_hits_data:
                            # Восстанавливаем hits из сохраненных данных
                            from ..knowledge.text_search import SearchHit
                            for hit_data in saved_hits_data:
                                if isinstance(hit_data, dict):
                                    search_hits.append(SearchHit(
                                        text=hit_data.get("text", ""),
                                        source=hit_data.get("source", ""),
                                        score=hit_data.get("score", 0.0),
                                        title=hit_data.get("title", ""),
                                        figures=hit_data.get("figures", ""),
                                        section=hit_data.get("section", "")
                                    ))

                        if not search_hits:
                            # Если hits не сохранены, делаем новый поиск
                            from ..knowledge import search_store as kb_search
                            search_results = kb_search.search(user_query, limit=5)
                            search_hits = search_results if search_results else []

                        fragments = search_store.get_primary_source_fragments(
                            search_hits,
                            user_query,
                            allowed_sources=[main_source],
                        )
                        if fragments:
                            await state.update_data(primary_sources=fragments, primary_source_index=0)
                            logger.info(f"Найдено фрагментов при повторном поиске: {len(fragments)}")
                        else:
                            logger.warning(f"Фрагменты не найдены для источника {main_source} и запроса '{user_query[:50]}'")
                            await callback.answer("Фрагменты не найдены для этого запроса.", show_alert=True)
                            return
                    except Exception as e:
                        logger.error(f"Ошибка при поиске фрагментов: {e}", exc_info=True)
                        await callback.answer("Ошибка при поиске фрагментов.", show_alert=True)
                        return
                else:
                    logger.warning(f"Не найден последний запрос пользователя в истории")
                    await callback.answer("Фрагменты не найдены для этого запроса.", show_alert=True)
                    return
            else:
                logger.warning(f"История чата пуста для пользователя {user_id}")
                await callback.answer("Фрагменты не найдены для этого запроса.", show_alert=True)
                return
        else:
            logger.warning(f"Фрагменты не найдены в state для открытия первоисточника. data keys: {list(data.keys())}")
            await callback.answer("Первоисточник недоступен для этого запроса.", show_alert=True)
            return

    # Убеждаемся, что у нас есть фрагменты
    if not fragments or len(fragments) == 0:
        logger.warning(f"Фрагменты пусты после повторного поиска")
        await callback.answer("Фрагменты не найдены для этого запроса.", show_alert=True)
        return

    fragment = fragments[0]
    main_source = data.get("primary_source_main_source")
    fragment_source = fragment.get("source") if isinstance(fragment, dict) else None
    resolved_source = fragment_source or main_source
    download_info = _get_download_info_for_source(resolved_source) if resolved_source else None

    try:
        text = _format_primary_source_fragment(fragment, 0, len(fragments), download_info)
    except Exception as format_error:
        logger.error(f"Ошибка при форматировании фрагмента: {format_error}", exc_info=True)
        await callback.answer("Ошибка при форматировании фрагмента.", show_alert=True)
        return

    markup = _build_primary_source_markup(0, len(fragments), download_info)

    await state.update_data(primary_source_index=0, primary_source_figure_messages=[])
    try:
        sent_message = await callback.message.answer(text, reply_markup=markup, parse_mode='HTML')
        await callback.answer()
    except Exception as send_error:
        logger.error(f"Ошибка при отправке сообщения с первоисточником: {send_error}", exc_info=True)
        await callback.answer("Ошибка при отправке сообщения.", show_alert=True)
        return

    # Отправляем рисунки, если они есть для этого фрагмента
    figure_message_ids = []
    try:
        figures_to_send = _get_figures_for_fragment(fragment, main_source)
        for fig_key in figures_to_send:
            img_path = image_mapper.get_image_path_for_figure(fig_key)
            if img_path:
                try:
                    photo = FSInputFile(img_path)
                    title = image_mapper.get_figure_title(fig_key)
                    if title:
                        caption = f"{title} {fig_key}."
                    else:
                        caption = f"{fig_key}."
                    fig_message = await sent_message.answer_photo(photo=photo, caption=caption)
                    if fig_message and fig_message.message_id:
                        figure_message_ids.append(fig_message.message_id)
                except Exception as img_error:
                    logger.warning(f"Не удалось отправить изображение {fig_key}: {img_error}")
        await state.update_data(primary_source_figure_messages=figure_message_ids)
    except Exception as fig_error:
        logger.warning(f"Ошибка при определении рисунков для фрагмента: {fig_error}")


@router.callback_query(F.data.startswith("phase4:"))
async def handle_phase4_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка кнопок Фазы 4 (Запись)"""
    logger = logging.getLogger(__name__)

    if not callback.from_user:
        logger.error("callback.from_user is None")
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    if not callback.message:
        logger.error("callback.message is None")
        await callback.answer("Ошибка: сообщение не найдено", show_alert=True)
        return

    user_id = callback.from_user.id
    button_type = callback.data.split(":")[1] if ":" in callback.data else ""

    # Оставляем сообщение с окном в чате (не удаляем)

    try:
        if button_type == "self":
            # Кнопка "📞 САМ"
            # Проверяем, изменился ли статус (сравниваем с сохраненным старым статусом)
            state_data = await state.get_data()
            old_status = state_data.get("old_status_before_intent", "")
            profile = await get_user_profile(user_id)
            current_status = (profile.status or "").strip() if profile else ""

            # Статус изменился, если он отличается от старого или если старый был пустым/Читатель
            is_lead_status = current_status in ("Обучение", "Консультация")
            status_changed = (
                current_status != old_status or
                (old_status in ("", "Читатель") and is_lead_status)
            )

            # Если статус изменился - сохраняем в Excel
            if status_changed and is_lead_status:
                try:
                    from ..db.leads_excel import save_lead_to_excel
                    logger.info(f"🔄 Сохранение в Excel для пользователя {user_id} (Сам, статус изменился): old='{old_status}' -> new='{current_status}'")
                    await save_lead_to_excel(profile, profile.name_sys or "" if profile else "")
                    logger.info(f"✅ Данные лида сохранены в Excel: статус='{current_status}'")
                except Exception as e:
                    logger.error(f"❌ Ошибка при сохранении в Excel: {e}", exc_info=True)

            await state.update_data(phase=1, phase4_window_shown=False, phase4_state=None)
            message_text = "👌<b>Прекрасно, ждём Вашего звонка!</b>\n... а я - весь внимание, готов к Вашим вопросам! ▶️"
            await callback.message.answer(message_text, parse_mode=ParseMode.HTML)
            await save_chat_message(user_id, "assistant", message_text)
            await callback.answer()
            logger.info(f"Пользователь {user_id} выбрал самостоятельную запись, status_changed={status_changed}")

        elif button_type == "contacts":
            # Кнопка "👨‍🎓 КОНТАКТЫ"
            await state.update_data(phase4_state="waiting_name", phase4_window_shown=False)
            name_message = "👍 Давайте знакомиться.\n<b>Ваше Имя?</b>\n(как к Вам обращаться)"
            await callback.message.answer(name_message, parse_mode=ParseMode.HTML)
            await save_chat_message(user_id, "assistant", name_message)
            await callback.answer()
            logger.info(f"Пользователь {user_id} выбрал оставить контакты")

        elif button_type == "cancel":
            # Кнопка "❌ Отмена"
            # Получаем список нерелевантных сообщений для удаления
            state_data = await state.get_data()
            invalid_messages = state_data.get("phase4_invalid_messages", [])

            # Удаляем нерелевантные сообщения (включая ответы бота) перед отменой
            if invalid_messages and callback.message and callback.message.chat:
                for msg_id in invalid_messages:
                    try:
                        await callback.message.bot.delete_message(
                            chat_id=callback.message.chat.id,
                            message_id=msg_id
                        )
                        logger.info(f"Удалено нерелевантное сообщение {msg_id} при отмене для пользователя {user_id}")
                    except Exception as e:
                        logger.warning(f"Не удалось удалить сообщение {msg_id} при отмене: {e}")

            await _normalize_state(state, user_id)
            cancel_message = "▶️ Я готов к Вашим вопросам."
            await callback.message.answer(cancel_message, parse_mode=ParseMode.HTML)
            await save_chat_message(user_id, "assistant", cancel_message)
            await callback.answer()
            logger.info(f"Пользователь {user_id} отменил запись")

    except Exception as e:
        logger.error(f"Ошибка при обработке кнопки Фазы 4: {e}", exc_info=True)
        await callback.answer("⚠️ Произошла ошибка. Попробуйте еще раз.", show_alert=True)


async def _normalize_state(state: FSMContext, user_id: int) -> None:
    """Нормализация состояния бота - сброс всех незавершенных операций"""
    logger = logging.getLogger(__name__)
    try:
        await state.update_data(
            phase=1,
            phase4_window_shown=False,
            phase4_state=None,
            phase4_check_contacts=False,
            phase4_invalid_messages=[],
            anketa_started=False,
            anketa_question=None,
            anketa_retry_count=0,
            anketa_invalid_messages=[],
            intent_selection_shown=False,
            policy_shown=False,
            continue_button_pressed=False
        )
        logger.info(f"Состояние нормализовано для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при нормализации состояния: {e}", exc_info=True)


@router.callback_query(F.data.startswith("primary_source:goto"))
async def handle_primary_source_goto(callback: CallbackQuery, state: FSMContext) -> None:
    logger = logging.getLogger(__name__)
    data = await state.get_data()
    if not data.get("primary_source_is_rules"):
        await callback.answer("Первоисточник недоступен для этого запроса.", show_alert=True)
        return

    fragments = data.get("primary_sources") or []
    if not fragments:
        await callback.answer("Фрагменты недоступны.", show_alert=True)
        return

    parts = callback.data.split(":")
    try:
        requested_index = int(parts[-1])
    except (ValueError, IndexError):
        requested_index = 0

    # Используем циклическую навигацию (по кругу)
    idx = requested_index % len(fragments) if len(fragments) > 0 else 0

    fragment = fragments[idx]
    main_source = data.get("primary_source_main_source")
    fragment_source = fragment.get("source") if isinstance(fragment, dict) else None
    resolved_source = fragment_source or main_source
    download_info = _get_download_info_for_source(resolved_source) if resolved_source else None
    text = _format_primary_source_fragment(fragment, idx, len(fragments), download_info)
    markup = _build_primary_source_markup(idx, len(fragments), download_info)

    # Удаляем старые рисунки перед переходом к новому фрагменту
    old_figure_messages = data.get("primary_source_figure_messages") or []
    for msg_id in old_figure_messages:
        try:
            await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
        except Exception as del_error:
            logger.debug(f"Не удалось удалить старое сообщение с рисунком {msg_id}: {del_error}")

    sent_message = None
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode='HTML')
        sent_message = callback.message
    except Exception:
        sent_message = await callback.message.answer(text, reply_markup=markup, parse_mode='HTML')

    await state.update_data(primary_source_index=idx)
    await callback.answer()

    # Отправляем рисунки, если они есть для этого фрагмента
    figure_message_ids = []
    if sent_message:
        try:
            figures_to_send = _get_figures_for_fragment(fragment, main_source)
            for fig_key in figures_to_send:
                img_path = image_mapper.get_image_path_for_figure(fig_key)
                if img_path:
                    try:
                        photo = FSInputFile(img_path)
                        title = image_mapper.get_figure_title(fig_key)
                        if title:
                            caption = f"{title} {fig_key}."
                        else:
                            caption = f"{fig_key}."
                        fig_message = await sent_message.answer_photo(photo=photo, caption=caption)
                        if fig_message and fig_message.message_id:
                            figure_message_ids.append(fig_message.message_id)
                    except Exception as img_error:
                        logger.warning(f"Не удалось отправить изображение {fig_key}: {img_error}")
            await state.update_data(primary_source_figure_messages=figure_message_ids)
        except Exception as fig_error:
            logger.warning(f"Ошибка при определении рисунков для фрагмента: {fig_error}")


@router.callback_query(F.data == "primary_source:close")
async def handle_primary_source_close(callback: CallbackQuery, state: FSMContext) -> None:
    logger = logging.getLogger(__name__)
    # Удаляем рисунки при закрытии окна
    data = await state.get_data()
    old_figure_messages = data.get("primary_source_figure_messages") or []
    for msg_id in old_figure_messages:
        try:
            await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
        except Exception as del_error:
            logger.debug(f"Не удалось удалить сообщение с рисунком {msg_id}: {del_error}")

    await state.update_data(primary_source_figure_messages=[])

    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await callback.answer()


def register_faq(dp: Dispatcher) -> None:
    dp.include_router(router)


