"""
Скрипт для обработки и структурирования PDF файлов из базы знаний.

Использование:
    python -m src.process_pdf 1.1_Общая информация.pdf
"""

import os
import sys
import re
from pypdf import PdfReader
from typing import List, Tuple

try:
    from .knowledge.text_search import DATA_DIR
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from knowledge.text_search import DATA_DIR


def extract_pdf_text(file_path: str) -> str:
    """Извлекает текст из PDF файла."""
    reader = PdfReader(file_path)
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def _join_section(lines: List[Tuple[str, bool]]) -> str:
    if not lines:
        return ""
    result, prev_had_space = lines[0]
    for text, had_space in lines[1:]:
        if result.endswith('-'):
            result = result[:-1] + text
        elif prev_had_space:
            result += " " + text
        else:
            result += text
        prev_had_space = had_space
    return result


def structure_text(text: str) -> str:
    """Структурирует извлечённый текст из PDF."""
    if not text.strip():
        return ""
    lines = text.split("\n")
    structured: list[str] = []
    current_section: list[tuple[str, bool]] = []
    for raw_line in lines:
        stripped = raw_line.rstrip("\n\r")
        had_trailing_space = bool(stripped) and stripped.endswith(" ")
        line = stripped.strip()
        if not line:
            if current_section:
                structured.append(_join_section(current_section))
                current_section = []
            continue
        is_header = (
            len(line) < 80 and (
                line.isupper()
                or re.match(r"^\d+[\.\)]\s+[А-ЯЁ]", line)
                or re.match(r"^[А-ЯЁ][а-яё\s]{0,50}:?$", line)
                or (line.endswith(':') and len(line) < 60)
            )
        )
        if is_header and current_section:
            structured.append(_join_section(current_section))
            current_section = []
            structured.append(f"\n### {line}\n")
        elif is_header:
            structured.append(f"\n### {line}\n")
        else:
            current_section.append((line, had_trailing_space))
    if current_section:
        structured.append(_join_section(current_section))
    result = "\n".join(structured)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"[ ]{2,}", " ", result)
    result = re.sub(r"\s+([.,;:!?])", r"\1", result)
    result = re.sub(r"([.,;:!?])\s+", r"\1 ", result)
    result = re.sub(r"\s+-\s+([А-Яа-яЁёA-Za-z])", r"-\1", result)
    return result.strip()


def extract_and_structure_pdf(pdf_filename: str) -> str:
    """Извлекает текст из PDF и структурирует его."""
    pdf_path = os.path.join(DATA_DIR, pdf_filename)
    
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Файл не найден: {pdf_path}")
    
    # Извлекаем весь текст
    raw_text = extract_pdf_text(pdf_path)
    
    # Получаем название из имени файла
    title = pdf_filename.replace(".pdf", "").replace("_", " ")
    
    # Структурируем текст
    structured_text = structure_text(raw_text)
    
    # Добавляем заголовок
    result = f"# {title}\n\n{structured_text}"
    
    return result


def save_structured_text(pdf_filename: str, structured_text: str) -> str:
    """Сохраняет структурированный текст в файл."""
    output_filename = pdf_filename.replace(".pdf", "_structured.txt")
    output_path = os.path.join(DATA_DIR, output_filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(structured_text)
    
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python -m src.process_pdf <имя_файла.pdf>")
        sys.exit(1)
    
    pdf_filename = sys.argv[1]
    if not pdf_filename.endswith(".pdf"):
        pdf_filename += ".pdf"
    
    try:
        print(f"Обработка файла: {pdf_filename}")
        structured_text = extract_and_structure_pdf(pdf_filename)
        output_path = save_structured_text(pdf_filename, structured_text)
        print(f"Структурированный текст сохранён в: {output_path}")
        print(f"\nПервые 500 символов:\n{structured_text[:500]}...")
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

