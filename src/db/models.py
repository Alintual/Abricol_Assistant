from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from .session import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(64))
    goal: Mapped[str] = mapped_column(String(255), default="")
    preferred_time: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" или "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class UserProfile(Base):
    """Глобальные переменные для каждого клиента"""
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # Дата последнего обращения
    status: Mapped[str] = mapped_column(String(50), default="Читатель")  # Обучение/Консультация/Читатель
    name: Mapped[str] = mapped_column(String(255), default="")  # Имя клиента
    name_sys: Mapped[str] = mapped_column(String(255), default="")  # Системное имя (first_name или username)
    phone: Mapped[str] = mapped_column(String(64), default="")  # Телефон клиента
    exp: Mapped[str] = mapped_column(String(255), default="")  # Опыт игры
    level: Mapped[str] = mapped_column(String(255), default="")  # Уровень игры
    goals: Mapped[str] = mapped_column(String(255), default="")  # Цели обучения
    before: Mapped[str] = mapped_column(String(50), default="")  # Обучался ли ранее (Да/Нет)
    politic: Mapped[str] = mapped_column(String(10), default="")  # Согласие с политикой (ДА/НЕТ)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContactJournal(Base):
    """Журнал обращений - запись всех данных для лидов с Status Обучение или Консультация"""
    __tablename__ = "contact_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, index=True)
    contact_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)  # Дата обращения
    status: Mapped[str] = mapped_column(String(50))  # Обучение/Консультация
    name: Mapped[str] = mapped_column(String(255), default="")  # Имя клиента
    phone: Mapped[str] = mapped_column(String(64), default="")  # Телефон клиента
    exp: Mapped[str] = mapped_column(String(255), default="")  # Опыт игры
    level: Mapped[str] = mapped_column(String(255), default="")  # Уровень игры
    goals: Mapped[str] = mapped_column(String(255), default="")  # Цели обучения
    before: Mapped[str] = mapped_column(String(50), default="")  # Обучался ли ранее (Да/Нет)
    politic: Mapped[str] = mapped_column(String(10), default="")  # Согласие с политикой (ДА/НЕТ)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # Дата создания записи


