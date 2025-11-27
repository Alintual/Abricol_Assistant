from typing import List, Dict

from sqlalchemy import select, desc

from .session import get_session
from .models import ChatMessage


async def get_chat_history(user_id: int, limit: int = 10) -> List[Dict]:
    """Возвращает последние N сообщений истории чата пользователя."""
    history: List[Dict] = []
    async for session in get_session():
        try:
            result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.tg_user_id == user_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(limit)
            )
            messages = result.scalars().all()
            for msg in reversed(messages):
                history.append({"role": msg.role, "content": msg.content})
            break
        except Exception:
            # Тихий фолбэк — просто возвращаем, не прерывая работу бота
            break
    return history


async def save_chat_message(user_id: int, role: str, content: str) -> None:
    """Сохраняет одно сообщение в историю чата."""
    async for session in get_session():
        try:
            chat_msg = ChatMessage(
                tg_user_id=user_id,
                role=role,
                content=content,
            )
            session.add(chat_msg)
            await session.commit()
            break
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            break


