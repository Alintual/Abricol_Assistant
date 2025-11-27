"""Обработчик Фазы 2: Политика конфиденциальности"""
import logging
import os
from aiogram import Dispatcher, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode

from ..db.user_profile import get_or_create_user_profile, update_user_profile, get_user_profile
from ..db.chat_history import save_chat_message

router = Router()
logger = logging.getLogger(__name__)

LINKS_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "knowledge", "data", "links.txt")
)


def _load_policy_link() -> str:
    """Загрузить ссылку на Политику конфиденциальности из links.txt"""
    if not os.path.exists(LINKS_FILE_PATH):
        return ""
    try:
        with open(LINKS_FILE_PATH, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if "Политика конфиденциальности" in line and " - " in line:
                    _, url = line.split(" - ", 1)
                    return url.strip()
    except Exception as e:
        logger.error(f"Ошибка при загрузке ссылки на политику: {e}")
    return ""


async def show_policy_window(
    message: Message, 
    state: FSMContext, 
    user_intent: str = "Обучение",
    waiting_sticker_message: Message | None = None
) -> None:
    """
    Показать окно с политикой конфиденциальности
    
    Args:
        message: Сообщение от пользователя
        state: FSM контекст
        user_intent: "Обучение" или "Консультация" - намерение пользователя из Фазы 1
        waiting_sticker_message: Сообщение со стикером ожидания для удаления
    """
    try:
        if not message:
            logger.error("show_policy_window: message is None")
            return
        
        # Удаляем стикер ожидания перед показом окна
        if waiting_sticker_message:
            try:
                await waiting_sticker_message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить стикер ожидания: {e}")
        
        policy_url = _load_policy_link()
        
        text = (
            "⚠️ <b>Внимание!</b> Для продолжения диалога Вы должны ответить на вопрос:\n"
            "| 👉 Вы хотите предоставить свои персональные данные на условиях <b>Политики конфиденциальности? |</b>\n"
            "В случае согласия Ваши персональные данные будут НАДЁЖНО защищены 🔥"
        )
        
        # Размещаем кнопки горизонтально в одной строке
        row = []
        row.append(InlineKeyboardButton(text="✅ ДА", callback_data=f"policy:accept:{user_intent}"))
        
        if policy_url:
            row.append(InlineKeyboardButton(text="📥 Политика", url=policy_url))
        
        row.append(InlineKeyboardButton(text="🚫 НЕТ", callback_data="policy:reject"))
        
        markup = InlineKeyboardMarkup(inline_keyboard=[row])
        
        await message.answer(
            text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        
        # Сохраняем намерение пользователя в state и устанавливаем Фазу 2
        await state.update_data(user_intent=user_intent, policy_shown=True, phase=2)
        
        if message.from_user:
            await save_chat_message(message.from_user.id, "assistant", text)
    except Exception as e:
        logger.error(f"Ошибка в show_policy_window: {e}", exc_info=True)
        # Удаляем стикер ожидания при ошибке
        if waiting_sticker_message:
            try:
                await waiting_sticker_message.delete()
            except Exception:
                pass
        if message and message.from_user:
            try:
                await message.answer("⚠️ Произошла ошибка при показе окна политики. Попробуйте еще раз.")
            except Exception:
                pass


@router.callback_query(F.data.startswith("policy:accept:"))
async def handle_policy_accept(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка согласия с политикой"""
    logger.info(f"Пользователь {callback.from_user.id} согласился с политикой")
    
    if not callback.from_user:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Получаем системное имя пользователя
    name_sys = "друг"
    if callback.from_user:
        if callback.from_user.first_name:
            name_sys = callback.from_user.first_name
        elif callback.from_user.username:
            name_sys = callback.from_user.username
    
    # Получаем профиль пользователя для проверки Status
    profile = await get_user_profile(user_id)
    if not profile:
        # Если профиля нет, создаем его
        profile = await get_or_create_user_profile(user_id, name_sys)
    elif not profile.name_sys:
        # Обновляем name_sys, если его нет
        await update_user_profile(tg_user_id=user_id, name_sys=name_sys)
    
    # Устанавливаем Politic = "ДА"
    updated_profile = await update_user_profile(
        tg_user_id=user_id,
        politic="ДА",
        name_sys=name_sys if not profile.name_sys else None,
    )
    await save_chat_message(user_id, "user", "ДА")
    
    await callback.answer("Спасибо за согласие!")
    
    # Оставляем сообщение с политикой в чате (не удаляем)
    
    # Проверяем Status из обновленного профиля пользователя
    status = updated_profile.status if updated_profile else (profile.status if profile else "Читатель")
    
    # Сбрасываем флаг показа политики, так как выбор сделан
    await state.update_data(policy_shown=False)
    
    # Сохранение в Excel будет происходить только в блоке Записи (при выборе "Сам" или "Контакт")
    
    # Если Status = "Обучение" - переходим к Фазе 3 (Анкетирование)
    # Если Status = "Консультация" - переходим к Фазе 4 (Запись)
    if status == "Обучение":
        # Переход к Фазе 3 (Анкетирование)
        await state.update_data(
            phase=3, 
            policy_accepted=True,
            anketa_started=True,
            anketa_question=1
        )
        # Инициируем анкетирование
        anketa_message = (
            "Вы хотите начать обучение, отлично, это правильное решение 👍.\n"
            "🔎 Проведём небольшое анкетирование.\n"
            "Ответьте на вопросы в свободной форме:\n\n"
            "<b>1. Какой у Вас ОПЫТ игры на бильярде?</b>\n"
            "(Например: играю 2 года, новичок, не играл, умею играть, играл в детстве и т.д.)"
        )
        await callback.message.answer(anketa_message, parse_mode=ParseMode.HTML)
        await save_chat_message(user_id, "assistant", anketa_message)
        logger.info(f"Переход к Фазе 3 (Анкетирование) для пользователя {user_id}, Status={status}")
    elif status == "Консультация":
        # Переход к Фазе 4 (Запись)
        await state.update_data(phase=4, policy_accepted=True, phase4_window_shown=False)
        # Используем ту же функцию для показа окна Фазы 4, что и при переходе из Фазы 3
        # Локальный импорт для избежания циклического импорта
        from .faq import _show_phase4_booking_window
        await _show_phase4_booking_window(callback.message, state, None)
        logger.info(f"Переход к Фазе 4 (Запись) для пользователя {user_id}, Status={status}")
    else:
        # Если Status не "Обучение" и не "Консультация", возвращаемся к Фазе 1
        await state.update_data(phase=1, policy_accepted=True)
        await callback.message.answer("▶️ Я готов к Вашим вопросам.")
        logger.warning(f"Неожиданный Status={status} для пользователя {user_id}, возврат к Фазе 1")


@router.callback_query(F.data == "policy:reject")
async def handle_policy_reject(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка отказа от политики"""
    try:
        if not callback.from_user:
            logger.error("handle_policy_reject: callback.from_user is None")
            await callback.answer("Ошибка: пользователь не найден", show_alert=True)
            return
        
        if not callback.message:
            logger.error("handle_policy_reject: callback.message is None")
            await callback.answer("Ошибка: сообщение не найдено", show_alert=True)
            return
        
        user_id = callback.from_user.id
        logger.info(f"Пользователь {user_id} отказался от политики")
        
        # Устанавливаем Politic = "НЕТ" (не критично, если не удастся)
        try:
            await update_user_profile(
                tg_user_id=user_id,
                politic="НЕТ",
            )
            await save_chat_message(user_id, "user", "НЕТ")
        except Exception as e:
            logger.warning(f"Не удалось обновить профиль или сохранить сообщение: {e}")
        
        await callback.answer("Понятно")
        
        # Возвращаемся к Фазе 1 и сбрасываем флаг показа политики
        try:
            await state.update_data(phase=1, policy_accepted=False, policy_shown=False)
        except Exception as e:
            logger.error(f"Ошибка при обновлении state: {e}", exc_info=True)
        
        # Отправляем сообщение о готовности к вопросам ДО удаления сообщения с политикой
        # Это важно, так как после удаления callback.message может стать невалидным
        try:
            await callback.message.answer("▶️ Я готов к Вашим вопросам.")
            await save_chat_message(user_id, "assistant", "▶️ Я готов к Вашим вопросам.")
            logger.info(f"Пользователь {user_id} вернулся к Фазе 1 после отказа от политики")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения о готовности: {e}", exc_info=True)
            # Если не удалось отправить через answer, пробуем через edit
            try:
                if callback.message:
                    await callback.message.edit_text("▶️ Я готов к Вашим вопросам.")
                    await save_chat_message(user_id, "assistant", "▶️ Я готов к Вашим вопросам.")
            except Exception as e2:
                logger.error(f"Ошибка при редактировании сообщения: {e2}", exc_info=True)
        
        # Оставляем сообщение с политикой в чате (не удаляем)
    except Exception as e:
        logger.error(f"Критическая ошибка в handle_policy_reject: {e}", exc_info=True)
        try:
            await callback.answer("⚠️ Произошла ошибка. Попробуйте еще раз.", show_alert=True)
        except Exception:
            pass


def register_policy(dp: Dispatcher) -> None:
    dp.include_router(router)

