# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Установка системных зависимостей
# - ffmpeg: для обработки аудио (faster-whisper, конвертация .oga в .wav)
# build-essential удален для экономии места (faster-whisper поставляется с предкомпилированными wheel)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

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
    /app/.cache

# Копирование entrypoint скрипта
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Установка переменных окружения для кэша моделей faster-whisper
ENV HF_HOME=/app/.cache/huggingface
ENV XDG_CACHE_HOME=/app/.cache
ENV TMPDIR=/tmp

# Опционально: сборка базы знаний при сборке образа
# Раскомментируйте следующую строку, если хотите собирать БЗ при билде
# RUN python -m src.build_kb || echo "База знаний будет собрана при первом запуске"

# Точка входа
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "src.bot"]
