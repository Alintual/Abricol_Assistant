# 🧹 Справочник команд: Удаление, очистка и тестирование на сервере

Полный список команд для удаления, очистки, диагностики и тестирования на продакшн сервере.

---

## 📋 Содержание

1. [Безопасное удаление контейнера](#безопасное-удаление-контейнера)
2. [Очистка Docker ресурсов](#очистка-docker-ресурсов)
3. [Очистка данных приложения](#очистка-данных-приложения)
4. [Полное удаление проекта](#полное-удаление-проекта)
5. [Диагностика проблем](#диагностика-проблем)
6. [Тестирование после очистки](#тестирование-после-очистки)
7. [Восстановление после очистки](#восстановление-после-очистки)
8. [Быстрые команды очистки](#быстрые-команды-очистки)

---

## 🛑 Безопасное удаление контейнера

### Остановка и удаление контейнера

```bash
# 1. Переход в директорию проекта
cd /opt/Abricol_Assistant

# 2. Остановка контейнера
docker-compose -f docker-compose.prod.yml stop

# 3. Удаление контейнера (данные сохраняются в томах)
docker-compose -f docker-compose.prod.yml down

# 4. Проверка, что контейнер удален
docker ps -a | grep abricol-assistant
```

### Принудительное удаление

```bash
# Если контейнер не останавливается
docker-compose -f docker-compose.prod.yml down --remove-orphans

# Принудительная остановка и удаление
docker kill abricol-assistant
docker rm abricol-assistant

# Удаление всех остановленных контейнеров
docker container prune -f
```

### Удаление с сохранением данных

```bash
# Остановка и удаление контейнера (данные в ./data сохраняются)
docker-compose -f docker-compose.prod.yml down

# Проверка сохранности данных
ls -lh /opt/Abricol_Assistant/data/

# Проверка размера данных
du -sh /opt/Abricol_Assistant/data
```

---

## 🗑️ Очистка Docker ресурсов

### Очистка образов

```bash
# Просмотр всех образов
docker images

# Просмотр образов с размером
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# Удаление конкретного образа
docker rmi abricol-assistant:latest

# Удаление образа по ID
docker rmi <image_id>

# Удаление образа с принуждением
docker rmi -f <image_id>

# Удаление всех неиспользуемых образов
docker image prune -a

# Удаление всех неиспользуемых образов с подтверждением
docker image prune -a -f

# Удаление всех образов (ОСТОРОЖНО!)
docker rmi $(docker images -q)
```

### Очистка контейнеров

```bash
# Просмотр всех контейнеров (включая остановленные)
docker ps -a

# Просмотр только остановленных контейнеров
docker ps -a -f status=exited

# Удаление остановленных контейнеров
docker container prune

# Удаление остановленных контейнеров без подтверждения
docker container prune -f

# Удаление конкретного контейнера
docker rm abricol-assistant

# Принудительное удаление запущенного контейнера
docker rm -f abricol-assistant

# Удаление всех остановленных контейнеров
docker rm $(docker ps -a -q -f status=exited)

# Удаление контейнеров по имени
docker rm $(docker ps -a -q -f name=abricol)
```

### Очистка томов

```bash
# Просмотр всех томов
docker volume ls

# Просмотр неиспользуемых томов
docker volume ls -f dangling=true

# Удаление неиспользуемых томов (ОСТОРОЖНО! Может удалить данные)
docker volume prune

# Удаление неиспользуемых томов без подтверждения
docker volume prune -f

# Удаление конкретного тома
docker volume rm <volume_name>

# Удаление всех неиспользуемых томов
docker volume prune -a
```

### Очистка сетей

```bash
# Просмотр всех сетей
docker network ls

# Просмотр неиспользуемых сетей
docker network ls -f dangling=true

# Удаление неиспользуемых сетей
docker network prune

# Удаление неиспользуемых сетей без подтверждения
docker network prune -f

# Удаление конкретной сети
docker network rm abricol-network

# Удаление всех неиспользуемых сетей
docker network prune -a
```

### Полная очистка Docker (ОСТОРОЖНО!)

```bash
# Удаление всего неиспользуемого (контейнеры, сети, образы, тома)
docker system prune -a --volumes

# Удаление без подтверждения
docker system prune -a --volumes -f

# Только неиспользуемые ресурсы (без томов)
docker system prune -a

# Только неиспользуемые ресурсы без подтверждения
docker system prune -a -f

# Просмотр того, что будет удалено (без удаления)
docker system df
```

### Очистка кэша сборки

```bash
# Удаление кэша сборки Docker
docker builder prune

# Удаление всего кэша сборки
docker builder prune -a

# Удаление без подтверждения
docker builder prune -a -f
```

---

## 📂 Очистка данных приложения

### Очистка логов

```bash
# Просмотр размера логов
du -sh /opt/Abricol_Assistant/data/bot.log

# Просмотр размера всех логов
du -sh /opt/Abricol_Assistant/data/*.log

# Очистка логов (оставляет пустой файл)
> /opt/Abricol_Assistant/data/bot.log

# Или удаление и создание нового
rm /opt/Abricol_Assistant/data/bot.log
touch /opt/Abricol_Assistant/data/bot.log
chmod 666 /opt/Abricol_Assistant/data/bot.log

# Очистка старых логов (оставить последние 1000 строк)
tail -n 1000 /opt/Abricol_Assistant/data/bot.log > /tmp/bot.log.tmp
mv /tmp/bot.log.tmp /opt/Abricol_Assistant/data/bot.log

# Очистка логов старше определенного размера
if [ $(stat -f%z /opt/Abricol_Assistant/data/bot.log 2>/dev/null || stat -c%s /opt/Abricol_Assistant/data/bot.log) -gt 104857600 ]; then
    > /opt/Abricol_Assistant/data/bot.log
fi

# Ротация логов (сохранение последних N строк)
tail -n 5000 /opt/Abricol_Assistant/data/bot.log > /opt/Abricol_Assistant/data/bot.log.new
mv /opt/Abricol_Assistant/data/bot.log.new /opt/Abricol_Assistant/data/bot.log
```

### Очистка баз данных

```bash
# ⚠️ ВНИМАНИЕ: Это удалит все данные!

# Остановка контейнера перед очисткой
docker-compose -f docker-compose.prod.yml down

# Резервная копия перед удалением
mkdir -p /opt/backups/abricol
cp /opt/Abricol_Assistant/data/abricol.db /opt/backups/abricol/abricol-$(date +%Y%m%d).db
cp /opt/Abricol_Assistant/data/knowledge.db /opt/backups/abricol/knowledge-$(date +%Y%m%d).db

# Удаление баз данных
rm /opt/Abricol_Assistant/data/abricol.db
rm /opt/Abricol_Assistant/data/knowledge.db

# Создание новых пустых баз
touch /opt/Abricol_Assistant/data/abricol.db
touch /opt/Abricol_Assistant/data/knowledge.db
chmod 666 /opt/Abricol_Assistant/data/*.db

# Пересборка базы знаний после очистки
docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml exec abricol-bot python -m src.build_kb
```

### Очистка Excel файла

```bash
# Резервная копия
cp /opt/Abricol_Assistant/data/leads.xlsx /opt/Abricol_Assistant/data/leads.xlsx.backup

# Удаление файла
rm /opt/Abricol_Assistant/data/leads.xlsx

# Создание нового пустого файла
touch /opt/Abricol_Assistant/data/leads.xlsx
chmod 666 /opt/Abricol_Assistant/data/leads.xlsx

# Очистка содержимого Excel (сохранение структуры)
# Требуется Python скрипт или ручное редактирование
```

### Очистка кэша моделей

```bash
# Просмотр размера кэша
du -sh /opt/Abricol_Assistant/cache/models

# Детальный просмотр размера
du -h --max-depth=2 /opt/Abricol_Assistant/cache/models

# Удаление кэша моделей faster-whisper
rm -rf /opt/Abricol_Assistant/cache/models/*

# Полная очистка кэша
rm -rf /opt/Abricol_Assistant/cache/models
mkdir -p /opt/Abricol_Assistant/cache/models
chmod -R 755 /opt/Abricol_Assistant/cache/models

# Очистка только старых моделей (старше 30 дней)
find /opt/Abricol_Assistant/cache/models -type f -mtime +30 -delete
```

### Очистка временных файлов

```bash
# Удаление временных файлов в data/
find /opt/Abricol_Assistant/data -name "*.tmp" -delete
find /opt/Abricol_Assistant/data -name "*.backup" -delete
find /opt/Abricol_Assistant/data -name "*.log.*" -delete
find /opt/Abricol_Assistant/data -name "*.swp" -delete
find /opt/Abricol_Assistant/data -name "*.bak" -delete

# Удаление пустых директорий
find /opt/Abricol_Assistant/data -type d -empty -delete

# Очистка всех временных файлов проекта
find /opt/Abricol_Assistant -name "*.pyc" -delete
find /opt/Abricol_Assistant -name "__pycache__" -type d -exec rm -rf {} +
find /opt/Abricol_Assistant -name "*.tmp" -delete
```

### Очистка структурированных файлов базы знаний

```bash
# Просмотр размера
du -sh /opt/Abricol_Assistant/src/knowledge/data/structured

# Удаление структурированных файлов (будут пересозданы при сборке)
rm -rf /opt/Abricol_Assistant/src/knowledge/data/structured/*

# Удаление изображений (будут пересозданы при сборке)
rm -rf /opt/Abricol_Assistant/src/knowledge/data/images/*
```

---

## 💥 Полное удаление проекта

### Удаление с сохранением данных

```bash
# 1. Создание резервной копии
mkdir -p /opt/backups/abricol-$(date +%Y%m%d)
cp -r /opt/Abricol_Assistant/data /opt/backups/abricol-$(date +%Y%m%d)/
cp /opt/Abricol_Assistant/.env /opt/backups/abricol-$(date +%Y%m%d)/ 2>/dev/null || true

# 2. Остановка и удаление контейнера
cd /opt/Abricol_Assistant
docker-compose -f docker-compose.prod.yml down

# 3. Удаление образа
docker rmi abricol-assistant:latest 2>/dev/null || true

# 4. Удаление сети
docker network rm abricol-network 2>/dev/null || true

# 5. Удаление проекта (код, но не data/)
rm -rf /opt/Abricol_Assistant/src
rm -rf /opt/Abricol_Assistant/.git
rm /opt/Abricol_Assistant/Dockerfile
rm /opt/Abricol_Assistant/docker-compose*.yml
rm /opt/Abricol_Assistant/requirements.txt
rm /opt/Abricol_Assistant/docker-entrypoint.sh
rm /opt/Abricol_Assistant/*.sh
rm /opt/Abricol_Assistant/*.md
# НО НЕ УДАЛЯЙТЕ: data/, .env, cache/
```

### Полное удаление (включая данные)

```bash
# ⚠️ ВНИМАНИЕ: Это удалит ВСЕ данные безвозвратно!

# 1. Создание финальной резервной копии (на всякий случай)
mkdir -p /opt/backups/abricol-final-$(date +%Y%m%d)
tar -czf /opt/backups/abricol-final-$(date +%Y%m%d)/final-backup.tar.gz \
    /opt/Abricol_Assistant/data \
    /opt/Abricol_Assistant/.env

# 2. Остановка и удаление контейнера
cd /opt/Abricol_Assistant
docker-compose -f docker-compose.prod.yml down

# 3. Удаление образа
docker rmi abricol-assistant:latest 2>/dev/null || true

# 4. Удаление сети
docker network rm abricol-network 2>/dev/null || true

# 5. Удаление всего проекта
rm -rf /opt/Abricol_Assistant
```

### Удаление только Docker ресурсов (сохранение кода и данных)

```bash
# Удаление контейнера
docker-compose -f docker-compose.prod.yml down

# Удаление образа
docker rmi abricol-assistant:latest

# Удаление сети
docker network rm abricol-network

# Проверка, что все удалено
docker ps -a | grep abricol
docker images | grep abricol
docker network ls | grep abricol
```

---

## 🔍 Диагностика проблем

### Проверка состояния контейнера

```bash
# Статус контейнера
docker ps -a | grep abricol-assistant

# Детальная информация о контейнере
docker inspect abricol-assistant

# Логи контейнера
docker logs abricol-assistant

# Последние 100 строк логов
docker logs --tail=100 abricol-assistant

# Логи с временными метками
docker logs -t abricol-assistant

# Логи с определенного времени
docker logs --since 2025-12-01T00:00:00 abricol-assistant
```

### Проверка ресурсов

```bash
# Использование CPU и памяти
docker stats abricol-assistant --no-stream

# Использование диска
df -h

# Размер директорий
du -sh /opt/Abricol_Assistant/*
du -h --max-depth=1 /opt/Abricol_Assistant

# Проверка места в Docker
docker system df

# Детальная информация о использовании места
docker system df -v
```

### Проверка сетевых подключений

```bash
# Сетевые подключения контейнера
docker network inspect abricol-network

# Проверка портов
netstat -tulpn | grep docker

# Проверка подключений контейнера
docker exec abricol-assistant netstat -tulpn
```

### Проверка файлов и прав доступа

```bash
# Проверка прав доступа к данным
ls -la /opt/Abricol_Assistant/data/

# Проверка размера файлов
ls -lh /opt/Abricol_Assistant/data/*

# Проверка наличия файлов
test -f /opt/Abricol_Assistant/data/abricol.db && echo "✅ База данных существует" || echo "❌ База данных отсутствует"
test -f /opt/Abricol_Assistant/.env && echo "✅ .env файл существует" || echo "❌ .env файл отсутствует"
test -f /opt/Abricol_Assistant/data/knowledge.db && echo "✅ База знаний существует" || echo "❌ База знаний отсутствует"

# Проверка прав доступа к файлам
stat /opt/Abricol_Assistant/data/abricol.db
```

### Поиск ошибок в логах

```bash
# Поиск ошибок
grep -i "error" /opt/Abricol_Assistant/data/bot.log | tail -20

# Поиск критических ошибок
grep -i "critical\|fatal\|exception" /opt/Abricol_Assistant/data/bot.log | tail -20

# Поиск по времени
grep "2025-12-01" /opt/Abricol_Assistant/data/bot.log | grep -i error

# Подсчет ошибок
grep -i "error" /opt/Abricol_Assistant/data/bot.log | wc -l

# Поиск последних ошибок
grep -i "error" /opt/Abricol_Assistant/data/bot.log | tail -10

# Поиск ошибок в Docker логах
docker logs abricol-assistant 2>&1 | grep -i error | tail -20
```

### Проверка переменных окружения

```bash
# Проверка переменных в контейнере
docker-compose -f docker-compose.prod.yml exec abricol-bot env | sort

# Проверка конкретных переменных
docker-compose -f docker-compose.prod.yml exec abricol-bot env | grep BOT_TOKEN
docker-compose -f docker-compose.prod.yml exec abricol-bot env | grep DEEPSEEK
docker-compose -f docker-compose.prod.yml exec abricol-bot env | grep DB_PATH

# Проверка .env файла на сервере
cat /opt/Abricol_Assistant/.env | grep -v "^#" | grep -v "^$"
```

### Проверка процессов в контейнере

```bash
# Список процессов
docker exec abricol-assistant ps aux

# Проверка использования памяти процессами
docker exec abricol-assistant ps aux --sort=-%mem | head -10
```

---

## 🧪 Тестирование после очистки

### Тест после очистки логов

```bash
# 1. Очистка логов
> /opt/Abricol_Assistant/data/bot.log

# 2. Перезапуск контейнера
docker-compose -f docker-compose.prod.yml restart

# 3. Проверка новых логов
sleep 5
tail -n 20 /opt/Abricol_Assistant/data/bot.log

# 4. Проверка на ошибки
grep -i "error" /opt/Abricol_Assistant/data/bot.log
```

### Тест после очистки кэша

```bash
# 1. Очистка кэша
rm -rf /opt/Abricol_Assistant/cache/models/*

# 2. Перезапуск контейнера
docker-compose -f docker-compose.prod.yml restart

# 3. Проверка работы STT (Speech-to-Text)
# Отправьте голосовое сообщение боту в Telegram

# 4. Проверка загрузки моделей
ls -lh /opt/Abricol_Assistant/cache/models/
```

### Тест после пересборки базы знаний

```bash
# 1. Остановка контейнера
docker-compose -f docker-compose.prod.yml down

# 2. Удаление базы знаний
rm /opt/Abricol_Assistant/data/knowledge.db

# 3. Запуск контейнера
docker-compose -f docker-compose.prod.yml up -d

# 4. Пересборка базы знаний
docker-compose -f docker-compose.prod.yml exec abricol-bot python -m src.build_kb

# 5. Проверка размера новой базы
ls -lh /opt/Abricol_Assistant/data/knowledge.db

# 6. Тест в Telegram - задайте вопрос боту
```

### Полный тест после очистки

```bash
# 1. Проверка статуса
docker-compose -f docker-compose.prod.yml ps

# 2. Проверка логов на ошибки
docker-compose -f docker-compose.prod.yml logs | grep -i error | tail -10

# 3. Проверка работы базы данных
docker-compose -f docker-compose.prod.yml exec abricol-bot python -c "
import asyncio
from src.db.session import init_engine_and_db
asyncio.run(init_engine_and_db())
print('✅ База данных работает')
"

# 4. Проверка размера файлов
du -sh /opt/Abricol_Assistant/data/*

# 5. Тест в Telegram
# - Отправьте /start
# - Задайте вопрос
# - Проверьте ответ
```

---

## 🔄 Восстановление после очистки

### Восстановление из резервной копии

```bash
# 1. Остановка контейнера
docker-compose -f docker-compose.prod.yml down

# 2. Восстановление данных
cp /opt/backups/abricol-YYYYMMDD/data/abricol.db /opt/Abricol_Assistant/data/
cp /opt/backups/abricol-YYYYMMDD/data/knowledge.db /opt/Abricol_Assistant/data/
cp /opt/backups/abricol-YYYYMMDD/data/leads.xlsx /opt/Abricol_Assistant/data/

# 3. Восстановление прав доступа
chmod 666 /opt/Abricol_Assistant/data/*.db
chmod 666 /opt/Abricol_Assistant/data/*.xlsx

# 4. Запуск контейнера
docker-compose -f docker-compose.prod.yml up -d

# 5. Проверка
docker-compose -f docker-compose.prod.yml logs -f
```

### Восстановление .env файла

```bash
# Если .env был удален
cp /opt/backups/abricol-YYYYMMDD/.env /opt/Abricol_Assistant/.env

# Или создайте новый
nano /opt/Abricol_Assistant/.env
# Добавьте необходимые переменные:
# BOT_TOKEN=ваш_токен_бота
# DEEPSEEK_API_KEY=ваш_ключ_deepseek
# ADMIN_CHAT_ID=ваш_telegram_id
```

### Восстановление из полного бэкапа

```bash
# 1. Остановка контейнера
docker-compose -f docker-compose.prod.yml down

# 2. Восстановление из архива
tar -xzf /opt/backups/abricol/backup-YYYYMMDD-HHMMSS.tar.gz -C /

# 3. Восстановление прав доступа
chmod 666 /opt/Abricol_Assistant/data/*.db
chmod 666 /opt/Abricol_Assistant/data/*.xlsx
chmod 666 /opt/Abricol_Assistant/data/*.log

# 4. Запуск контейнера
docker-compose -f docker-compose.prod.yml up -d
```

---

## 📊 Полезные команды для мониторинга очистки

### Размеры до и после очистки

```bash
# До очистки
echo "=== ДО ОЧИСТКИ ==="
du -sh /opt/Abricol_Assistant/data
du -sh /opt/Abricol_Assistant/cache
docker system df

# После очистки
echo "=== ПОСЛЕ ОЧИСТКИ ==="
du -sh /opt/Abricol_Assistant/data
du -sh /opt/Abricol_Assistant/cache
docker system df
```

### Список всех файлов для проверки

```bash
# Все файлы в data/
find /opt/Abricol_Assistant/data -type f -exec ls -lh {} \;

# Все файлы в cache/
find /opt/Abricol_Assistant/cache -type f -exec ls -lh {} \;

# Размер каждого файла
du -h /opt/Abricol_Assistant/data/* | sort -h
```

### Статистика использования места

```bash
# Общее использование места
df -h /opt

# Использование места по директориям
du -h --max-depth=1 /opt/Abricol_Assistant | sort -h

# Топ-10 самых больших файлов
find /opt/Abricol_Assistant -type f -exec du -h {} + | sort -rh | head -10
```

---

## ⚡ Быстрые команды очистки

### Самые часто используемые

```bash
# Остановка и удаление контейнера
docker-compose -f docker-compose.prod.yml down

# Очистка Docker (без томов)
docker system prune -a

# Очистка логов
> /opt/Abricol_Assistant/data/bot.log

# Очистка кэша моделей
rm -rf /opt/Abricol_Assistant/cache/models/*

# Проверка места
du -sh /opt/Abricol_Assistant/*
docker system df
```

### Команды для быстрой очистки

```bash
# Полная очистка Docker (ОСТОРОЖНО!)
docker system prune -a --volumes -f

# Очистка только неиспользуемых ресурсов
docker system prune -f

# Очистка логов и перезапуск
> /opt/Abricol_Assistant/data/bot.log && docker-compose -f docker-compose.prod.yml restart
```

---

## ⚠️ Важные предупреждения

1. **Всегда делайте резервную копию** перед очисткой данных
2. **Проверяйте размеры файлов** перед удалением
3. **Не удаляйте `.env`** без создания резервной копии
4. **Тестируйте после очистки** перед использованием в продакшене
5. **Очистка кэша моделей** замедлит первый запуск STT
6. **Удаление баз данных** приведет к потере всех данных
7. **Полная очистка Docker** может удалить данные других проектов
8. **Проверяйте список файлов** перед массовым удалением

---

## 📞 Быстрая справка

```bash
# Остановка и удаление
docker-compose -f docker-compose.prod.yml down

# Очистка Docker
docker system prune -a

# Очистка логов
> /opt/Abricol_Assistant/data/bot.log

# Очистка кэша
rm -rf /opt/Abricol_Assistant/cache/models/*

# Проверка места
du -sh /opt/Abricol_Assistant/*
docker system df

# Диагностика
docker ps -a
docker logs abricol-assistant --tail=50
```

---

**Последнее обновление:** 2025-12-01
