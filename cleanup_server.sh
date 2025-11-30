#!/bin/bash
# Скрипт для очистки сервера от ненужных файлов
# Использование: chmod +x cleanup_server.sh && ./cleanup_server.sh

echo "=========================================="
echo "Очистка сервера Abricol Assistant"
echo "=========================================="
echo ""

# 1. Очистка Docker
echo "1. Очистка Docker..."
echo "   Статистика ДО очистки:"
docker system df
echo ""

# Удаление неиспользуемых образов
echo "   Удаление неиспользуемых образов..."
docker image prune -a -f

# Очистка build cache (только неиспользуемого)
echo "   Очистка неиспользуемого build cache..."
docker builder prune -f

# Безопасная очистка
echo "   Безопасная очистка системы..."
docker system prune -f

echo ""
echo "   Статистика ПОСЛЕ очистки:"
docker system df
echo ""

# 2. Удаление неполных загрузок моделей
echo "2. Удаление неполных загрузок моделей..."
find /opt/Abricol_Assistant/cache/models -name "*.incomplete" -type f -delete
echo "   ✓ Неполные загрузки удалены"
echo ""

# 3. Очистка старых логов (опционально)
echo "3. Проверка логов..."
BOT_LOG="/opt/Abricol_Assistant/data/bot.log"
if [ -f "$BOT_LOG" ]; then
    LOG_SIZE=$(du -h "$BOT_LOG" | cut -f1)
    echo "   Размер bot.log: $LOG_SIZE"
    if [ $(stat -f%z "$BOT_LOG" 2>/dev/null || stat -c%s "$BOT_LOG" 2>/dev/null) -gt 10485760 ]; then
        echo "   ⚠️  Лог больше 10MB, рекомендуется очистить"
        read -p "   Очистить лог? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            > "$BOT_LOG"
            echo "   ✓ Лог очищен"
        fi
    fi
fi
echo ""

# 4. Проверка использования диска
echo "4. Использование диска:"
df -h / | tail -1
echo ""

# 5. Размер директорий проекта
echo "5. Размер директорий проекта:"
cd /opt/Abricol_Assistant 2>/dev/null || exit
du -sh data cache src 2>/dev/null | sort -h
echo ""

echo "=========================================="
echo "Очистка завершена!"
echo "=========================================="

