from aiogram import Dispatcher, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from sqlalchemy import insert
import logging

from ..db.session import get_session
from ..db.chat_history import save_chat_message
from ..db.models import Lead


router = Router()
logger = logging.getLogger(__name__)


class BookingStates(StatesGroup):
    """Фаза 2: Анкетирование"""
    exp = State()  # Опыт игры
    level = State()  # Уровень подготовки
    goals = State()  # Цели обучения
    before = State()  # Учились ли ранее в «Абриколь»
    # Фаза 3: Запись
    name = State()  # Имя
    phone = State()  # Телефон


@router.message(F.text == "📝 Запись на обучение")
async def booking_start(message: Message, state: FSMContext) -> None:
    """Начало Фазы 2: Анкетирование"""
    logger.info(f"Получена кнопка 'Запись на обучение' от пользователя {message.from_user.id if message.from_user else 'unknown'}")
    # Сохраняем сообщение пользователя и ответ ассистента
    if message.from_user:
        await save_chat_message(message.from_user.id, "user", message.text or "")
    await message.answer("Проведём небольшое анкетирование.")
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", "Проведём небольшое анкетирование.")
    await state.set_state(BookingStates.exp)
    logger.info(f"Установлено состояние BookingStates.exp (Фаза 2)")
    await message.answer("Какой у Вас опыт игры?")
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", "Какой у Вас опыт игры?")


@router.message(BookingStates.exp)
async def booking_exp(message: Message, state: FSMContext) -> None:
    """Вопрос 1: Опыт игры"""
    logger.info(f"Получен ответ на вопрос об опыте: {message.text}")
    await state.update_data(exp=(message.text or "").strip())
    if message.from_user:
        await save_chat_message(message.from_user.id, "user", message.text or "")
    await state.set_state(BookingStates.level)
    logger.info(f"Установлено состояние BookingStates.level")
    await message.answer("Какой уровень подготовки?")
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", "Какой уровень подготовки?")


@router.message(BookingStates.level)
async def booking_level(message: Message, state: FSMContext) -> None:
    """Вопрос 2: Уровень подготовки"""
    logger.info(f"Получен ответ на вопрос об уровне: {message.text}")
    await state.update_data(level=(message.text or "").strip())
    if message.from_user:
        await save_chat_message(message.from_user.id, "user", message.text or "")
    await state.set_state(BookingStates.goals)
    logger.info(f"Установлено состояние BookingStates.goals")
    await message.answer("Какие цели обучения?")
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", "Какие цели обучения?")


@router.message(BookingStates.goals)
async def booking_goals(message: Message, state: FSMContext) -> None:
    """Вопрос 3: Цели обучения"""
    logger.info(f"Получен ответ на вопрос о целях: {message.text}")
    await state.update_data(goals=(message.text or "").strip())
    if message.from_user:
        await save_chat_message(message.from_user.id, "user", message.text or "")
    await state.set_state(BookingStates.before)
    logger.info(f"Установлено состояние BookingStates.before")
    await message.answer("Учились ли ранее в «Абриколь»?")
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", "Учились ли ранее в «Абриколь»?")


@router.message(BookingStates.before)
async def booking_before(message: Message, state: FSMContext) -> None:
    """Вопрос 4: Обучение ранее"""
    logger.info(f"Получен ответ на вопрос об обучении ранее: {message.text}")
    await state.update_data(before=(message.text or "").strip())
    if message.from_user:
        await save_chat_message(message.from_user.id, "user", message.text or "")
    
    # Выводим сводку согласно промпту
    data = await state.get_data()
    summary = f"""✨ Отлично! Вот Ваши ответы:
1. Опыт: {data.get('exp', '—')}
2. Уровень: {data.get('level', '—')}
3. Цель: {data.get('goals', '—')}
4. Обучение ранее: {data.get('before', '—')}"""
    
    await message.answer(summary)
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", summary)
    logger.info("Выведена сводка анкетирования")
    
    # Переход к Фазе 4: Запись
    await message.answer(
        "Вы можете записаться на Обучение или получить Консультацию по телефону ШБ 📱 +7 983 205 2230.\n"
        "ИЛИ просто сообщите Ваше Имя и Номер телефона +7 *** *** **** и Вам перезвонят 👍"
    )
    if message.from_user:
        await save_chat_message(
            message.from_user.id, 
            "assistant", 
            "Вы можете записаться на Обучение или получить Консультацию по телефону ШБ 📱 +7 983 205 2230.\n"
            "ИЛИ просто сообщите Ваше Имя и Номер телефона +7 *** *** **** и Вам перезвонят 👍"
        )
    await state.set_state(BookingStates.name)
    logger.info(f"Переход к Фазе 4: Запись. Установлено состояние BookingStates.name")


@router.message(BookingStates.name)
async def booking_name(message: Message, state: FSMContext) -> None:
    """Фаза 3: Запись - Имя"""
    logger.info(f"Получено имя: {message.text}")
    await state.update_data(name=(message.text or "").strip())
    if message.from_user:
        await save_chat_message(message.from_user.id, "user", message.text or "")
    await state.set_state(BookingStates.phone)
    logger.info(f"Установлено состояние BookingStates.phone")
    await message.answer("Оставьте номер телефона (например, +7XXXXXXXXXX).")
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", "Оставьте номер телефона (например, +7XXXXXXXXXX).")


@router.message(BookingStates.phone)
async def booking_phone(message: Message, state: FSMContext) -> None:
    """Фаза 4: Запись - Телефон с проверкой формата"""
    import re
    
    logger.info(f"Получен телефон: {message.text}")
    phone_text = (message.text or "").strip()
    
    if message.from_user:
        await save_chat_message(message.from_user.id, "user", phone_text)
    
    # Проверка формата телефона
    phone_patterns = [
        r"\+?7\s?[\(]?\d{3}[\)]?\s?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
        r"\+?7\d{10}",
        r"8\s?[\(]?\d{3}[\)]?\s?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
    ]
    
    extracted_phone = None
    for pattern in phone_patterns:
        match = re.search(pattern, phone_text)
        if match:
            extracted_phone = re.sub(r"[\s\-\(\)]", "", match.group(0))
            # Нормализуем формат: +7XXXXXXXXXX
            if extracted_phone.startswith("8"):
                extracted_phone = "+7" + extracted_phone[1:]
            elif not extracted_phone.startswith("+7"):
                extracted_phone = "+7" + extracted_phone
            break
    
    # Если формат не правильный, просим повторить ввод
    if not extracted_phone:
        await message.answer(
            "❌ Формат номера телефона неверный. Пожалуйста, введите номер в формате:\n"
            "+7 *** *** **** или 8 *** *** ****\n"
            "Например: +7 983 205 2230 или 8 983 205 2230"
        )
        if message.from_user:
            await save_chat_message(message.from_user.id, "assistant", "Формат номера телефона неверный. Пожалуйста, повторите ввод.")
        return  # Не переходим дальше, ждем правильный формат
    
    # Сохраняем нормализованный телефон
    await state.update_data(phone=extracted_phone)
    data = await state.get_data()
    
    name = data.get('name', '')
    phone = extracted_phone
    before = data.get('before', '').lower()
    
    # Сохранение в БД
    async for session in get_session():
        stmt = insert(Lead).values(
            tg_user_id=message.from_user.id if message.from_user else 0,
            full_name=name,
            phone=phone,
            goal=data.get('goals', ''),
            preferred_time="",  # Не используется в новой логике
            notes=f"Опыт: {data.get('exp', '')}, Уровень: {data.get('level', '')}, Обучение ранее: {data.get('before', '')}",
        )
        await session.execute(stmt)
        await session.commit()
    
    logger.info("Данные сохранены в БД")
    
    # Ответ согласно промпту
    response = f"{name}, спасибо! Вам перезвонят по {phone}."
    
    # Бонус для новых клиентов
    if "нет" in before or "не" in before or before == "":
        response += "\n\n🎁 Вам полагается приветственный бонус — бесплатный первый урок (2 часа, без аренды стола)."
    
    await message.answer(response)
    if message.from_user:
        await save_chat_message(message.from_user.id, "assistant", response)
    await state.clear()
    logger.info("Фаза 4 завершена, состояние очищено")


def register_booking(dp: Dispatcher) -> None:
    dp.include_router(router)


