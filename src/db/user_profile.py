"""Функции для работы с профилем пользователя (глобальные переменные)"""
import logging
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .session import get_session
from .models import UserProfile

logger = logging.getLogger(__name__)


async def get_user_profile(tg_user_id: int) -> UserProfile | None:
    """Получить профиль пользователя или None, если не существует"""
    async for session in get_session():
        result = await session.execute(
            select(UserProfile).where(UserProfile.tg_user_id == tg_user_id)
        )
        profile = result.scalar_one_or_none()
        return profile


async def reset_user_profile_fields(tg_user_id: int) -> UserProfile:
    """
    Обнулить все поля профиля пользователя (кроме tg_user_id и name_sys).
    Вызывается при показе окна выбора намерения.
    """
    async for session in get_session():
        result = await session.execute(
            select(UserProfile).where(UserProfile.tg_user_id == tg_user_id)
        )
        profile = result.scalar_one_or_none()
        
        if profile is None:
            profile = UserProfile(tg_user_id=tg_user_id)
            session.add(profile)
        
        # Сохраняем name_sys перед обнулением
        saved_name_sys = profile.name_sys or ""
        
        # Обнуляем все поля (кроме tg_user_id и name_sys)
        profile.date = datetime.utcnow()
        profile.status = ""
        profile.name = ""
        profile.phone = ""
        profile.exp = ""
        profile.level = ""
        profile.goals = ""
        profile.before = ""
        profile.politic = ""
        profile.name_sys = saved_name_sys  # Восстанавливаем name_sys
        
        await session.commit()
        await session.refresh(profile)
        logger.info(f"Обнулены все поля профиля для пользователя {tg_user_id} (кроме name_sys)")
        
        return profile


async def check_status_changed(tg_user_id: int, new_status: str) -> bool:
    """
    Проверить, изменился ли статус пользователя.
    Возвращает True, если статус изменился, False - если остался прежним.
    """
    async for session in get_session():
        result = await session.execute(
            select(UserProfile).where(UserProfile.tg_user_id == tg_user_id)
        )
        profile = result.scalar_one_or_none()
        
        if profile is None:
            # Если профиля нет, считаем что статус изменился (новый статус)
            return True
        
        old_status = (profile.status or "").strip()
        new_status_stripped = new_status.strip()
        
        # Статус изменился, если он отличается от старого
        # Или если старый статус был пустым/Читатель, а новый - лид-статус
        is_lead_status = new_status_stripped in ("Обучение", "Консультация")
        changed = (
            old_status != new_status_stripped or
            (old_status in ("", "Читатель") and is_lead_status)
        )
        
        logger.info(
            f"Проверка изменения статуса для пользователя {tg_user_id}: "
            f"old_status='{old_status}', new_status='{new_status_stripped}', changed={changed}"
        )
        
        return changed


async def get_or_create_user_profile(tg_user_id: int, name_sys: str = "") -> UserProfile:
    """Получить профиль пользователя или создать новый"""
    async for session in get_session():
        result = await session.execute(
            select(UserProfile).where(UserProfile.tg_user_id == tg_user_id)
        )
        profile = result.scalar_one_or_none()
        
        if profile is None:
            profile = UserProfile(
                tg_user_id=tg_user_id,
                date=datetime.utcnow(),
                status="Читатель",
                name_sys=name_sys or "",
            )
            session.add(profile)
            await session.commit()
            await session.refresh(profile)
            logger.info(f"Создан новый профиль для пользователя {tg_user_id}")
        else:
            # Обновляем дату последнего обращения и name_sys, если передан
            profile.date = datetime.utcnow()
            if name_sys and not profile.name_sys:
                profile.name_sys = name_sys
            await session.commit()
            await session.refresh(profile)
        
        return profile


async def update_user_profile(
    tg_user_id: int,
    date: datetime | None = None,
    status: str | None = None,
    name: str | None = None,
    name_sys: str | None = None,
    phone: str | None = None,
    exp: str | None = None,
    level: str | None = None,
    goals: str | None = None,
    before: str | None = None,
    politic: str | None = None,
) -> UserProfile:
    """Обновить профиль пользователя"""
    async for session in get_session():
        # Получаем или создаем профиль
        result = await session.execute(
            select(UserProfile).where(UserProfile.tg_user_id == tg_user_id)
        )
        profile = result.scalar_one_or_none()
        
        if profile is None:
            profile = UserProfile(tg_user_id=tg_user_id)
            session.add(profile)
        
        # Сохраняем старые значения для проверки изменения (до обновления)
        old_status = (profile.status or "").strip()
        old_name = (profile.name or "").strip()
        old_phone = (profile.phone or "").strip()
        old_exp = (profile.exp or "").strip()
        old_level = (profile.level or "").strip()
        old_goals = (profile.goals or "").strip()
        old_before = (profile.before or "").strip()
        old_politic = (profile.politic or "").strip()
        logger.info(f"Профиль пользователя {tg_user_id}: old_status='{old_status}', передано status={status}")
        
        # Обновляем только переданные поля
        if date is not None:
            profile.date = date
        if status is not None:
            profile.status = status
        if name is not None:
            profile.name = name
        if name_sys is not None:
            profile.name_sys = name_sys
        if phone is not None:
            profile.phone = phone
        if exp is not None:
            profile.exp = exp
        if level is not None:
            profile.level = level
        if goals is not None:
            profile.goals = goals
        if before is not None:
            profile.before = before
        if politic is not None:
            profile.politic = politic
        
        # Всегда обновляем дату последнего обращения
        profile.date = datetime.utcnow()
        
        await session.commit()
        await session.refresh(profile)
        logger.info(f"Обновлен профиль пользователя {tg_user_id}: status={status}, name={name}, phone={phone}")
        
        # Сохранение в Excel больше не происходит автоматически
        # Оно происходит только явно в нужных местах (блок Записи)
        
        return profile

