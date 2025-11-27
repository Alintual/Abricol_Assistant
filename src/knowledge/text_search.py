"""
Система полнотекстового поиска на основе SQLite FTS (Full-Text Search).
Использует структурированные тексты для надежного и точного поиска.

Альтернатива векторной базе данных - более надежная и простая система.
"""

import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from typing import List, Optional


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STRUCTURED_DIR = os.path.join(DATA_DIR, "structured")
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "knowledge.db"))


@dataclass
class SearchHit:
    source: str
    title: str
    text: str
    score: float
    figures: str = ""  # Список рисунков в формате "Рис.1.1.1,Рис.1.1.2"
    section: str = ""  # Секция/раздел документа


def _get_connection() -> sqlite3.Connection:
    """Создает подключение к SQLite базе данных."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_text(text: str) -> str:
    """Нормализует текст для поиска."""
    # Убираем лишние пробелы, переносы строк
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text


def _extract_figures(text: str) -> str:
    """Извлекает все упоминания рисунков из текста."""
    figures = re.findall(r'Рис\.(\d+\.\d+\.\d+)', text)
    if figures:
        return ",".join([f"Рис.{f}" for f in figures])
    return ""


def _extract_section(text: str, max_lines: int = 10) -> str:
    """Извлекает название секции из начала текста (для контекста)."""
    lines = text.split('\n')[:max_lines]
    # Ищем заголовки (строки, начинающиеся с #)
    for line in lines:
        line = line.strip()
        if line.startswith('#'):
            # Убираем символы # и лишние пробелы
            section = re.sub(r'^#+\s*', '', line)
            section = section.strip()
            if section and len(section) < 100:
                return section
    return ""


def _rule_number_sort_key(fragment: dict) -> tuple[int, ...]:
    number = fragment.get("rule_number") or ""
    parts = [int(part) for part in re.findall(r"\d+", number)]
    if not parts:
        return (sys.maxsize,)
    return tuple(parts)


def _position_sort_key(fragment: dict) -> int:
    """Сортирует фрагменты по позиции в документе (сверху вниз)."""
    position = fragment.get("_position", sys.maxsize)
    return position


def _sort_and_return_fragments(fragments: list[dict]) -> list[dict]:
    # Сортируем по позиции в документе (сверху вниз), а не по номеру правила
    # Если позиция не указана, используем сортировку по номеру как fallback
    fragments.sort(key=lambda f: (f.get("_position", sys.maxsize), _rule_number_sort_key(f)))
    return fragments


def build_index() -> None:
    """
    Строит индекс из структурированных текстов.
    Использует SQLite FTS5 для полнотекстового поиска.
    """
    if not os.path.exists(STRUCTURED_DIR):
        print(f"[WARNING] Директория со структурированными текстами не найдена: {STRUCTURED_DIR}")
        return
    
    conn = _get_connection()
    cursor = conn.cursor()
    
    # Создаем основную таблицу для хранения документов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            section TEXT,
            figures TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Проверяем поддержку FTS5
    try:
        cursor.execute("PRAGMA compile_options")
        compile_options = [row[0] for row in cursor.fetchall()]
        has_fts5 = any('FTS5' in opt for opt in compile_options)
    except:
        has_fts5 = False
    
    if not has_fts5:
        # Проверяем через попытку создания таблицы
        try:
            cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS test_fts5 USING fts5(test)")
            cursor.execute("DROP TABLE test_fts5")
            has_fts5 = True
        except:
            has_fts5 = False
    
    # Сохраняем флаг для использования позже
    use_fts5 = has_fts5
    
    if has_fts5:
        # Создаем FTS5 таблицу для полнотекстового поиска
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                content,
                source,
                title,
                section,
                figures,
                content='documents',
                content_rowid='id'
            )
        """)
    else:
        # Fallback на FTS4 (без внешнего контента)
        print("[WARNING] FTS5 не поддерживается, используем FTS4")
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts4(
                rowid,
                content,
                source,
                title,
                section,
                figures
            )
        """)
    
    # Очищаем старые данные
    cursor.execute("DELETE FROM documents")
    try:
        cursor.execute("DELETE FROM documents_fts")
    except:
        pass  # Если таблица еще не создана
    
    # Индексируем все структурированные файлы
    structured_files = [f for f in os.listdir(STRUCTURED_DIR) if f.endswith("_structured.txt")]
    
    if not structured_files:
        print(f"[WARNING] Не найдено структурированных файлов в {STRUCTURED_DIR}")
        conn.close()
        return
    
    print(f"[INFO] Найдено структурированных файлов: {len(structured_files)}")
    
    total_docs = 0
    
    for filename in sorted(structured_files):
        filepath = os.path.join(STRUCTURED_DIR, filename)
        title = filename.replace("_structured.txt", "").replace(".pdf", "")
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            if not content.strip():
                continue
            
            # Вставляем ВЕСЬ текст файла как один документ (не разбиваем на фрагменты)
            # Нормализуем текст для поиска (но сохраняем оригинал для отображения)
            normalized = _normalize_text(content)
            
            # Извлекаем все рисунки из всего документа
            figures = _extract_figures(content)
            
            # Извлекаем название (первый заголовок или название файла)
            section_name = _extract_section(content)
            if not section_name:
                section_name = title
            
            # Вставляем весь документ как одну запись
            cursor.execute("""
                INSERT INTO documents (source, title, content, section, figures)
                VALUES (?, ?, ?, ?, ?)
            """, (filename, title, normalized, section_name, figures))
            
            total_docs += 1
            print(f"  [OK] {filename}: индексирован как один документ ({len(content)} символов)")
            
        except Exception as e:
            print(f"  [ERROR] Ошибка при обработке {filename}: {e}")
            continue
    
    # Заполняем FTS таблицу данными
    if use_fts5:
        # Для FTS5 с внешним контентом - синхронизируем
        try:
            cursor.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        except:
            # Если rebuild не работает, вставляем данные вручную
            cursor.execute("""
                INSERT INTO documents_fts (rowid, content, source, title, section, figures)
                SELECT id, content, source, title, section, figures FROM documents
            """)
    else:
        # Для FTS4 - вставляем данные напрямую
        cursor.execute("""
            INSERT INTO documents_fts (rowid, content, source, title, section, figures)
            SELECT id, content, source, title, section, figures FROM documents
        """)
    
    conn.commit()
    conn.close()
    
    print(f"[SUCCESS] Индекс построен: {total_docs} документов из {len(structured_files)} файлов")


def ensure_index() -> None:
    """Проверяет наличие индекса, создает если нужно."""
    if not os.path.exists(DB_PATH):
        build_index()
    else:
        # Проверяем, что индекс не пустой
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) as count FROM documents")
            result = cursor.fetchone()
            if result and result['count'] == 0:
                build_index()
            else:
                # Проверяем, что FTS таблица существует
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents_fts'")
                if not cursor.fetchone():
                    build_index()
        except Exception:
            build_index()
        finally:
            conn.close()


def search(query: str, top_k: int = 5) -> List[SearchHit]:
    """
    Выполняет полнотекстовый поиск по запросу.
    
    Args:
        query: Поисковый запрос
        top_k: Количество результатов
    
    Returns:
        Список найденных документов с релевантностью
    """
    ensure_index()
    
    if not query or not query.strip():
        return []
    
    # Нормализуем запрос
    query_normalized = _normalize_text(query)
    
    # Подготавливаем запрос для FTS (экранируем специальные символы)
    # FTS5 использует синтаксис: "слово1 слово2" для точной фразы, слово1 OR слово2 для ИЛИ
    # Экранируем специальные символы
    fts_query = query_normalized.replace('"', '""')
    
    # Формируем запрос для FTS
    # FTS ищет по словам, нужно правильно экранировать
    words = query_normalized.split()
    
    # Убираем очень короткие слова (меньше 2 символов)
    words = [w for w in words if len(w) > 2]
    
    if not words:
        # Если все слова слишком короткие, используем весь запрос
        words = [query_normalized]
    
    if len(words) > 1:
        # Для нескольких слов используем OR (более гибкий поиск)
        # Каждое слово ищем отдельно
        fts_query = " OR ".join([f'"{w}"' for w in words])
    else:
        # Для одного слова используем точный поиск с префиксом для частичного совпадения
        word = words[0]
        # Используем префиксный поиск (*) для частичного совпадения
        fts_query = f'"{word}"*'
    
    conn = _get_connection()
    cursor = conn.cursor()
    
    try:
        # Выполняем FTS поиск с ранжированием по релевантности
        # Проверяем, поддерживается ли bm25 (только в FTS5)
        try:
            # Пробуем использовать bm25 (FTS5)
            cursor.execute("""
                SELECT 
                    d.source,
                    d.title,
                    d.content,
                    d.section,
                    d.figures,
                    bm25(documents_fts) as rank
                FROM documents_fts
                JOIN documents d ON documents_fts.rowid = d.id
                WHERE documents_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, top_k * 2))
        except:
            # Fallback для FTS4 или если bm25 не работает
            cursor.execute("""
                SELECT 
                    d.source,
                    d.title,
                    d.content,
                    d.section,
                    d.figures,
                    0.0 as rank
                FROM documents_fts
                JOIN documents d ON documents_fts.rowid = d.id
                WHERE documents_fts MATCH ?
                LIMIT ?
            """, (fts_query, top_k * 2))
        
        results = cursor.fetchall()
        
        # Добавляем логирование для отладки
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"FTS запрос: '{fts_query}', найдено строк: {len(results)}")
        
        hits: List[SearchHit] = []
        seen_texts = set()  # Для дедупликации
        
        for row in results:
            content = row['content']
            
            # Дедупликация по первым 100 символам
            content_key = content[:100]
            if content_key in seen_texts:
                continue
            seen_texts.add(content_key)
            
            # Вычисляем score (чем меньше rank, тем выше релевантность)
            # bm25 возвращает отрицательные значения, конвертируем в 0-1
            rank = row['rank'] or 0.0
            score = max(0.0, min(1.0, 1.0 / (1.0 + abs(rank) / 10.0)))
            
            # Если запрос точно совпадает с началом текста, повышаем score
            if content.lower().startswith(query_normalized.lower()):
                score = min(1.0, score + 0.2)
            
            # Подсчитываем количество совпадений слов
            query_words = query_normalized.lower().split()
            content_lower = content.lower()
            matches = sum(1 for word in query_words if word in content_lower)
            if matches > 0:
                score = min(1.0, score + (matches / len(query_words)) * 0.3)
            
            hit = SearchHit(
                source=row['source'] or "",
                title=row['title'] or "",
                text=content,
                score=score,
                figures=row['figures'] or "",
                section=row['section'] or ""
            )
            hits.append(hit)
            
            if len(hits) >= top_k:
                break
        
        # Если FTS не нашел результатов, делаем fallback поиск по LIKE
        if not hits:
            logger.debug("FTS не нашел результатов, используем fallback LIKE поиск")
            query_words = query_normalized.split()
            
            # Пробуем разные варианты поиска
            for word in query_words:
                if len(word) < 3:
                    continue
                    
                like_pattern = f"%{word}%"
                
                cursor.execute("""
                    SELECT source, title, content, section, figures
                    FROM documents
                    WHERE content LIKE ?
                    LIMIT ?
                """, (like_pattern, top_k * 2))
                
                fallback_results = cursor.fetchall()
                
                if fallback_results:
                    logger.debug(f"Fallback нашел {len(fallback_results)} результатов для слова '{word}'")
                    
                    for row in fallback_results:
                        content = row['content']
                        content_key = content[:100]
                        if content_key in seen_texts:
                            continue
                        seen_texts.add(content_key)
                        
                        # Подсчитываем количество совпадений слов
                        query_words_lower = query_normalized.lower().split()
                        content_lower = content.lower()
                        matches = sum(1 for w in query_words_lower if w in content_lower)
                        score = 0.7 if matches > 0 else 0.5
                        
                        if matches > 0:
                            score = min(1.0, 0.7 + (matches / len(query_words_lower)) * 0.3)
                        
                        hit = SearchHit(
                            source=row['source'] or "",
                            title=row['title'] or "",
                            text=content,
                            score=score,
                            figures=row['figures'] or "",
                            section=row['section'] or ""
                        )
                        hits.append(hit)
                        
                        if len(hits) >= top_k:
                            break
                    
                    # Если нашли результаты, прекращаем поиск
                    if hits:
                        break
        
        # Сортируем по score (убывание)
        hits.sort(key=lambda x: x.score, reverse=True)
        
        return hits[:top_k]
        
    except Exception as e:
        # Если FTS5 не поддерживается или ошибка, используем простой LIKE поиск
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Ошибка FTS поиска: {e}, используем fallback")
        
        query_words = query_normalized.split()
        like_pattern = f"%{'%'.join(query_words)}%"
        
        try:
            cursor.execute("""
                SELECT source, title, content, section, figures
                FROM documents
                WHERE content LIKE ?
                LIMIT ?
            """, (like_pattern, top_k))
            
            results = cursor.fetchall()
            logger.debug(f"Fallback LIKE поиск: найдено {len(results)} результатов")
            
            hits = []
            for row in results:
                hit = SearchHit(
                    source=row['source'] or "",
                    title=row['title'] or "",
                    text=row['content'] or "",
                    score=0.7,
                    figures=row['figures'] or "",
                    section=row['section'] or ""
                )
                hits.append(hit)
            
            return hits
        except Exception as e2:
            logger.error(f"Ошибка fallback поиска: {e2}", exc_info=True)
            return []
    
    finally:
        conn.close()


import re
import os

ALLOWED_SOURCES = [
    '2.1.1_Международные правила_structured.txt',
    '2.1.2_Правила игры Корона_structured.txt',
    '2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt',
]
CONTEXT_ROUTES = {
    'корона': '2.1.2_Правила игры Корона_structured.txt',
    'пирамид': '2.1.1_Международные правила_structured.txt',
    'междунар': '2.1.1_Международные правила_structured.txt',
    'оборуд': '2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt',
    'аксес': '2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt',
    'фбср': '2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt',
}
CONTEXT_STOP_WORDS = set([w for w in CONTEXT_ROUTES] + ['игра', 'русский', 'бильярд', 'стол', 'общие'])


def _normalize_number(number: str) -> str:
    return number.strip().rstrip('.').strip()


def _extract_blocks_from_content(content: str) -> list[dict]:
    """
    Извлекает блоки из структурированного текста согласно новой структуре:
    - Разделы: от "#" до следующей "#"
    - Пункты: текст с номером N. (без точки в конце первой строки)
    - Подпункты: текст с номером N.N или N.N.N
    - Приамбулы: текст без номера после раздела или перед пунктом
    """
    content_with_newlines = content.replace('###', '\n###')
    if not content_with_newlines.startswith('\n'):
        content_with_newlines = '\n' + content_with_newlines
    
    blocks: list[dict] = []
    
    # Паттерн для поиска номеров: N. или N.N. или N.N.N. в начале строки
    # Исключаем номера в конце строки (они заканчиваются на ".")
    # Пункт начинается с номера в начале строки или после пробела/табуляции
    point_pattern = re.compile(r'(?:^|\n)(\d{1,2}(?:\.\d+)*\.)\s+')
    
    matches = list(point_pattern.finditer(content_with_newlines))
    
    if not matches:
        return blocks
    
    # Обрабатываем каждый найденный номер как начало блока
    for i, match in enumerate(matches):
        # КРИТИЧНО: Начало блока должно быть строго с начала строки, содержащей номер
        # Находим начало строки с номером (перед номером может быть только пробел/таб)
        match_start = match.start(1)  # Позиция начала номера в совпадении
        # Ищем начало строки, содержащей этот номер
        line_start = content_with_newlines.rfind('\n', 0, match_start) + 1
        # Если это первая строка, line_start будет 0
        if line_start == 0 and not content_with_newlines.startswith('\n'):
            line_start = 0
        # Проверяем, что перед номером на строке нет текста (только пробелы/табы)
        line_before_number = content_with_newlines[line_start:match_start].strip()
        # Если перед номером есть непустой текст - это не начало блока, пропускаем
        # Исключение: если это перечисление (номер в скобках или после дефиса)
        if line_before_number and not re.match(r'^[\s\-•\(\)]+$', line_before_number):
            # Перед номером есть текст - это не начало блока пункта/подпункта
            # Пропускаем этот номер (возможно, это часть перечисления)
            continue
        
        start = match_start  # Используем позицию начала номера
        number = match.group(1).strip()
        
        # Определяем, является ли это подпунктом (N.N или N.N.N)
        is_subpoint = number.count('.') > 1
        
        # Находим раздел для этого блока СНАЧАЛА
        before = content_with_newlines[:start]
        section = ''
        # Ищем последний маркер раздела "# ..."
        section_match = list(re.finditer(r'^# ([^\n]+)', before, re.MULTILINE))
        if section_match:
            last_section = section_match[-1]
            section_text = last_section.group(1).strip()
            # Название раздела - первая строка без "." на конце
            if section_text.endswith('.'):
                section_text = section_text[:-1].strip()
            section = section_text
        
        # КРИТИЧНО: Сначала проверяем границы раздела
        # Блок должен заканчиваться до начала следующего раздела (если он есть)
        # Ищем следующий раздел после начала текущего блока
        next_section_pos = content_with_newlines.find('\n# ', start)
        section_end_limit = len(content_with_newlines)
        if next_section_pos != -1:
            # Проверяем, что следующий раздел действительно другой (не текущий)
            # Находим название следующего раздела
            next_section_line_end = content_with_newlines.find('\n', next_section_pos + 2)
            if next_section_line_end != -1:
                next_section_line = content_with_newlines[next_section_pos + 2:next_section_line_end].strip()
                if next_section_line.endswith('.'):
                    next_section_line = next_section_line[:-1].strip()
                # Если следующий раздел отличается от текущего - блок должен заканчиваться до него
                if next_section_line != section:
                    section_end_limit = next_section_pos
        
        # Определяем конец блока (но не позже границы раздела)
        if i + 1 < len(matches):
            next_match = matches[i + 1]
            next_number = next_match.group(1).strip()
            next_start = next_match.start(1)
            
            # Если следующий блок находится в другом разделе - блок должен заканчиваться до него
            # Находим раздел следующего блока
            before_next = content_with_newlines[:next_start]
            next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
            next_block_section = ''
            if next_section_match:
                last_next_section = next_section_match[-1]
                next_section_text = last_next_section.group(1).strip()
                if next_section_text.endswith('.'):
                    next_section_text = next_section_text[:-1].strip()
                next_block_section = next_section_text
            
            # Если следующий блок в другом разделе - блок должен заканчиваться до него
            if next_block_section and next_block_section != section:
                end = min(next_start, section_end_limit)
            # Если текущий блок - это пункт (N.), а следующий - его подпункт (N.M),
            # то конец текущего блока - это начало первого подпункта
            elif not is_subpoint and '.' in next_number:
                current_point_num = number.split('.')[0] if '.' in number else number.rstrip('.')
                next_first_part = next_number.split('.')[0]
                
                # Если следующий блок - подпункт текущего пункта
                if next_first_part == current_point_num and next_number.count('.') > 1:
                    # Ищем первый подпункт - это будет конец блока пункта
                    # Ищем паттерн "N.1." или "N.1.N" после текущего номера
                    first_subpoint_pattern = re.compile(r'(?:^|\n)' + re.escape(current_point_num) + r'\.1\.')
                    first_subpoint_match = first_subpoint_pattern.search(content_with_newlines, start)
                    if first_subpoint_match:
                        end = min(first_subpoint_match.start(), section_end_limit)
                    else:
                        end = min(next_start, section_end_limit)
                else:
                    # Следующий блок - другой пункт
                    end = min(next_start, section_end_limit)
            else:
                end = min(next_start, section_end_limit)
        else:
            # Последний блок - до следующего раздела или до конца
            end = section_end_limit
        
        # Извлекаем текст блока (включая номер)
        # КРИТИЧНО: Блок должен начинаться строго с номера, без текста перед ним
        # Находим начало строки с номером
        line_start_pos = content_with_newlines.rfind('\n', 0, start) + 1
        if line_start_pos == 0 and not content_with_newlines.startswith('\n'):
            line_start_pos = 0
        
        # Проверяем, есть ли текст перед номером в строке
        line_content_before_number = content_with_newlines[line_start_pos:start].strip()
        if line_content_before_number:
            # В строке перед номером есть текст - это остаток предыдущего блока
            # Блок должен начинаться строго с позиции номера (не включая текст перед номером)
            # Извлекаем текст от позиции номера до конца блока
            block_text = content_with_newlines[start:end].strip()
            # КРИТИЧНО: Убеждаемся, что первая строка начинается строго с номера
            # Если первая строка содержит текст перед номером - обрезаем его
            lines_check = block_text.split('\n')
            if lines_check:
                first_line_check = lines_check[0]
                number_pos_in_first = first_line_check.find(number)
                if number_pos_in_first > 0:
                    # Перед номером в первой строке есть текст - обрезаем его
                    first_line_check = first_line_check[number_pos_in_first:]
                    lines_check[0] = first_line_check
                    block_text = '\n'.join(lines_check).strip()
        else:
            # В строке перед номером только пробелы - это нормально
            # Блок начинается с начала строки с номером
            block_text = content_with_newlines[line_start_pos:end].strip()
        
        # КРИТИЧНО: Убеждаемся, что блок начинается строго с номера
        # Проверяем первую строку и обрезаем все, что перед номером
        lines = block_text.split('\n')
        if not lines:
            continue
        
        first_line = lines[0]
        # Находим позицию номера в первой строке (без strip, чтобы сохранить пробелы)
        number_pos = first_line.find(number)
        if number_pos < 0:
            # Номер не найден в первой строке - ошибка
            continue
        elif number_pos > 0:
            # Перед номером есть текст - это остаток предыдущего блока
            # Проверяем, является ли это частью перечисления (только маркеры)
            text_before = first_line[:number_pos].strip()
            is_enum_marker = re.match(r'^[\s\-•\(\)]+$', text_before) if text_before else False
            
            # КРИТИЧНО: По требованиям - перед номером пункта/подпункта не должно быть текста
            # Исключение: только маркеры перечисления
            # ВСЕГДА обрезаем текст перед номером, если это не маркер перечисления
            if not is_enum_marker:
                # Это не маркер перечисления - обрезаем первую строку до номера
                first_line = first_line[number_pos:]
                lines[0] = first_line
                block_text = '\n'.join(lines).strip()
            else:
                # Это маркер перечисления - тоже обрезаем, так как перед номером пункта/подпункта не должно быть ничего
                first_line = first_line[number_pos:]
                lines[0] = first_line
                block_text = '\n'.join(lines).strip()
        else:
            # Номер в начале строки - это правильно
            # Убеждаемся, что нет пробелов перед номером
            first_line_stripped = first_line.strip()
            if not first_line_stripped.startswith(number):
                # Есть пробелы перед номером - удаляем их
                first_line = first_line.lstrip()
                if first_line.startswith(number):
                    lines[0] = first_line
                    block_text = '\n'.join(lines).strip()
                else:
                    # Номер не найден после удаления пробелов - ошибка
                    continue
            else:
                block_text = '\n'.join(lines).strip()
        
        # ФИНАЛЬНАЯ ПРОВЕРКА: блок должен начинаться строго с номера
        if not block_text.strip().startswith(number):
            continue
        
        # Удаляем маркеры следующих разделов из конца блока
        # Блок не должен содержать маркер следующего раздела "# ..."
        lines = block_text.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Если строка начинается с маркера раздела "# " - это конец блока
            if stripped.startswith('# '):
                break
            cleaned_lines.append(line)
        block_text = '\n'.join(cleaned_lines).strip()
        
        # ФИНАЛЬНАЯ ПРОВЕРКА: блок должен начинаться с правильного номера
        # И не должен содержать текст из предыдущего блока
        block_text_stripped = block_text.strip()
        if not block_text_stripped.startswith(number):
            # Блок все еще не начинается с правильного номера - пропускаем его
            continue
        
        # ФИНАЛЬНАЯ ПРОВЕРКА: убеждаемся, что первая строка начинается строго с номера
        # ВСЕГДА обрезаем любой текст перед номером в первой строке
        lines_final = block_text.split('\n')
        if lines_final:
            first_line_final = lines_final[0]
            # Находим позицию номера в первой строке
            number_pos_final = first_line_final.find(number)
            if number_pos_final < 0:
                # Номер не найден - пропускаем блок
                continue
            elif number_pos_final > 0:
                # Перед номером есть текст - ВСЕГДА обрезаем его
                # По требованиям: перед номером пункта/подпункта не должно быть текста
                first_line_final = first_line_final[number_pos_final:]
                lines_final[0] = first_line_final
                block_text = '\n'.join(lines_final).strip()
            else:
                # Номер в начале строки - удаляем пробелы перед ним
                first_line_final = first_line_final.lstrip()
                if first_line_final.startswith(number):
                    lines_final[0] = first_line_final
                    block_text = '\n'.join(lines_final).strip()
                else:
                    # Номер не найден после удаления пробелов - пропускаем блок
                    continue
        
        # ФИНАЛЬНАЯ ПРОВЕРКА: блок должен начинаться строго с номера
        if not block_text.strip().startswith(number):
            continue
        
        # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: блок не должен содержать текст с другим номером перед правильным номером
        # Проверяем первые строки блока на наличие других номеров пунктов/подпунктов
        lines_check = block_text.split('\n')
        for line_idx, line in enumerate(lines_check[:3]):  # Проверяем первые 3 строки
            stripped_line = line.strip()
            if not stripped_line:
                continue
            # Ищем номер пункта/подпункта в строке (паттерн: N. или N.N. или N.N.N.)
            other_number_match = re.match(r'^(\d+(?:\.\d+)*\.)\s+', stripped_line)
            if other_number_match:
                found_number = other_number_match.group(1)
                # Если найденный номер отличается от номера блока
                if found_number != number:
                    # Если это первая строка - это ошибка, блок содержит текст из другого блока
                    # ПРОПУСКАЕМ блок полностью - он содержит остаток предыдущего блока
                    if line_idx == 0:
                        continue
                    # Если это не первая строка, но номер найден - это может быть часть перечисления
                    # Пропускаем проверку для строк после первой
                    break
        
        # Определяем тип блока: пункт или подпункт
        # Подпункт имеет более 1 точки в номере (например, 2.1., 2.1.1.)
        is_subpoint = number.count('.') > 1
        
        blocks.append({
            'number': number,
            'start': start,
            'end': end,
            'section': section,
            'text': block_text,
            'is_subpoint': is_subpoint,
        })
    
    return blocks


def _block_has_content(block: dict) -> bool:
    """Проверяет, содержит ли блок полезный текст (не только заголовки)."""
    # Проверяем, что блок не пустой
    if not block['text'].strip():
        return False
    # Проверяем, что в блоке есть хотя бы одно слово, отличное от заголовка
    # Исключаем заголовки, которые могут быть в начале блока
    if block['section'] and block['section'].lower() in ['глава', 'раздел', 'пункт', 'подпункт', 'абзац', 'часть']:
        # Ищем слова, которые не являются заголовками
        words = re.findall(r'\b\w+\b', block['text'])
        if words:
            # Проверяем, есть ли среди слов хоть одно, которое не является заголовком
            # (например, '1.1.1' или '1.1.1.1')
            if not any(re.match(r'\d+\.\d+\.\d+', w) for w in words):
                return True
    return True


def _collect_candidate_docs(hits, allowed_sources, lwquery):
    candidate_docs: list[str] = []
    if allowed_sources:
        candidate_docs = [doc for doc in allowed_sources if doc in ALLOWED_SOURCES]
    if not candidate_docs:
        for key, doc in CONTEXT_ROUTES.items():
            if key in lwquery and doc in ALLOWED_SOURCES:
                candidate_docs.append(doc)
    if not candidate_docs and hits:
        for hit in hits:
            src = (hit.source or '').strip()
            if src in ALLOWED_SOURCES and src not in candidate_docs:
                candidate_docs.append(src)
    
    # Сортируем документы: сначала "Международные правила" (2.1.1_), затем "Правила Корона" (2.1.2_), затем остальные
    def _sort_key(doc: str) -> tuple[int, str]:
        """Возвращает ключ сортировки для документа."""
        if doc.startswith("2.1.1_"):
            return (0, doc)  # Международные правила - первый приоритет
        elif doc.startswith("2.1.2_"):
            return (1, doc)  # Правила Корона - второй приоритет
        else:
            return (2, doc)  # Остальные - третий приоритет
    
    candidate_docs.sort(key=_sort_key)
    return candidate_docs


def _collect_fragments(candidate_docs, search_words, max_fragments, phrases=None):
    """
    Маршрутизатор для формирования окон первоисточника.
    Определяет тип документа и вызывает соответствующую специализированную функцию.
    """
    structured_dir = os.path.join(os.path.dirname(__file__), "data", "structured")
    fragments: list[dict] = []
    phrases = [p for p in (phrases or []) if p] if phrases else []
    
    # Константы для определения типа документа
    INTERNATIONAL_RULES = "2.1.1_Международные правила_structured.txt"
    CORONA_RULES = "2.1.2_Правила игры Корона_structured.txt"
    TECHNICAL_REQUIREMENTS = "2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt"
    
    for doc in candidate_docs:
        path = os.path.join(structured_dir, doc)
        if not os.path.exists(path):
            continue
        
        with open(path, encoding="utf-8") as f:
            content = f.read()
        
        # Для каждого документа используем отдельный processed_blocks, чтобы избежать конфликтов
        processed_blocks = set()
        
        # Определяем тип документа и вызываем соответствующую функцию
        if doc == TECHNICAL_REQUIREMENTS:
            fragments = _collect_fragments_technical_requirements(
                content, doc, search_words, phrases, max_fragments, fragments, processed_blocks
            )
        elif doc == CORONA_RULES:
            fragments = _collect_fragments_corona_rules(
                content, doc, search_words, phrases, max_fragments, fragments, processed_blocks
            )
        elif doc == INTERNATIONAL_RULES:
            fragments = _collect_fragments_international_rules(
                content, doc, search_words, phrases, max_fragments, fragments, processed_blocks
            )
        else:
            # Для других документов пропускаем (если понадобится - добавим отдельную функцию)
            continue
        
        if len(fragments) >= max_fragments:
            return _sort_and_return_fragments(fragments)
    
    return _sort_and_return_fragments(fragments)


# Старая универсальная логика удалена - теперь используются специализированные функции для каждого документа


# Старая логика удалена - теперь используется простая логика:
# 1. Находим релевантные фрагменты (где есть поисковые слова)
# 2. Для каждого фрагмента находим ближайший номер пункта СВЕРХУ
# 3. Извлекаем блок, начиная с этого номера
# 4. Находим раздел для блока
# 5. Сохраняем фрагмент с правильной позицией для сортировки




def _collect_fragments_technical_requirements(content, doc, search_words, phrases, max_fragments, fragments, processed_blocks):
    """
    Специализированная логика для 2.2_Технические требования к бильярдным столам и оборудованию ФБСР_structured.txt
    Сохраняет текущую работающую логику для этого документа
    """
    # Подготавливаем контент для поиска
    content_with_newlines = content.replace('###', '\n###')
    if not content_with_newlines.startswith('\n'):
        content_with_newlines = '\n' + content_with_newlines
    
    # ШАГ 1: Находим все релевантные фрагменты (где есть поисковые слова)
    content_lower = content_with_newlines.lower()
    relevant_positions = []
    
    if search_words:
        for word in search_words:
            pos = 0
            while True:
                pos = content_lower.find(word, pos)
                if pos == -1:
                    break
                relevant_positions.append(pos)
                pos += len(word)
    
    if phrases:
        for phrase in phrases:
            pos = 0
            while True:
                pos = content_lower.find(phrase, pos)
                if pos == -1:
                    break
                relevant_positions.append(pos)
                pos += len(phrase)
    
    if not relevant_positions:
        return fragments
    
    # Сортируем позиции и убираем дубликаты
    relevant_positions = sorted(set(relevant_positions))
    
    # ШАГ 2: Для каждой релевантной позиции находим ближайший номер пункта/подпункта СВЕРХУ
    point_pattern = re.compile(r'(?:^|\n)(\d{1,2}(?:\.\d+)*\.)\s+')
    all_points = list(point_pattern.finditer(content_with_newlines))
    
    for rel_pos in relevant_positions:
        # КРИТИЧНО: Сначала находим раздел для релевантной позиции
        before_rel_pos = content_with_newlines[:rel_pos]
        section_match_rel = list(re.finditer(r'^# ([^\n]+)', before_rel_pos, re.MULTILINE))
        rel_section = section_match_rel[-1].group(1).strip() if section_match_rel else ''
        
        # Находим границы раздела для релевантной позиции
        section_start = 0
        if section_match_rel:
            section_start = section_match_rel[-1].start(0)
        
        section_end = len(content_with_newlines)
        next_section_match = re.search(r'^# ', content_with_newlines[rel_pos:], re.MULTILINE)
        if next_section_match:
            section_end = rel_pos + next_section_match.start()
        
        # Находим ближайший номер пункта СВЕРХУ от релевантной позиции
        nearest_point = None
        nearest_point_pos = -1
        
        for point_match in all_points:
            point_pos = point_match.start(1)
            if point_pos <= rel_pos and point_pos >= section_start:
                before_point = content_with_newlines[:point_pos]
                point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                
                if point_section == rel_section:
                    if point_pos > nearest_point_pos:
                        nearest_point_pos = point_pos
                        nearest_point = point_match
        
        # КРИТИЧНО: Если не нашли номер СВЕРХУ, но релевантная позиция в разделе,
        # проверяем, есть ли номера НИЖЕ в этом разделе
        if not nearest_point:
            first_point_below = None
            first_point_below_pos = sys.maxsize
            
            for point_match in all_points:
                point_pos = point_match.start(1)
                if point_pos > rel_pos and point_pos < section_end:
                    before_point = content_with_newlines[:point_pos]
                    point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                    point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                    
                    if point_section == rel_section:
                        if point_pos < first_point_below_pos:
                            first_point_below_pos = point_pos
                            first_point_below = point_match
            
            if first_point_below:
                number = first_point_below.group(1).strip()
                number_start = first_point_below.start(1)
                
                line_start_first = content_with_newlines.rfind('\n', 0, number_start) + 1
                if line_start_first == 0 and not content_with_newlines.startswith('\n'):
                    line_start_first = 0
                
                line_end_first = content_with_newlines.find('\n', number_start)
                if line_end_first < 0:
                    line_end_first = len(content_with_newlines)
                first_line_with_number = content_with_newlines[number_start:line_end_first].strip()
                is_list_item = first_line_with_number.endswith('.')
                
                if is_list_item:
                    # Это список - формируем блок от начала вводного текста до конца списка
                    section_header_match = list(re.finditer(r'^# ([^\n]+)', content_with_newlines[:rel_pos], re.MULTILINE))
                    if section_header_match:
                        section_header_end = section_header_match[-1].end()
                        section_content_start = content_with_newlines.find('\n', section_header_end)
                        if section_content_start >= 0:
                            section_content_start += 1
                        else:
                            section_content_start = section_header_end
                    else:
                        section_content_start = section_start
                    
                    list_end = section_end
                    last_list_item_pos = number_start
                    
                    for point_match in all_points:
                        point_pos = point_match.start(1)
                        if point_pos > last_list_item_pos and point_pos < section_end:
                            before_point = content_with_newlines[:point_pos]
                            point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                            point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                            
                            if point_section == rel_section:
                                line_end_point = content_with_newlines.find('\n', point_pos)
                                if line_end_point < 0:
                                    line_end_point = len(content_with_newlines)
                                line_with_point = content_with_newlines[point_pos:line_end_point].strip()
                                if line_with_point.endswith('.'):
                                    last_list_item_pos = point_pos
                                    line_end_item = content_with_newlines.find('\n', point_pos)
                                    if line_end_item < 0:
                                        line_end_item = len(content_with_newlines)
                                    list_end = line_end_item
                                else:
                                    break
                
                    start = section_content_start
                    end = list_end
                    block_text = content_with_newlines[start:end].strip()
                    
                    block_text_lower = block_text.lower()
                    has_search_word = False
                    if search_words:
                        has_search_word = any(w in block_text_lower for w in search_words)
                    if phrases:
                        has_search_word = has_search_word or all(p in block_text_lower for p in phrases)
                    
                    if has_search_word:
                        section = rel_section
                        fragment = {
                            'source': doc,
                            'section': section,
                            'text': block_text,
                            'rule_number': '',
                            'rule_label': '',
                            'found_words': search_words if search_words else [],
                            'found_phrases': phrases if phrases else [],
                            '_position': start,
                        }
                        fragments.append(fragment)
                        print(f"[DEBUG] Фрагмент из технических требований (вводный текст раздела со списком): раздел={section}, позиция={start}, текст (первые 200 символов)={block_text[:200]}")
                else:
                    # Это не список, а обычный пункт - формируем блок от начала раздела до этого пункта
                    section_header_match = list(re.finditer(r'^# ([^\n]+)', content_with_newlines[:rel_pos], re.MULTILINE))
                    if section_header_match:
                        section_header_end = section_header_match[-1].end()
                        section_content_start = content_with_newlines.find('\n', section_header_end)
                        if section_content_start >= 0:
                            section_content_start += 1
                        else:
                            section_content_start = section_header_end
                    else:
                        section_content_start = section_start
                    
                    start = section_content_start
                    end = number_start
                    block_text = content_with_newlines[start:end].strip()
                    block_text_lower = block_text.lower()
                    has_search_word = False
                    if search_words:
                        has_search_word = any(w in block_text_lower for w in search_words)
                    if phrases:
                        has_search_word = has_search_word or all(p in block_text_lower for p in phrases)
                    
                    if has_search_word:
                        section = rel_section
                        fragment = {
                            'source': doc,
                                    'section': section,
                            'text': block_text,
                            'rule_number': '',
                            'rule_label': '',
                            'found_words': search_words if search_words else [],
                            'found_phrases': phrases if phrases else [],
                            '_position': start,
                        }
                        fragments.append(fragment)
                        print(f"[DEBUG] Фрагмент из технических требований (вводный текст раздела): раздел={section}, позиция={start}, текст (первые 100 символов)={block_text[:100]}")
            
            continue
        
        number = nearest_point.group(1).strip()
        if number in processed_blocks:
                continue
            
        # Для технических требований используем упрощенную логику без подпунктов
        number_start = nearest_point.start(1)
        
        # КРИТИЧНО: Проверяем, является ли найденный номер элементом списка
        # Если да, и релевантная позиция находится в этом списке, извлекаем весь список с приамбулой
        line_start_check = content_with_newlines.rfind('\n', 0, number_start) + 1
        if line_start_check == 0 and not content_with_newlines.startswith('\n'):
            line_start_check = 0
        
        line_end_check = content_with_newlines.find('\n', number_start)
        if line_end_check < 0:
            line_end_check = len(content_with_newlines)
        line_with_number_check = content_with_newlines[number_start:line_end_check].strip()
        is_list_item = line_with_number_check.endswith('.')
        
        # Если это элемент списка и релевантная позиция находится в этом списке
        if is_list_item:
            # Находим начало приамбулы (после заголовка раздела)
            section_header_match = list(re.finditer(r'^# ([^\n]+)', content_with_newlines[:rel_pos], re.MULTILINE))
            if section_header_match:
                section_header_end = section_header_match[-1].end()
                section_content_start = content_with_newlines.find('\n', section_header_end)
                if section_content_start >= 0:
                    section_content_start += 1
                else:
                    section_content_start = section_header_end
            else:
                section_content_start = section_start
            
            # Находим конец списка - последний элемент списка перед следующим разделом или концом раздела
            list_end = section_end
            first_list_item_pos = number_start
            
            # Находим первый элемент списка в этом разделе
            for point_match in all_points:
                point_pos = point_match.start(1)
                if point_pos < number_start and point_pos >= section_start:
                    before_point = content_with_newlines[:point_pos]
                    point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                    point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                    if point_section == rel_section:
                        line_end_point = content_with_newlines.find('\n', point_pos)
                        if line_end_point < 0:
                            line_end_point = len(content_with_newlines)
                        line_with_point = content_with_newlines[point_pos:line_end_point].strip()
                        if line_with_point.endswith('.'):
                            first_list_item_pos = point_pos
                        break
            
            # Находим последний элемент списка
            last_list_item_pos = number_start
            for point_match in all_points:
                point_pos = point_match.start(1)
                if point_pos > last_list_item_pos and point_pos < section_end:
                    before_point = content_with_newlines[:point_pos]
                    point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                    point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                    if point_section == rel_section:
                        line_end_point = content_with_newlines.find('\n', point_pos)
                        if line_end_point < 0:
                            line_end_point = len(content_with_newlines)
                        line_with_point = content_with_newlines[point_pos:line_end_point].strip()
                        if line_with_point.endswith('.'):
                            last_list_item_pos = point_pos
                            # Находим конец строки с этим элементом (включая перенос строки)
                            line_end_item = content_with_newlines.find('\n', point_pos)
                            if line_end_item < 0:
                                line_end_item = len(content_with_newlines)
                            else:
                                line_end_item += 1  # Включаем перенос строки
                            list_end = line_end_item
                        else:
                            break
            
            start = section_content_start
            end = list_end
            block_text = content_with_newlines[start:end].strip()
            
            # Проверяем, что блок содержит поисковые слова
            block_text_lower = block_text.lower()
            has_search_word = False
        if search_words:
            has_search_word = any(w in block_text_lower for w in search_words)
        if phrases:
            has_search_word = has_search_word or all(p in block_text_lower for p in phrases)
        
        if has_search_word:
                section = rel_section
                fragment = {
                    'source': doc,
                    'section': section,
                    'text': block_text,
                    'rule_number': '',
                    'rule_label': '',
                    'found_words': search_words if search_words else [],
                    'found_phrases': phrases if phrases else [],
                    '_position': start,
                }
                fragments.append(fragment)
                print(f"[DEBUG] Фрагмент из технических требований (список с приамбулой): раздел={section}, позиция={start}, текст (первые 200 символов)={block_text[:200]}")
        
        if len(fragments) >= max_fragments:
            return fragments
        
        continue
        
        # Если это не элемент списка, используем обычную логику
        line_start = content_with_newlines.rfind('\n', 0, number_start) + 1
        if line_start == 0 and not content_with_newlines.startswith('\n'):
            line_start = 0
        
        line_with_number = content_with_newlines[line_start:number_start + len(number) + 10]
        if not line_with_number.strip().startswith(number):
            number_pos_in_line = line_with_number.find(number)
            if number_pos_in_line >= 0:
                line_start = line_start + number_pos_in_line
            else:
                continue
        
        start = line_start
        end = section_end
        for point_match in all_points:
            point_pos = point_match.start(1)
            if point_pos > start and point_pos < section_end:
                before_next = content_with_newlines[:point_pos]
                next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                if next_section == rel_section:
                    end = point_pos
                    break
        
        block_text = content_with_newlines[start:end].strip()
        
        if start < section_start:
            continue
        
        section_markers_in_block = list(re.finditer(r'^# ', block_text, re.MULTILINE))
        if section_markers_in_block and section_markers_in_block[0].start() > 0:
            continue
        
        lines = block_text.split('\n')
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith(number + ' '):
                pass
            elif number in first_line:
                number_pos_in_first = first_line.find(number)
                if number_pos_in_first > 0:
                    text_before_number = first_line[:number_pos_in_first].strip()
                    if text_before_number:
                        same_number_pattern = re.compile(r'^' + re.escape(number) + r'\s+')
                        same_number_before = same_number_pattern.match(text_before_number)
                        if same_number_before:
                            continue
                        other_number_match = re.search(r'(\d{1,2}(?:\.\d+)*\.)\s+', text_before_number)
                        if other_number_match:
                            continue
                    first_line = first_line[number_pos_in_first:].strip()
                    lines[0] = first_line
                    block_text = '\n'.join(lines).strip()
                else:
                    continue
            else:
                continue
        
        if not block_text.startswith(number):
            number_pos = block_text.find(number)
            if number_pos >= 0:
                text_before = block_text[:number_pos].strip()
                if text_before:
                    other_number_match = re.search(r'(\d{1,2}(?:\.\d+)*\.)\s+', text_before)
                    if other_number_match:
                        continue
                block_text = block_text[number_pos:].strip()
            else:
                continue
        
        first_line_final = block_text.split('\n')[0].strip()
        if not first_line_final.startswith(number):
            continue
        
        block_text_lower = block_text.lower()
        has_search_word = False
        if search_words:
            has_search_word = any(w in block_text_lower for w in search_words)
        if phrases:
            has_search_word = has_search_word or all(p in block_text_lower for p in phrases)
        
        if not has_search_word:
                continue
            
        before = content_with_newlines[:start]
        section = ''
        section_match = list(re.finditer(r'^# ([^\n]+)', before, re.MULTILINE))
        if section_match:
            last_section = section_match[-1]
            section_text = last_section.group(1).strip()
            if section_text.endswith('.'):
                section_text = section_text[:-1].strip()
            section = section_text
        
        processed_blocks.add(number)
        fragment = {
            'source': doc,
            'section': section,
            'text': block_text,
            'rule_number': number,
            'rule_label': '',
            'found_words': search_words if search_words else [],
            'found_phrases': phrases if phrases else [],
            '_position': start,
        }
        fragments.append(fragment)
        print(f"[DEBUG] Фрагмент из технических требований: номер={number}, позиция={start}, раздел={section}, текст (первые 100 символов)={block_text[:100]}")
        
        if len(fragments) >= max_fragments:
            return fragments
    
    return fragments


def _collect_fragments_corona_rules(content, doc, search_words, phrases, max_fragments, fragments, processed_blocks):
    """
    Специализированная логика для 2.1.2_Правила игры Корона_structured.txt
    Сохраняет текущую работающую логику для этого документа
    """
    # Подготавливаем контент для поиска
    content_with_newlines = content.replace('###', '\n###')
    if not content_with_newlines.startswith('\n'):
        content_with_newlines = '\n' + content_with_newlines
        
    # ШАГ 1: Находим все релевантные фрагменты
    content_lower = content_with_newlines.lower()
    relevant_positions = []
    
    if search_words:
        for word in search_words:
            pos = 0
            while True:
                pos = content_lower.find(word, pos)
                if pos == -1:
                    break
                relevant_positions.append(pos)
                pos += len(word)
    
    if phrases:
        for phrase in phrases:
            pos = 0
            while True:
                pos = content_lower.find(phrase, pos)
                if pos == -1:
                    break
                relevant_positions.append(pos)
                pos += len(phrase)
    
    if not relevant_positions:
        return fragments
    
    relevant_positions = sorted(set(relevant_positions))
    
    # ШАГ 2: Для каждой релевантной позиции находим ближайший номер пункта/подпункта СВЕРХУ
    point_pattern = re.compile(r'(?:^|\n)(\d{1,2}(?:\.\d+)*\.)\s+')
    all_points = list(point_pattern.finditer(content_with_newlines))
    
    for rel_pos in relevant_positions:
        before_rel_pos = content_with_newlines[:rel_pos]
        section_match_rel = list(re.finditer(r'^# ([^\n]+)', before_rel_pos, re.MULTILINE))
        rel_section = section_match_rel[-1].group(1).strip() if section_match_rel else ''
        
        section_start = 0
        if section_match_rel:
            section_start = section_match_rel[-1].start(0)
        
        section_end = len(content_with_newlines)
        next_section_match = re.search(r'^# ', content_with_newlines[rel_pos:], re.MULTILINE)
        if next_section_match:
            section_end = rel_pos + next_section_match.start()
        
        nearest_point = None
        nearest_point_pos = -1
        
        for point_match in all_points:
            point_pos = point_match.start(1)
            if point_pos <= rel_pos and point_pos >= section_start:
                before_point = content_with_newlines[:point_pos]
                point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                
                if point_section == rel_section:
                    if point_pos > nearest_point_pos:
                        nearest_point_pos = point_pos
                        nearest_point = point_match
        
        if not nearest_point:
                continue
            
        number = nearest_point.group(1).strip()
        if number in processed_blocks:
            continue
        
        number_start = nearest_point.start(1)
        point_level = len(number.rstrip('.').split('.'))
        
        found_subpoint = None
        found_subpoint_pos = -1
        next_same_level_pos = section_end
        
        for point_match in all_points:
            point_pos = point_match.start(1)
            if point_pos > number_start and point_pos < section_end:
                point_number = point_match.group(1).strip()
                point_number_level = len(point_number.rstrip('.').split('.'))
                
                before_next = content_with_newlines[:point_pos]
                next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                
                if next_section == rel_section:
                    if point_number_level <= point_level:
                        if next_same_level_pos == section_end or point_pos < next_same_level_pos:
                            next_same_level_pos = point_pos
                    elif point_number_level > point_level:
                        if point_number.startswith(number.rstrip('.') + '.'):
                            if point_pos <= rel_pos:
                                if point_pos > found_subpoint_pos:
                                    found_subpoint = point_match
                                    found_subpoint_pos = point_pos
        
        original_number = number
        has_subpoints = False
        first_subpoint_pos = section_end
        
        for point_match in all_points:
            point_pos = point_match.start(1)
            if point_pos > number_start and point_pos < next_same_level_pos:
                point_number = point_match.group(1).strip()
                point_number_level = len(point_number.rstrip('.').split('.'))
                
                before_next = content_with_newlines[:point_pos]
                next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                
                if next_section == rel_section:
                    if point_number_level > point_level:
                        if point_number.startswith(number.rstrip('.') + '.'):
                            has_subpoints = True
                            if point_pos < first_subpoint_pos:
                                first_subpoint_pos = point_pos
                    break
            
        if has_subpoints and rel_pos < first_subpoint_pos:
            processed_blocks.add(original_number)
            continue
        
        if found_subpoint:
            number = found_subpoint.group(1).strip()
            number_start = found_subpoint.start(1)
            nearest_point = found_subpoint
            if original_number not in processed_blocks:
                processed_blocks.add(original_number)
        
        if number in processed_blocks:
            continue
        
        line_start = content_with_newlines.rfind('\n', 0, number_start) + 1
        if line_start == 0 and not content_with_newlines.startswith('\n'):
            line_start = 0
        
        line_with_number = content_with_newlines[line_start:number_start + len(number) + 10]
        if not line_with_number.strip().startswith(number):
            number_pos_in_line = line_with_number.find(number)
            if number_pos_in_line >= 0:
                line_start = line_start + number_pos_in_line
            else:
                continue
            
        start = line_start
        end = section_end
        for point_match in all_points:
            point_pos = point_match.start(1)
            if point_pos > start and point_pos < section_end:
                before_next = content_with_newlines[:point_pos]
                next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                if next_section == rel_section:
                    end = point_pos
                    break
        
        block_text = content_with_newlines[start:end].strip()
        
        if start < section_start:
            continue
        
        section_markers_in_block = list(re.finditer(r'^# ', block_text, re.MULTILINE))
        if section_markers_in_block and section_markers_in_block[0].start() > 0:
            continue
        
        lines = block_text.split('\n')
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith(number + ' '):
                pass
            elif number in first_line:
                number_pos_in_first = first_line.find(number)
                if number_pos_in_first > 0:
                    text_before_number = first_line[:number_pos_in_first].strip()
                    if text_before_number:
                        same_number_pattern = re.compile(r'^' + re.escape(number) + r'\s+')
                        same_number_before = same_number_pattern.match(text_before_number)
                        if same_number_before:
                            continue
                        other_number_match = re.search(r'(\d{1,2}(?:\.\d+)*\.)\s+', text_before_number)
                        if other_number_match:
                            continue
                    first_line = first_line[number_pos_in_first:].strip()
                    lines[0] = first_line
                    block_text = '\n'.join(lines).strip()
                else:
                    continue
            else:
                continue
        
        if not block_text.startswith(number):
            number_pos = block_text.find(number)
            if number_pos >= 0:
                text_before = block_text[:number_pos].strip()
                if text_before:
                    other_number_match = re.search(r'(\d{1,2}(?:\.\d+)*\.)\s+', text_before)
                    if other_number_match:
                        continue
                block_text = block_text[number_pos:].strip()
            else:
                continue
        
        first_line_final = block_text.split('\n')[0].strip()
        if not first_line_final.startswith(number):
            continue
        
        block_text_lower = block_text.lower()
        has_search_word = False
        if search_words:
            has_search_word = any(w in block_text_lower for w in search_words)
        if phrases:
            has_search_word = has_search_word or all(p in block_text_lower for p in phrases)
        
        if not has_search_word:
            continue
        
        before = content_with_newlines[:start]
        section = ''
        section_match = list(re.finditer(r'^# ([^\n]+)', before, re.MULTILINE))
        if section_match:
            last_section = section_match[-1]
            section_text = last_section.group(1).strip()
            if section_text.endswith('.'):
                section_text = section_text[:-1].strip()
            section = section_text
        
        processed_blocks.add(number)
        fragment = {
                        'source': doc,
                        'section': section,
                        'text': block_text,
            'rule_number': number,
                        'rule_label': '',
                        'found_words': search_words if search_words else [],
                        'found_phrases': phrases if phrases else [],
            '_position': start,
        }
        fragments.append(fragment)
        
        if len(fragments) >= max_fragments:
            return fragments
    
    return fragments


def _collect_fragments_international_rules(content, doc, search_words, phrases, max_fragments, fragments, processed_blocks):
    """
    Специализированная логика для 2.1.1_Международные правила_structured.txt
    Полная копия текущей логики для этого документа
    """
    # Подготавливаем контент для поиска
    content_with_newlines = content.replace('###', '\n###')
    if not content_with_newlines.startswith('\n'):
        content_with_newlines = '\n' + content_with_newlines
    
    # ШАГ 1: Находим все релевантные фрагменты
    content_lower = content_with_newlines.lower()
    relevant_positions = []
    
    if search_words:
        for word in search_words:
            word_lower = word.lower()
            # Обычный поиск подстроки
            pos = 0
            while True:
                pos = content_lower.find(word_lower, pos)
                if pos == -1:
                    break
                relevant_positions.append(pos)
                pos += len(word_lower)
    
    if phrases:
        for phrase in phrases:
            pos = 0
            while True:
                pos = content_lower.find(phrase, pos)
                if pos == -1:
                    break
                relevant_positions.append(pos)
                pos += len(phrase)
    
    if not relevant_positions:
        return fragments
    
    relevant_positions = sorted(set(relevant_positions))
    
    # ШАГ 2: Для каждой релевантной позиции находим ближайший номер пункта/подпункта СВЕРХУ
    point_pattern = re.compile(r'(?:^|\n)(\d{1,2}(?:\.\d+)*\.)\s+')
    all_points = list(point_pattern.finditer(content_with_newlines))
    
    for rel_pos in relevant_positions:
        before_rel_pos = content_with_newlines[:rel_pos]
        section_match_rel = list(re.finditer(r'^# ([^\n]+)', before_rel_pos, re.MULTILINE))
        rel_section = section_match_rel[-1].group(1).strip() if section_match_rel else ''
        
        section_start = 0
        if section_match_rel:
            section_start = section_match_rel[-1].start(0)
        
        section_end = len(content_with_newlines)
        next_section_match = re.search(r'^# ', content_with_newlines[rel_pos:], re.MULTILINE)
        if next_section_match:
            section_end = rel_pos + next_section_match.start()
        
        # КРИТИЧНО: Сначала ищем подпункты, которые содержат релевантную позицию
        # Это важно, чтобы приоритет был у подпунктов, а не у родительских пунктов
        found_subpoint_for_rel = None
        found_subpoint_for_rel_pos = -1
        
        for point_match in all_points:
            point_pos = point_match.start(1)
            point_number = point_match.group(1).strip()
            point_level = len(point_number.rstrip('.').split('.'))
            
            # Ищем только подпункты (уровень > 1)
            if point_level > 1 and point_pos >= section_start and point_pos < section_end:
                before_point = content_with_newlines[:point_pos]
                point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                
                if point_section == rel_section:
                    # Находим конец этого подпункта
                    # Сначала проверяем, есть ли список в подпункте (элементы, начинающиеся с "-")
                    # Если есть список, конец подпункта определяется по последнему элементу списка, который заканчивается на "."
                    subpoint_end = section_end
                    
                    # Ищем список в подпункте (элементы, начинающиеся с "-")
                    list_end_pos = -1
                    text_after_subpoint = content_with_newlines[point_pos:]
                    
                    # Ищем все элементы списка более гибко - учитываем многострочные элементы
                    # Элемент списка начинается с "-" и заканчивается на ";" или "."
                    # Может быть многострочным (продолжение на следующих строках без "-")
                    lines_after_subpoint = text_after_subpoint.split('\n')
                    current_list_item_start = -1
                    current_list_item_end = -1
                    
                    for i, line in enumerate(lines_after_subpoint):
                        stripped_line = line.strip()
                        # Проверяем, начинается ли строка с "-" (элемент списка)
                        if stripped_line.startswith('-'):
                            # Если был предыдущий элемент списка, сохраняем его конец
                            if current_list_item_start >= 0 and current_list_item_end >= 0:
                                # Проверяем, заканчивается ли предыдущий элемент на "."
                                prev_text = '\n'.join(lines_after_subpoint[current_list_item_start:current_list_item_end+1])
                                if prev_text.rstrip().endswith('.'):
                                    # Находим абсолютную позицию конца этого элемента
                                    text_before_lines = lines_after_subpoint[:current_list_item_end+1]
                                    # Вычисляем позицию: начало подпункта + длина всех строк до конца предыдущего элемента
                                    # Учитываем, что каждая строка заканчивается на \n (кроме последней)
                                    total_length = 0
                                    for j, line in enumerate(text_before_lines):
                                        total_length += len(line)
                                        if j < len(text_before_lines) - 1:  # Не последняя строка
                                            total_length += 1  # Добавляем \n
                                    list_item_end_absolute = point_pos + total_length
                                    if list_item_end_absolute < section_end:
                                        list_end_pos = list_item_end_absolute
                            
                            # Начинаем новый элемент списка
                            current_list_item_start = i
                            current_list_item_end = i
                        elif current_list_item_start >= 0:
                            # Продолжение текущего элемента списка (многострочный)
                            current_list_item_end = i
                    
                    # Проверяем последний элемент списка
                    if current_list_item_start >= 0 and current_list_item_end >= 0:
                        last_item_text = '\n'.join(lines_after_subpoint[current_list_item_start:current_list_item_end+1])
                        if last_item_text.rstrip().endswith('.'):
                            # Находим абсолютную позицию конца последнего элемента списка
                            text_before_lines = lines_after_subpoint[:current_list_item_end+1]
                            # Вычисляем позицию: начало подпункта + длина всех строк до конца последнего элемента
                            # Учитываем, что каждая строка заканчивается на \n (кроме последней)
                            total_length = 0
                            for j, line in enumerate(text_before_lines):
                                total_length += len(line)
                                if j < len(text_before_lines) - 1:  # Не последняя строка
                                    total_length += 1  # Добавляем \n
                            list_item_end_absolute = point_pos + total_length
                            if list_item_end_absolute < section_end:
                                list_end_pos = list_item_end_absolute
                    
                    # Ищем следующий пункт того же или более высокого уровня
                    next_point_end = section_end
                    for next_point_match in all_points:
                        next_point_pos = next_point_match.start(1)
                        if next_point_pos > point_pos and next_point_pos < section_end:
                            next_point_number = next_point_match.group(1).strip()
                            next_point_level = len(next_point_number.rstrip('.').split('.'))
                            before_next = content_with_newlines[:next_point_pos]
                            next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                            next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                            if next_section == rel_section:
                                # Если следующий пункт того же или более высокого уровня - это конец подпункта
                                if next_point_level <= point_level:
                                    next_point_end = next_point_pos
                                    break
                    
                    # Используем более ранний конец (либо конец списка, либо следующий пункт)
                    if list_end_pos > 0 and list_end_pos < next_point_end:
                        subpoint_end = list_end_pos
                    else:
                        subpoint_end = next_point_end
                    
                    # КРИТИЧНО: Если subpoint_end равен section_end, это означает, что мы не нашли ни список, ни следующий пункт
                    # В этом случае используем конец раздела, но это может быть неправильно
                    # Лучше использовать позицию следующего пункта 13.2, если он есть
                    if subpoint_end == section_end:
                        # Ищем следующий пункт 13.2 в том же разделе
                        for next_point_match in all_points:
                            next_point_pos = next_point_match.start(1)
                            if next_point_pos > point_pos:
                                next_point_number = next_point_match.group(1).strip()
                                before_next = content_with_newlines[:next_point_pos]
                                next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                                next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                                if next_section == rel_section:
                                    # Проверяем, является ли это пунктом 13.2 (следующим после 13.1)
                                    if next_point_number.startswith('13.') and next_point_number != '13.1.':
                                        subpoint_end = next_point_pos
                                        break
                                    
                    # Проверяем, находится ли релевантная позиция в этом подпункте
                    if point_pos <= rel_pos < subpoint_end:
                        if point_pos > found_subpoint_for_rel_pos:
                            found_subpoint_for_rel = point_match
                            found_subpoint_for_rel_pos = point_pos
        
        # Если нашли подпункт, используем его
        skip_subpoint_check = False
        if found_subpoint_for_rel:
            nearest_point = found_subpoint_for_rel
            nearest_point_pos = found_subpoint_for_rel_pos
            number = found_subpoint_for_rel.group(1).strip()
            number_start = found_subpoint_for_rel.start(1)
            point_level = len(number.rstrip('.').split('.'))
            
            # КРИТИЧНО: Проверяем, не был ли уже обработан этот подпункт
            if number in processed_blocks:
                continue
            
            # Находим родительский пункт и добавляем его в processed_blocks
            parent_number = number.split('.')[0] + '.'
            if parent_number not in processed_blocks:
                processed_blocks.add(parent_number)
            
            # Пропускаем проверку has_subpoints, так как мы уже нашли подпункт
            found_subpoint = None
            next_same_level_pos = section_end
            original_number = parent_number
            has_subpoints = False  # Уже нашли подпункт, пропускаем проверку
            first_subpoint_pos = section_end
            skip_subpoint_check = True  # Флаг для пропуска проверки подпунктов
        else:
            # Если подпункт не найден, ищем обычный пункт
            nearest_point = None
            nearest_point_pos = -1
            has_subpoints = False  # Инициализируем переменную
            first_subpoint_pos = section_end
            
            for point_match in all_points:
                point_pos = point_match.start(1)
                if point_pos <= rel_pos and point_pos >= section_start:
                    before_point = content_with_newlines[:point_pos]
                    point_section_match = list(re.finditer(r'^# ([^\n]+)', before_point, re.MULTILINE))
                    point_section = point_section_match[-1].group(1).strip() if point_section_match else ''
                    
                    if point_section == rel_section:
                        if point_pos > nearest_point_pos:
                            nearest_point_pos = point_pos
                            nearest_point = point_match
            
            if not nearest_point:
                continue
            
            number = nearest_point.group(1).strip()
            if number in processed_blocks:
                continue
            
            number_start = nearest_point.start(1)
            point_level = len(number.rstrip('.').split('.'))
            
            # Проверяем, есть ли подпункты у найденного пункта
            found_subpoint = None
            found_subpoint_pos = -1
            next_same_level_pos = section_end
            
            for point_match in all_points:
                point_pos = point_match.start(1)
                if point_pos > number_start and point_pos < section_end:
                    point_number = point_match.group(1).strip()
                    point_number_level = len(point_number.rstrip('.').split('.'))
                    
                    before_next = content_with_newlines[:point_pos]
                    next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                    next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                    
                    if next_section == rel_section:
                        if point_number_level <= point_level:
                            if next_same_level_pos == section_end or point_pos < next_same_level_pos:
                                next_same_level_pos = point_pos
                        elif point_number_level > point_level:
                            if point_number.startswith(number.rstrip('.') + '.'):
                                # Находим конец этого подпункта
                                subpoint_end = section_end
                                for next_point_match in all_points:
                                    next_point_pos = next_point_match.start(1)
                                    if next_point_pos > point_pos and next_point_pos < section_end:
                                        next_point_number = next_point_match.group(1).strip()
                                        next_point_level = len(next_point_number.rstrip('.').split('.'))
                                        before_next = content_with_newlines[:next_point_pos]
                                        next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                                        next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                                        if next_section == rel_section:
                                            if next_point_level <= point_number_level:
                                                subpoint_end = next_point_pos
                        break
                
                        # Проверяем, находится ли релевантная позиция в этом подпункте
                        if point_pos <= rel_pos < subpoint_end:
                            if point_pos > found_subpoint_pos:
                                found_subpoint = point_match
                                found_subpoint_pos = point_pos
            
            original_number = number
        
        # Проверяем has_subpoints только если мы не нашли подпункт напрямую
        if not skip_subpoint_check:
            has_subpoints = False
            first_subpoint_pos = section_end
            
            for point_match in all_points:
                point_pos = point_match.start(1)
                if point_pos > number_start and point_pos < next_same_level_pos:
                    point_number = point_match.group(1).strip()
                    point_number_level = len(point_number.rstrip('.').split('.'))
                    
                    before_next = content_with_newlines[:point_pos]
                    next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                    next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                    
                    if next_section == rel_section:
                        if point_number_level > point_level:
                            if point_number.startswith(number.rstrip('.') + '.'):
                                has_subpoints = True
                                if point_pos < first_subpoint_pos:
                                    first_subpoint_pos = point_pos
                                break
            
            if has_subpoints and rel_pos < first_subpoint_pos:
                processed_blocks.add(original_number)
                continue
                                    
        if found_subpoint:
            number = found_subpoint.group(1).strip()
            number_start = found_subpoint.start(1)
            nearest_point = found_subpoint
            if original_number not in processed_blocks:
                processed_blocks.add(original_number)
        
        if number in processed_blocks:
            continue
        
        line_start = content_with_newlines.rfind('\n', 0, number_start) + 1
        if line_start == 0 and not content_with_newlines.startswith('\n'):
            line_start = 0
        
        line_with_number = content_with_newlines[line_start:number_start + len(number) + 10]
        if not line_with_number.strip().startswith(number):
            number_pos_in_line = line_with_number.find(number)
            if number_pos_in_line >= 0:
                line_start = line_start + number_pos_in_line
            else:
                continue
        
        start = line_start
        end = section_end
        
        # КРИТИЧНО: Если подпункт содержит список (элементы, начинающиеся с "-"),
        # конец подпункта определяется по последнему элементу списка, который заканчивается на "."
        # Проверяем, есть ли список в подпункте
        text_after_start = content_with_newlines[start:]
        lines_after_start = text_after_start.split('\n')
        current_list_item_start = -1
        current_list_item_end = -1
        list_end_pos = -1
        
        for i, line in enumerate(lines_after_start):
            stripped_line = line.strip()
            # Проверяем, начинается ли строка с "-" (элемент списка)
            if stripped_line.startswith('-'):
                # Если был предыдущий элемент списка, сохраняем его конец
                if current_list_item_start >= 0 and current_list_item_end >= 0:
                    # Проверяем, заканчивается ли предыдущий элемент на "."
                    prev_text = '\n'.join(lines_after_start[current_list_item_start:current_list_item_end+1])
                    if prev_text.rstrip().endswith('.'):
                        # Находим абсолютную позицию конца этого элемента
                        text_before_lines = lines_after_start[:current_list_item_end+1]
                        # Вычисляем позицию: начало блока + длина всех строк до конца предыдущего элемента
                        # Учитываем, что каждая строка заканчивается на \n (кроме последней)
                        total_length = 0
                        for j, line in enumerate(text_before_lines):
                            total_length += len(line)
                            if j < len(text_before_lines) - 1:  # Не последняя строка
                                total_length += 1  # Добавляем \n
                        list_item_end_absolute = start + total_length
                        if list_item_end_absolute < section_end:
                            list_end_pos = list_item_end_absolute
                
                # Начинаем новый элемент списка
                current_list_item_start = i
                current_list_item_end = i
            elif current_list_item_start >= 0:
                # Продолжение текущего элемента списка (многострочный)
                current_list_item_end = i
        
        # Проверяем последний элемент списка
        if current_list_item_start >= 0 and current_list_item_end >= 0:
            last_item_text = '\n'.join(lines_after_start[current_list_item_start:current_list_item_end+1])
            if last_item_text.rstrip().endswith('.'):
                # Находим абсолютную позицию конца последнего элемента списка
                text_before_lines = lines_after_start[:current_list_item_end+1]
                # Вычисляем позицию: начало блока + длина всех строк до конца последнего элемента
                # Учитываем, что каждая строка заканчивается на \n (кроме последней)
                total_length = 0
                for i, line in enumerate(text_before_lines):
                    total_length += len(line)
                    if i < len(text_before_lines) - 1:  # Не последняя строка
                        total_length += 1  # Добавляем \n
                list_item_end_absolute = start + total_length
                if list_item_end_absolute < section_end:
                    list_end_pos = list_item_end_absolute
        
        if list_end_pos > 0:
            end = list_end_pos
        
        # Если список не найден или не определили конец, ищем следующий пункт
        if end == section_end:
            for point_match in all_points:
                point_pos = point_match.start(1)
                if point_pos > start and point_pos < section_end:
                    before_next = content_with_newlines[:point_pos]
                    next_section_match = list(re.finditer(r'^# ([^\n]+)', before_next, re.MULTILINE))
                    next_section = next_section_match[-1].group(1).strip() if next_section_match else ''
                    if next_section == rel_section:
                        end = point_pos
                        break
        
        block_text = content_with_newlines[start:end].strip()
        
        if start < section_start:
                        continue
                    
        section_markers_in_block = list(re.finditer(r'^# ', block_text, re.MULTILINE))
        if section_markers_in_block and section_markers_in_block[0].start() > 0:
                            continue
                    
        lines = block_text.split('\n')
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith(number + ' '):
                pass
            elif number in first_line:
                number_pos_in_first = first_line.find(number)
                if number_pos_in_first > 0:
                    text_before_number = first_line[:number_pos_in_first].strip()
                    if text_before_number:
                        same_number_pattern = re.compile(r'^' + re.escape(number) + r'\s+')
                        same_number_before = same_number_pattern.match(text_before_number)
                        if same_number_before:
                                continue
                        other_number_match = re.search(r'(\d{1,2}(?:\.\d+)*\.)\s+', text_before_number)
                        if other_number_match:
                                    continue
                    first_line = first_line[number_pos_in_first:].strip()
                    lines[0] = first_line
                    block_text = '\n'.join(lines).strip()
                else:
                                continue
            else:
                    continue
        
        if not block_text.startswith(number):
            number_pos = block_text.find(number)
            if number_pos >= 0:
                text_before = block_text[:number_pos].strip()
                if text_before:
                    other_number_match = re.search(r'(\d{1,2}(?:\.\d+)*\.)\s+', text_before)
                    if other_number_match:
                        continue
                block_text = block_text[number_pos:].strip()
            else:
                continue
        
        first_line_final = block_text.split('\n')[0].strip()
        if not first_line_final.startswith(number):
            continue
        
        block_text_lower = block_text.lower()
        has_search_word = False
        if search_words:
            has_search_word = any(w in block_text_lower for w in search_words)
        if phrases:
            has_search_word = has_search_word or all(p in block_text_lower for p in phrases)
        
        if not has_search_word:
            continue
                        
        before = content_with_newlines[:start]
        section = ''
        section_match = list(re.finditer(r'^# ([^\n]+)', before, re.MULTILINE))
        if section_match:
            last_section = section_match[-1]
            section_text = last_section.group(1).strip()
            if section_text.endswith('.'):
                section_text = section_text[:-1].strip()
            section = section_text
        
        processed_blocks.add(number)
        fragment = {
                        'source': doc,
            'section': section,
                        'text': block_text,
                        'rule_number': number,
                        'rule_label': '',
            'found_words': search_words if search_words else [],
                        'found_phrases': phrases if phrases else [],
            '_position': start,
        }
        fragments.append(fragment)
        
        if len(fragments) >= max_fragments:
            return fragments
    
    return fragments


# Старая логика удалена - теперь используется простая логика:
# 1. Находим релевантные фрагменты (где есть поисковые слова)
# 2. Для каждого фрагмента находим ближайший номер пункта СВЕРХУ
# 3. Извлекаем блок, начиная с этого номера
# 4. Находим раздел для блока
# 5. Сохраняем фрагмент с правильной позицией для сортировки


def get_primary_source_fragments(hits, query, allowed_sources=None, max_fragments=20):
    lwquery = (query or '').lower()
    phrase_matches = re.findall(r"\*([^*]+?)\*", lwquery)
    phrases = []
    for raw in phrase_matches:
        cleaned = re.sub(r"\s+", " ", raw.strip())
        if cleaned and len(cleaned.split()) >= 2:
            phrases.append(cleaned)
    query_without_phrases = re.sub(r"\*[^*]+?\*", " ", lwquery)
    all_words = [w.strip() for w in query_without_phrases.split() if w.strip() and len(w.strip()) > 1]
    # Не фильтруем слова из CONTEXT_ROUTES - они нужны для поиска внутри документа
    # Фильтруем только базовые стоп-слова, которые не являются ключевыми словами контекста
    base_stop_words = {'игра', 'русский', 'бильярд', 'стол', 'общие'}
    search_words = [w for w in all_words if w in CONTEXT_ROUTES or w not in base_stop_words]

    candidate_docs = _collect_candidate_docs(hits, allowed_sources, lwquery)
    if not candidate_docs:
        return []
    return _collect_fragments(candidate_docs, search_words, max_fragments, phrases=phrases)

