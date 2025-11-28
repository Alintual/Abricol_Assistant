#!/bin/bash
set -e

echo "Инициализация файлов базы данных..."

# Создание директории для данных, если её нет
mkdir -p /app/data

# Создание файлов баз данных, если их нет (проверяем как файлы, не директории)
if [ ! -e /app/abricol.db ] || [ -d /app/abricol.db ]; then
    if [ -d /app/abricol.db ]; then
        rm -rf /app/abricol.db
    fi
    touch /app/abricol.db
    chmod 666 /app/abricol.db
    echo "✓ Создан файл abricol.db"
fi

if [ ! -e /app/knowledge.db ] || [ -d /app/knowledge.db ]; then
    if [ -d /app/knowledge.db ]; then
        rm -rf /app/knowledge.db
    fi
    touch /app/knowledge.db
    chmod 666 /app/knowledge.db
    echo "✓ Создан файл knowledge.db"
fi

if [ ! -e /app/leads.xlsx ] || [ -d /app/leads.xlsx ]; then
    if [ -d /app/leads.xlsx ]; then
        rm -rf /app/leads.xlsx
    fi
    touch /app/leads.xlsx
    chmod 666 /app/leads.xlsx
    echo "✓ Создан файл leads.xlsx"
fi

if [ ! -e /app/bot.log ] || [ -d /app/bot.log ]; then
    if [ -d /app/bot.log ]; then
        rm -rf /app/bot.log
    fi
    touch /app/bot.log
    chmod 666 /app/bot.log
    echo "✓ Создан файл bot.log"
fi

# Установка прав доступа на существующие файлы
chmod 666 /app/abricol.db /app/knowledge.db /app/leads.xlsx /app/bot.log 2>/dev/null || true

# Проверка, что это файлы, а не директории
if [ -d /app/abricol.db ] || [ -d /app/knowledge.db ] || [ -d /app/leads.xlsx ] || [ -d /app/bot.log ]; then
    echo "ОШИБКА: Обнаружены директории вместо файлов! Удалите их на хосте и перезапустите контейнер."
    exit 1
fi

echo "Инициализация завершена. Запуск бота..."

# Запуск основного приложения
exec "$@"

