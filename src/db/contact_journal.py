"""Функции для работы с журналом обращений"""
import logging
import os
import asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .session import get_session
from .models import ContactJournal, UserProfile
from ..config import settings

logger = logging.getLogger(__name__)

# Путь к файлу links.txt
LINKS_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "knowledge", "data", "links.txt")
)


def _load_journal_link() -> str:
    """Загрузить ссылку на Журнал обращений из links.txt"""
    if not os.path.exists(LINKS_FILE_PATH):
        logger.warning(f"Файл links.txt не найден: {LINKS_FILE_PATH}")
        return ""
    try:
        with open(LINKS_FILE_PATH, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if "Журнал обращений" in line and " - " in line:
                    _, url = line.split(" - ", 1)
                    return url.strip()
        logger.warning("Ссылка на Журнал обращений не найдена в links.txt")
        return ""
    except Exception as e:
        logger.error(f"Ошибка при чтении links.txt: {e}", exc_info=True)
        return ""


def _extract_spreadsheet_id_from_url(url: str) -> str | None:
    """
    Извлечь ID таблицы Google Sheets из URL.
    
    Args:
        url: URL таблицы Google Sheets
        
    Returns:
        ID таблицы или None, если не удалось извлечь
    """
    if not url:
        return None
    
    try:
        # Формат URL: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit...
        if "/spreadsheets/d/" in url:
            parts = url.split("/spreadsheets/d/")
            if len(parts) > 1:
                spreadsheet_id = parts[1].split("/")[0]
                return spreadsheet_id
        return None
    except Exception as e:
        logger.error(f"Ошибка при извлечении ID из URL: {e}")
        return None


def _get_spreadsheet_id() -> str:
    """
    Получить ID таблицы Google Sheets из настроек или из ссылки в links.txt.
    
    Returns:
        ID таблицы или пустая строка
    """
    # Сначала пробуем из настроек
    if settings.google_sheets_spreadsheet_id:
        return settings.google_sheets_spreadsheet_id
    
    # Если не указан, извлекаем из ссылки в links.txt
    journal_link = _load_journal_link()
    if journal_link:
        spreadsheet_id = _extract_spreadsheet_id_from_url(journal_link)
        if spreadsheet_id:
            logger.info(f"ID таблицы извлечен из ссылки: {spreadsheet_id}")
            return spreadsheet_id
    
    # Возвращаем дефолтный ID
    return "19lUsVO5zeuWc6H5YrQVrE-hztUiqC5TpFOy11ORZLv4"


async def add_to_contact_journal(tg_user_id: int, profile: UserProfile) -> ContactJournal | None:
    """
    Добавить запись в журнал обращений для пользователя с Status Обучение или Консультация.
    
    Args:
        tg_user_id: Telegram ID пользователя
        profile: Профиль пользователя из UserProfile
        
    Returns:
        Созданная запись ContactJournal или None, если статус не подходит
    """
    # Проверяем, что статус подходит для журнала
    if profile.status not in ("Обучение", "Консультация"):
        logger.debug(f"Пользователь {tg_user_id} имеет статус '{profile.status}', запись в журнал не требуется")
        return None
    
    async for session in get_session():
        try:
            # Используем текущую дату и время для contact_date (дата обращения)
            current_date = datetime.utcnow()
            
            # Создаем запись в журнале
            journal_entry = ContactJournal(
                tg_user_id=tg_user_id,
                contact_date=current_date,  # Дата обращения (текущая дата)
                status=profile.status,
                name=profile.name or "",
                phone=profile.phone or "",
                exp=profile.exp or "",
                level=profile.level or "",
                goals=profile.goals or "",
                before=profile.before or "",
                politic=profile.politic or "",
            )
            session.add(journal_entry)
            await session.commit()
            await session.refresh(journal_entry)
            logger.info(
                f"Добавлена запись в журнал обращений для пользователя {tg_user_id}, "
                f"статус: {profile.status}, дата: {current_date}, имя: {profile.name or 'не указано'}, "
                f"телефон: {profile.phone or 'не указан'}"
            )
            
            # Асинхронно добавляем запись в Google Sheets (не блокируем основной поток)
            try:
                # Используем create_task для фоновой задачи
                asyncio.create_task(_add_to_google_sheets(journal_entry))
            except RuntimeError:
                # Если event loop не запущен, запускаем синхронно в executor
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(_add_to_google_sheets(journal_entry))
                    else:
                        asyncio.run(_add_to_google_sheets(journal_entry))
                except Exception as e:
                    logger.warning(f"Не удалось запустить задачу записи в Google Sheets: {e}")
            except Exception as e:
                logger.warning(f"Не удалось запустить задачу записи в Google Sheets: {e}")
            
            return journal_entry
        except Exception as e:
            logger.error(f"Ошибка при добавлении записи в журнал обращений: {e}", exc_info=True)
            await session.rollback()
            return None


async def get_journal_link() -> str:
    """Получить ссылку на Журнал обращений из links.txt"""
    return _load_journal_link()


async def get_journal_entries_by_date(date: datetime) -> list[ContactJournal]:
    """
    Получить все записи журнала обращений за указанную дату.
    
    Args:
        date: Дата для фильтрации
        
    Returns:
        Список записей ContactJournal за указанную дату
    """
    async for session in get_session():
        try:
            # Фильтруем по дате (без учета времени)
            result = await session.execute(
                select(ContactJournal).where(
                    ContactJournal.contact_date >= date.replace(hour=0, minute=0, second=0, microsecond=0),
                    ContactJournal.contact_date < date.replace(hour=23, minute=59, second=59, microsecond=999999)
                )
            )
            entries = result.scalars().all()
            return list(entries)
        except Exception as e:
            logger.error(f"Ошибка при получении записей журнала за дату {date}: {e}", exc_info=True)
            return []


async def get_journal_entries_by_user(tg_user_id: int) -> list[ContactJournal]:
    """
    Получить все записи журнала обращений для указанного пользователя.
    
    Args:
        tg_user_id: Telegram ID пользователя
        
    Returns:
        Список записей ContactJournal для пользователя
    """
    async for session in get_session():
        try:
            result = await session.execute(
                select(ContactJournal).where(ContactJournal.tg_user_id == tg_user_id)
                .order_by(ContactJournal.contact_date.desc())
            )
            entries = result.scalars().all()
            return list(entries)
        except Exception as e:
            logger.error(f"Ошибка при получении записей журнала для пользователя {tg_user_id}: {e}", exc_info=True)
            return []


def _sync_add_to_google_sheets(journal_entry: ContactJournal) -> None:
    """
    Синхронная функция для добавления записи в Google Sheets.
    
    Args:
        journal_entry: Запись из ContactJournal для добавления в таблицу
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Проверяем наличие credentials
        if not settings.google_sheets_credentials_path:
            logger.warning("GOOGLE_SHEETS_CREDENTIALS_PATH не установлен, пропускаем запись в Google Sheets")
            return
        
        if not os.path.exists(settings.google_sheets_credentials_path):
            logger.warning(f"Файл credentials не найден: {settings.google_sheets_credentials_path}")
            return
        
        # Получаем ID таблицы (из настроек или из ссылки)
        spreadsheet_id = _get_spreadsheet_id()
        if not spreadsheet_id:
            logger.warning("Не удалось получить ID таблицы Google Sheets, пропускаем запись")
            return
        
        logger.info(f"Попытка записи в Google Sheets, ID таблицы: {spreadsheet_id}")
        
        # Загружаем credentials и подключаемся к Google Sheets
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_file(
            settings.google_sheets_credentials_path,
            scopes=scopes
        )
        client = gspread.authorize(creds)
        
        # Открываем таблицу
        try:
            spreadsheet = client.open_by_key(spreadsheet_id)
            logger.info(f"✅ Таблица открыта: {spreadsheet.title} (ID: {spreadsheet_id})")
        except gspread.exceptions.SpreadsheetNotFound:
            logger.error(f"❌ Таблица с ID {spreadsheet_id} не найдена. Проверьте ID и доступ Service Account.")
            return
        except gspread.exceptions.APIError as e:
            logger.error(f"❌ Ошибка API Google Sheets: {e}. Проверьте доступ Service Account к таблице.")
            return
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при открытии таблицы: {e}", exc_info=True)
            return
        
        # Получаем первый лист (или создаем, если его нет)
        try:
            worksheet = spreadsheet.sheet1
        except Exception:
            worksheet = spreadsheet.add_worksheet(title="Журнал обращений", rows=1000, cols=10)
        
        # Проверяем, есть ли заголовки
        try:
            headers = worksheet.row_values(1)
            if not headers or len(headers) < 9:
                # Добавляем заголовки, если их нет
                worksheet.append_row([
                    "Дата обращения",
                    "Telegram ID",
                    "Статус",
                    "Имя",
                    "Телефон",
                    "Опыт",
                    "Уровень",
                    "Цели",
                    "Обучался ранее",
                    "Политика"
                ])
        except Exception as e:
            logger.warning(f"Ошибка при проверке заголовков: {e}")
        
        # Форматируем дату для таблицы
        contact_date_str = journal_entry.contact_date.strftime("%Y-%m-%d %H:%M:%S")
        
        # Добавляем строку с данными
        row_data = [
            contact_date_str,
            str(journal_entry.tg_user_id),
            journal_entry.status,
            journal_entry.name or "",
            journal_entry.phone or "",
            journal_entry.exp or "",
            journal_entry.level or "",
            journal_entry.goals or "",
            journal_entry.before or "",
            journal_entry.politic or "",
        ]
        
        worksheet.append_row(row_data)
        logger.info(
            f"✅ Запись добавлена в Google Sheets для пользователя {journal_entry.tg_user_id}, "
            f"статус: {journal_entry.status}, имя: {journal_entry.name or 'не указано'}, "
            f"телефон: {journal_entry.phone or 'не указан'}, дата: {contact_date_str}"
        )
        
    except ImportError:
        logger.warning("Библиотека gspread не установлена. Установите: pip install gspread google-auth")
    except Exception as e:
        logger.error(f"Ошибка при добавлении записи в Google Sheets: {e}", exc_info=True)


async def _add_to_google_sheets(journal_entry: ContactJournal) -> None:
    """
    Асинхронная обертка для добавления записи в Google Sheets.
    
    Args:
        journal_entry: Запись из ContactJournal для добавления в таблицу
    """
    try:
        # Запускаем синхронную функцию в отдельном потоке
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_add_to_google_sheets, journal_entry)
    except Exception as e:
        logger.error(f"Ошибка при запуске записи в Google Sheets: {e}", exc_info=True)

