#!/bin/bash
set -e

echo "Инициализация файлов базы данных..."

# Создание директории для данных, если её нет
mkdir -p /app/data

# Функция для безопасного создания файла (удаляет директорию, если она есть)
create_file_if_needed() {
    local file_path=$1
    local file_name=$(basename "$file_path")
    
    # Если это директория - удаляем
    if [ -d "$file_path" ]; then
        echo "⚠️  Обнаружена директория вместо файла: $file_name. Удаляю..."
        rm -rf "$file_path"
    fi
    
    # Создаем файл, если его нет
    if [ ! -f "$file_path" ]; then
        touch "$file_path"
        chmod 666 "$file_path"
        echo "✓ Создан файл $file_name"
    else
        # Устанавливаем права доступа на существующий файл
        chmod 666 "$file_path" 2>/dev/null || true
    fi
}

# Создание всех необходимых файлов
create_file_if_needed "/app/abricol.db"
create_file_if_needed "/app/knowledge.db"
create_file_if_needed "/app/leads.xlsx"
create_file_if_needed "/app/bot.log"

# Финальная проверка, что все это файлы, а не директории
if [ -d /app/abricol.db ] || [ -d /app/knowledge.db ] || [ -d /app/leads.xlsx ] || [ -d /app/bot.log ]; then
    echo "❌ ОШИБКА: Обнаружены директории вместо файлов после инициализации!"
    echo "Проверьте монтирование томов в docker-compose.yml"
    exit 1
fi

echo "✅ Инициализация завершена. Все файлы готовы."
echo "Запуск бота..."

# Запуск основного приложения
exec "$@"

