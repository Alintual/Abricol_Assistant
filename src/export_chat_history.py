"""
Утилита для экспорта истории чата из базы данных в JSON файл.

Использование:
    python -m src.export_chat_history [output_file.json] [--user-id USER_ID]
    python src/export_chat_history.py [output_file.json] [--user-id USER_ID]

Опции:
    output_file.json  Путь к выходному JSON файлу (по умолчанию: chat_history_export.json)
    --user-id USER_ID  Экспортировать историю только для конкретного пользователя
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import select, desc

from .db.session import get_session, init_engine_and_db
from .db.models import ChatMessage


async def export_chat_history(
    output_file: str = "chat_history_export.json",
    user_id: Optional[int] = None
) -> None:
    """
    Экспортирует историю чата из базы данных в JSON файл.
    
    Args:
        output_file: Путь к выходному JSON файлу
        user_id: Если указан, экспортирует только историю этого пользователя
    """
    load_dotenv()
    await init_engine_and_db()
    
    print(f"📂 Экспорт истории чата в: {output_file}")
    
    # Получаем все сообщения из базы
    messages_data = []
    async for session in get_session():
        try:
            query = select(ChatMessage).order_by(ChatMessage.tg_user_id, ChatMessage.created_at)
            
            if user_id:
                query = query.where(ChatMessage.tg_user_id == user_id)
                print(f"👤 Фильтр по user_id: {user_id}")
            
            result = await session.execute(query)
            messages = result.scalars().all()
            
            if not messages:
                print("⚠️ История чата пуста")
                return
            
            print(f"📊 Найдено сообщений: {len(messages)}")
            
            # Группируем по пользователям
            grouped_by_user: dict[int, list] = {}
            
            for msg in messages:
                if msg.tg_user_id not in grouped_by_user:
                    grouped_by_user[msg.tg_user_id] = []
                
                grouped_by_user[msg.tg_user_id].append({
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None
                })
            
            # Формируем итоговую структуру (группированный формат)
            for tg_user_id, msgs in grouped_by_user.items():
                messages_data.append({
                    "tg_user_id": tg_user_id,
                    "messages": msgs
                })
            
            break
        except Exception as e:
            print(f"❌ Ошибка при чтении из базы: {e}")
            return
    
    # Сохраняем в JSON файл
    try:
        output_path = Path(output_file)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(messages_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ История экспортирована: {output_file}")
        print(f"📊 Пользователей: {len(messages_data)}")
        total_messages = sum(len(g["messages"]) for g in messages_data)
        print(f"📊 Всего сообщений: {total_messages}")
        
    except Exception as e:
        print(f"❌ Ошибка при сохранении файла: {e}")


async def main() -> None:
    output_file = "chat_history_export.json"
    user_id: Optional[int] = None
    
    # Парсим аргументы
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--user-id" and i + 1 < len(args):
            try:
                user_id = int(args[i + 1])
                i += 2
            except ValueError:
                print("❌ --user-id должен быть числом")
                sys.exit(1)
        elif not arg.startswith("--"):
            output_file = arg
            i += 1
        else:
            i += 1
    
    await export_chat_history(output_file, user_id)


if __name__ == "__main__":
    asyncio.run(main())

