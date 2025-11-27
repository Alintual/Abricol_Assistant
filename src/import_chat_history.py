"""
Утилита для импорта истории чата из JSON файла.

Формат JSON файла:
[
    {
        "tg_user_id": 123456789,
        "messages": [
            {"role": "user", "content": "Привет", "timestamp": "2024-01-01T12:00:00"},
            {"role": "assistant", "content": "Привет! Чем могу помочь?", "timestamp": "2024-01-01T12:00:01"}
        ]
    },
    ...
]

Или альтернативный формат (плоский список сообщений):
[
    {"tg_user_id": 123456789, "role": "user", "content": "Привет", "timestamp": "2024-01-01T12:00:00"},
    {"tg_user_id": 123456789, "role": "assistant", "content": "Привет! Чем могу помочь?", "timestamp": "2024-01-01T12:00:01"}
]

Использование:
    python -m src.import_chat_history path/to/chat_history.json
    python src/import_chat_history.py path/to/chat_history.json
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

from .db.session import get_session, init_engine_and_db
from .db.models import ChatMessage
from sqlalchemy import delete, select


async def import_chat_history(file_path: str, clear_existing: bool = False) -> None:
    """
    Импортирует историю чата из JSON файла.
    
    Args:
        file_path: Путь к JSON файлу с историей чата
        clear_existing: Если True, удаляет существующие сообщения перед импортом
    """
    load_dotenv()
    await init_engine_and_db()
    
    path = Path(file_path)
    if not path.exists():
        print(f"❌ Файл не найден: {file_path}")
        return
    
    print(f"📂 Чтение файла: {file_path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON: {e}")
        return
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return
    
    # Определяем формат данных
    if not isinstance(data, list):
        print("❌ JSON должен содержать массив объектов")
        return
    
    if not data:
        print("⚠️ Файл пуст")
        return
    
    # Проверяем формат: если первый элемент имеет ключ "messages", это группированный формат
    is_grouped = isinstance(data[0], dict) and "messages" in data[0]
    
    messages_to_import: List[Dict[str, Any]] = []
    
    if is_grouped:
        # Группированный формат: {tg_user_id, messages: [...]}
        print("📋 Обнаружен группированный формат")
        for group in data:
            if not isinstance(group, dict) or "tg_user_id" not in group or "messages" not in group:
                print(f"⚠️ Пропущена некорректная группа: {group}")
                continue
            tg_user_id = group["tg_user_id"]
            for msg in group["messages"]:
                if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                    continue
                messages_to_import.append({
                    "tg_user_id": tg_user_id,
                    "role": msg["role"],
                    "content": msg["content"],
                    "timestamp": msg.get("timestamp")
                })
    else:
        # Плоский формат: список сообщений с tg_user_id в каждом
        print("📋 Обнаружен плоский формат")
        for msg in data:
            if not isinstance(msg, dict) or "tg_user_id" not in msg or "role" not in msg or "content" not in msg:
                print(f"⚠️ Пропущено некорректное сообщение: {msg}")
                continue
            messages_to_import.append({
                "tg_user_id": msg["tg_user_id"],
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": msg.get("timestamp")
            })
    
    if not messages_to_import:
        print("⚠️ Нет сообщений для импорта")
        return
    
    print(f"📊 Найдено сообщений: {len(messages_to_import)}")
    
    # Если нужно очистить существующие сообщения
    if clear_existing:
        async for session in get_session():
            try:
                result = await session.execute(delete(ChatMessage))
                await session.commit()
                deleted = result.rowcount if hasattr(result, 'rowcount') else 0
                print(f"🗑️ Удалено существующих сообщений: {deleted}")
            except Exception as e:
                await session.rollback()
                print(f"⚠️ Ошибка при удалении сообщений: {e}")
            break
    
    # Импортируем сообщения
    imported = 0
    skipped = 0
    
    async for session in get_session():
        try:
            for msg_data in messages_to_import:
                try:
                    # Парсим timestamp если есть
                    created_at = datetime.utcnow()
                    if msg_data.get("timestamp"):
                        try:
                            if isinstance(msg_data["timestamp"], str):
                                # Пробуем разные форматы
                                for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
                                    try:
                                        created_at = datetime.strptime(msg_data["timestamp"], fmt)
                                        break
                                    except ValueError:
                                        continue
                            elif isinstance(msg_data["timestamp"], (int, float)):
                                created_at = datetime.fromtimestamp(msg_data["timestamp"])
                        except Exception:
                            pass  # Используем текущее время
                    
                    # Проверяем, не существует ли уже такое сообщение (по timestamp и content)
                    existing = await session.execute(
                        select(ChatMessage).where(
                            ChatMessage.tg_user_id == msg_data["tg_user_id"],
                            ChatMessage.content == msg_data["content"],
                            ChatMessage.created_at == created_at
                        )
                    )
                    if existing.scalar_one_or_none():
                        skipped += 1
                        continue
                    
                    # Создаём новое сообщение
                    chat_msg = ChatMessage(
                        tg_user_id=msg_data["tg_user_id"],
                        role=msg_data["role"],
                        content=msg_data["content"],
                        created_at=created_at
                    )
                    session.add(chat_msg)
                    imported += 1
                    
                except Exception as e:
                    print(f"⚠️ Ошибка при импорте сообщения: {e}")
                    skipped += 1
                    continue
            
            await session.commit()
            print(f"✅ Импортировано сообщений: {imported}")
            if skipped > 0:
                print(f"⏭️ Пропущено (дубликаты): {skipped}")
            
        except Exception as e:
            await session.rollback()
            print(f"❌ Ошибка при сохранении: {e}")
            raise
        break


async def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python -m src.import_chat_history <путь_к_json_файлу> [--clear]")
        print("\nОпции:")
        print("  --clear  Удалить существующие сообщения перед импортом")
        sys.exit(1)
    
    file_path = sys.argv[1]
    clear_existing = "--clear" in sys.argv
    
    await import_chat_history(file_path, clear_existing=clear_existing)


if __name__ == "__main__":
    asyncio.run(main())

