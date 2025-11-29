"""Функции для отправки email с вложениями"""
import logging
import smtplib
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)


def _sync_send_email_with_attachment(
    file_path: str,
    recipient_email: str,
    subject: str = "Обновление файла leads.xlsx",
    body: str = "Файл leads.xlsx был обновлен. См. вложение.",
) -> bool:
    """
    Синхронная функция для отправки email с вложением.
    
    Args:
        file_path: Путь к файлу для отправки
        recipient_email: Email получателя
        subject: Тема письма
        body: Текст письма
        
    Returns:
        True если отправка успешна, False в противном случае
    """
    try:
        # Проверяем наличие необходимых настроек
        if not recipient_email:
            logger.warning("⚠️ EMAIL_MAIN не указан в .env, пропускаем отправку email")
            return False
        
        if not settings.smtp_user or not settings.smtp_password:
            logger.warning("⚠️ SMTP_USER или SMTP_PASSWORD не указаны в .env, пропускаем отправку email")
            return False
        
        # Проверяем существование файла
        if not Path(file_path).exists():
            logger.error(f"❌ Файл {file_path} не существует, невозможно отправить по email")
            return False
        
        # Создаем сообщение
        msg = MIMEMultipart()
        msg['From'] = settings.smtp_user
        msg['To'] = recipient_email
        msg['Subject'] = subject
        
        # Добавляем текст письма
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Добавляем вложение
        with open(file_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        
        encoders.encode_base64(part)
        filename = Path(file_path).name
        part.add_header(
            'Content-Disposition',
            f'attachment; filename= {filename}',
        )
        msg.attach(part)
        
        # Подключаемся к SMTP серверу и отправляем
        logger.info(f"📧 Подключение к SMTP серверу {settings.smtp_host}:{settings.smtp_port}")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()  # Включаем TLS
            server.login(settings.smtp_user, settings.smtp_password)
            text = msg.as_string()
            server.sendmail(settings.smtp_user, recipient_email, text)
        
        logger.info(f"✅ Email успешно отправлен на {recipient_email} с файлом {filename}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ Ошибка аутентификации SMTP: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"❌ Ошибка SMTP: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке email: {e}", exc_info=True)
        return False


async def send_email_with_attachment(
    file_path: str,
    recipient_email: Optional[str] = None,
    subject: str = "Обновление файла leads.xlsx",
    body: str = "Файл leads.xlsx был обновлен. См. вложение.",
) -> bool:
    """
    Асинхронная функция для отправки email с вложением.
    
    Args:
        file_path: Путь к файлу для отправки
        recipient_email: Email получателя (если не указан, используется EMAIL_MAIN из настроек)
        subject: Тема письма
        body: Текст письма
        
    Returns:
        True если отправка успешна, False в противном случае
    """
    try:
        recipient = recipient_email or settings.email_main
        if not recipient:
            logger.warning("⚠️ Email получателя не указан, пропускаем отправку")
            return False
        
        logger.info(f"🔄 Начало отправки email на {recipient} с файлом {file_path}")
        # Запускаем синхронную функцию в отдельном потоке
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _sync_send_email_with_attachment,
            file_path,
            recipient,
            subject,
            body,
        )
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске отправки email: {e}", exc_info=True)
        return False

