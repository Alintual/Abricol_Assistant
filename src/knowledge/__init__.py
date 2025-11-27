"""
Модуль для работы с базой знаний.

Использует полнотекстовый поиск (SQLite FTS) вместо векторной базы для более надежного поиска.
"""

# Экспортируем text_search под именем search_store
from . import text_search as search_store
from . import image_mapper

__all__ = ['search_store', 'image_mapper']

