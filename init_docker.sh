#!/bin/bash
# Скрипт для инициализации файлов перед запуском Docker контейнера

echo "Инициализация файлов для Docker..."

# Создание директории для данных
mkdir -p data
mkdir -p cache/models

# Создание пустых файлов баз данных, если их нет
if [ ! -f abricol.db ]; then
    touch abricol.db
    echo "Создан файл abricol.db"
fi

if [ ! -f knowledge.db ]; then
    touch knowledge.db
    echo "Создан файл knowledge.db"
fi

# Создание пустого Excel файла, если его нет
if [ ! -f leads.xlsx ]; then
    touch leads.xlsx
    echo "Создан файл leads.xlsx"
fi

# Создание пустого лог-файла, если его нет
if [ ! -f bot.log ]; then
    touch bot.log
    echo "Создан файл bot.log"
fi

# Установка прав доступа
chmod 666 abricol.db knowledge.db leads.xlsx bot.log 2>/dev/null || true

echo "Инициализация завершена!"
echo "Теперь можно запускать: docker-compose up -d"

