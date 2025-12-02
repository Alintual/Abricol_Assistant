"""
Скрипт для переиндексирования базы знаний из существующих structured файлов.

Использование:
    python -m src.rebuild_index

Этот скрипт:
1. Пересобирает индекс полнотекстового поиска из всех существующих structured файлов
2. Обновляет базу знаний knowledge.db

Важно:
- Этот скрипт НЕ создает новые structured файлы из PDF
- Этот скрипт НЕ изменяет содержимое существующих structured файлов
- Он только читает существующие файлы и индексирует их в базу знаний

Для полной пересборки используйте: python -m src.build_kb
"""

import os
import sys
from dotenv import load_dotenv

try:
    from .knowledge import search_store
    from .knowledge.text_search import DATA_DIR
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from knowledge import search_store  # type: ignore
    from knowledge.text_search import DATA_DIR  # type: ignore


STRUCTURED_DIR = os.path.join(DATA_DIR, "structured")
os.makedirs(STRUCTURED_DIR, exist_ok=True)


def rebuild_index() -> None:
    """Пересборка индекса полнотекстового поиска из всех существующих structured файлов.

    ВАЖНО: Файлы НЕ изменяются, только читаются и индексируются.
    """
    print("\n=== Пересборка индекса полнотекстового поиска ===")

    if not os.path.exists(STRUCTURED_DIR):
        print(f"[ERROR] Директория со структурированными текстами не найдена: {STRUCTURED_DIR}")
        return

    # Проверяем наличие structured файлов
    structured_files = [f for f in os.listdir(STRUCTURED_DIR) if f.endswith("_structured.txt")]

    if not structured_files:
        print(f"[WARNING] Не найдено структурированных файлов в {STRUCTURED_DIR}")
        print("Для создания structured файлов запустите: python -m src.build_kb")
        return

    print(f"[INFO] Найдено структурированных файлов: {len(structured_files)}")
    for filename in sorted(structured_files):
        filepath = os.path.join(STRUCTURED_DIR, filename)
        size = os.path.getsize(filepath)
        print(f"  - {filename} ({size} байт)")

    # Пересобираем индекс
    search_store.build_index()
    print("\n[SUCCESS] Индекс полнотекстового поиска пересобран успешно")


def main() -> None:
    """Основная функция: выполняет переиндексирование без изменения файлов."""
    load_dotenv()

    print("=" * 60)
    print("Переиндексирование базы знаний")
    print("=" * 60)
    print("\nЭтот скрипт:")
    print("  ✓ Читает существующие structured файлы")
    print("  ✓ Индексирует их в базу знаний")
    print("  ✗ НЕ создает новые файлы из PDF")
    print("  ✗ НЕ изменяет содержимое существующих файлов")
    print("\nДля полной пересборки используйте: python -m src.build_kb")
    print()

    # Пересборка индекса (без изменения файлов)
    rebuild_index()

    print("\n" + "=" * 60)
    print("Готово! База знаний переиндексирована.")
    print(f"База данных: knowledge.db")
    print("=" * 60)


if __name__ == "__main__":
    main()

