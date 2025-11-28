# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Установка системных зависимостей
# - build-essential: для компиляции Python пакетов
# - ffmpeg: для обработки аудио (faster-whisper)
# - git: для установки некоторых пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        git \
    && rm -rf /var/lib/apt/lists/*

# Rust не требуется для данного проекта
# Все пакеты из requirements.txt устанавливаются через pip с предкомпилированными wheel файлами
# Если в будущем понадобится Rust, раскомментируйте следующие строки:
# RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup-init.sh && \
#     sh /tmp/rustup-init.sh -y --profile minimal && \
#     rm /tmp/rustup-init.sh
# ENV PATH="/root/.cargo/bin:${PATH}"

# Установка рабочей директории
WORKDIR /app

# Копирование и установка зависимостей Python
# Делаем это отдельно для кэширования слоя Docker
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip cache purge

# Копирование всего кода проекта
COPY . .

# Установка переменных окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Создание директорий для данных (если их нет)
RUN mkdir -p /app/src/knowledge/data/images \
    /app/src/knowledge/data/structured \
    /app/data \
    /tmp \
    /app/.cache && \
    # Создание пустых файлов баз данных, если они не будут смонтированы
    touch /app/abricol.db /app/knowledge.db /app/leads.xlsx /app/bot.log && \
    # Установка прав доступа
    chmod 666 /app/abricol.db /app/knowledge.db /app/leads.xlsx /app/bot.log

# Установка переменных окружения для кэша моделей faster-whisper
ENV HF_HOME=/app/.cache/huggingface
ENV XDG_CACHE_HOME=/app/.cache
ENV TMPDIR=/tmp

# Опционально: сборка базы знаний при сборке образа
# Раскомментируйте следующую строку, если хотите собирать БЗ при билде
# RUN python -m src.build_kb || echo "База знаний будет собрана при первом запуске"

# Точка входа
CMD ["python", "-m", "src.bot"]
