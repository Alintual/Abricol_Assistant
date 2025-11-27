from pydantic import BaseModel
from dotenv import load_dotenv
import os


load_dotenv()


class Settings(BaseModel):
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_chat_id: int = int(os.getenv("ADMIN_CHAT_ID", "0"))

    db_path: str = os.getenv("DB_PATH", "sqlite+aiosqlite:///./abricol.db")

    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    # Путь к Excel файлу для сохранения данных о лидах (по умолчанию в корне проекта)
    leads_excel_path: str = os.getenv("LEADS_EXCEL_PATH", "")

    stt_model_size: str = os.getenv("STT_MODEL_SIZE", "medium")
    stt_device: str = os.getenv("STT_DEVICE", "cpu")
    stt_compute_type: str = os.getenv("STT_COMPUTE_TYPE", "int8")
    stt_language: str = os.getenv("STT_LANGUAGE", "ru")


settings = Settings()


