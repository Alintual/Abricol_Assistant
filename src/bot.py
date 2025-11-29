r"""
Инструкции по запуску (Windows, PowerShell):

1) Активируйте виртуальное окружение Python 3.11:
   .\.venv\Scripts\Activate.ps1

2) Запустите построение базы знаний и запустите бот:
   python -m src.bot
   
"""

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from .config import settings
from .handlers.start import register_start
from .handlers.faq import register_faq
from .handlers.booking import register_booking
from .handlers.policy import register_policy
from .db.session import init_engine_and_db


ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE_PATH = ROOT_DIR / "data" / "bot.log"


def _configure_logging() -> None:
    """
    Настройка логирования.
    Логи пишутся в файл bot.log и выводятся в консоль.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


async def _setup_bot_commands(bot: Bot) -> None:
    """Настройка команд бота в меню"""
    try:
        commands = [
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="cancel", description="Нормализация"),
        ]
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logging.info("Команды бота успешно настроены")
    except Exception as e:
        logging.error(f"Ошибка при настройке команд бота: {e}", exc_info=True)


async def main() -> None:
    """Основная функция запуска бота"""
    _configure_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("Запуск бота Abricol Assistant")
    logger.info("=" * 60)
    
    # Проверяем наличие токена
    if not settings.bot_token:
        logger.error("BOT_TOKEN не найден в переменных окружения!")
        logger.error("Создайте файл .env и добавьте BOT_TOKEN=ваш_токен")
        sys.exit(1)
    
    # Инициализируем базу данных
    try:
        logger.info("Инициализация базы данных...")
        await init_engine_and_db()
        logger.info("База данных инициализирована успешно")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}", exc_info=True)
        sys.exit(1)
    
    # Создаем бот и диспетчер
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрируем обработчики
    logger.info("Регистрация обработчиков...")
    register_start(dp)
    register_faq(dp)
    register_booking(dp)
    register_policy(dp)
    logger.info("Обработчики зарегистрированы")
    
    # Настраиваем команды бота
    await _setup_bot_commands(bot)
    
    # Запускаем бота
    logger.info("Бот запущен и готов к работе")
    logger.info("=" * 60)
    
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Критическая ошибка при работе бота: {e}", exc_info=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}", exc_info=True)

