from aiogram import Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.enums import ParseMode
from ..db.chat_history import save_chat_message
import os
import logging


router = Router()

# Путь к рекламной картинке
AD_IMAGE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "knowledge", "data", "images",
    "1.1_Общая_информация_page2__Image37.jpg"
))

AD_TEXT = """🎯 Вы хотите научиться играть на бильярде или повысить уровень игры?
Играть красиво и уверенно? Узнать все секреты? Достичь вершин мастерства? Тогда... мы ждем Вас в школе русского бильярда «Абриколь» 🎯"""

def _get_welcome_text(name_sys: str = "друг") -> str:
    """Формирует приветственное сообщение с именем пользователя"""
    return (
        f"👋 <b>Час добрый, {name_sys}! Я - Леонидыч, консультант школы бильярда «Абриколь». Чем могу помочь?</b>\n\n"
    "👉 Общайтесь со мной <b>текстом</b> 📝 или <b>голосом</b> 📣\n"
    "👉 Ищите целые фразы в формате <b>*слово1 слово2...*</b>\n"
        "👉 ЗАПИСЫВАЙТЕСЬ на ОБУЧЕНИЕ или на КОНСУЛЬТАЦИЮ 🔥"
)


def _main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 О школе"), KeyboardButton(text="🔥 О русском бильярде")],
            [KeyboardButton(text="📝 Записаться")],
        ],
        resize_keyboard=True,
    )


async def _send_start_menu(message: Message) -> None:
    """Отправка главного меню: картинка → рекламный текст → приветствие"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Получаем системное имя пользователя для приветствия
        Name_sys = "друг"  # Значение по умолчанию
        if message.from_user:
            if message.from_user.first_name:
                Name_sys = message.from_user.first_name
            elif message.from_user.username:
                Name_sys = message.from_user.username
            elif hasattr(message.from_user, 'full_name') and message.from_user.full_name:
                Name_sys = message.from_user.full_name.split()[0] if message.from_user.full_name.split() else "друг"
        
        # 1. Сначала отправляем картинку (если существует)
        if os.path.exists(AD_IMAGE_PATH):
            try:
                photo = FSInputFile(AD_IMAGE_PATH)
                await message.answer_photo(photo=photo)
                logger.info("Рекламная картинка отправлена")
            except Exception as e:
                logger.warning(f"Не удалось отправить картинку: {e}")
        
        # 2. Затем рекламный текст
        await message.answer(
            AD_TEXT,
            parse_mode=ParseMode.HTML,
        )
        if message.from_user:
            await save_chat_message(message.from_user.id, "assistant", AD_TEXT)
        logger.info("Рекламный текст отправлен")
        
        # 3. Затем приветствие с клавиатурой (с именем пользователя)
        welcome_text = _get_welcome_text(Name_sys)
        await message.answer(
            welcome_text,
            reply_markup=_main_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        if message.from_user:
            await save_chat_message(message.from_user.id, "assistant", welcome_text)
        logger.info("Приветственное сообщение с клавиатурой отправлено")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке стартового меню: {e}", exc_info=True)
        raise


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Получена команда /start от пользователя {message.from_user.id if message.from_user else 'unknown'}")
    try:
        if message.from_user:
            await save_chat_message(message.from_user.id, "user", "/start")
        await _send_start_menu(message)
        logger.info("Команда /start обработана успешно")
    except Exception as e:
        logger.error(f"Ошибка при обработке /start: {e}", exc_info=True)
        # Попробуем отправить хотя бы простое сообщение
        try:
            await message.answer("Привет! Я Леонидыч, консультант школы бильярда «Абриколь». Чем могу помочь?", reply_markup=_main_keyboard())
        except:
            pass




def register_start(dp: Dispatcher) -> None:
    dp.include_router(router)


