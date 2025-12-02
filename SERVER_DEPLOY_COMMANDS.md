# 🚀 Справочник команд: Развертывание и управление на сервере

Полный список команд для развертывания, тестирования, обновления и управления ботом на продакшн сервере.

---

## 📋 Содержание

1. [Подключение к серверу](#подключение-к-серверу)
2. [Первоначальное развертывание](#первоначальное-развертывание)
3. [Обновление кода](#обновление-кода)
4. [Управление контейнером](#управление-контейнером)
5. [Пересборка образа](#пересборка-образа)
6. [Тестирование](#тестирование)
7. [Мониторинг и логи](#мониторинг-и-логи)
8. [Работа с базой знаний](#работа-с-базой-знаний)
9. [Резервное копирование](#резервное-копирование)
10. [Быстрые команды](#быстрые-команды)

---

## 🔌 Подключение к серверу

```bash
# Подключение по SSH
ssh root@ваш_ip_адрес

# Переход в директорию проекта
cd /opt/Abricol_Assistant

# Проверка текущей директории
pwd
```

---

## 🎯 Первоначальное развертывание

### Полное развертывание с нуля

```bash
# 1. Переход в директорию проекта
cd /opt/Abricol_Assistant

# 2. Проверка наличия .env файла
ls -la .env

# 3. Если .env отсутствует, создайте его
nano .env
# Добавьте необходимые переменные:
# BOT_TOKEN=ваш_токен_бота
# DEEPSEEK_API_KEY=ваш_ключ_deepseek
# ADMIN_CHAT_ID=ваш_telegram_id
# DB_PATH=sqlite+aiosqlite:///./abricol.db
# LEADS_EXCEL_PATH=./leads.xlsx

# 4. Создание необходимых директорий
mkdir -p data cache/models
chmod -R 755 data cache/models

# 5. Создание файлов баз данных (если их нет)
touch data/abricol.db data/knowledge.db data/leads.xlsx data/bot.log
chmod 666 data/*.db data/*.xlsx data/*.log

# 6. Остановка старых контейнеров (если есть)
docker-compose -f docker-compose.prod.yml down

# 7. Сборка образа (первый раз может занять 10-15 минут)
docker-compose -f docker-compose.prod.yml build

# 8. Запуск контейнера
docker-compose -f docker-compose.prod.yml up -d

# 9. Проверка статуса
docker-compose -f docker-compose.prod.yml ps

# 10. Просмотр логов
docker-compose -f docker-compose.prod.yml logs -f
```

### Использование скрипта развертывания

```bash
# Если есть скрипт deploy_timeweb.sh
chmod +x deploy_timeweb.sh
./deploy_timeweb.sh
```

---

## 🔄 Обновление кода

### Вариант 1: Через Git (рекомендуется)

```bash
# 1. Переход в директорию проекта
cd /opt/Abricol_Assistant

# 2. Получение последних изменений
git pull origin master

# 3. Остановка контейнера
docker-compose -f docker-compose.prod.yml down

# 4. Пересборка образа с новым кодом
docker-compose -f docker-compose.prod.yml build

# 5. Запуск обновленного контейнера
docker-compose -f docker-compose.prod.yml up -d

# 6. Проверка логов
docker-compose -f docker-compose.prod.yml logs -f
```

### Вариант 2: Быстрое обновление (без остановки)

```bash
cd /opt/Abricol_Assistant
git pull origin master
docker-compose -f docker-compose.prod.yml up -d --build
```

### Вариант 3: Копирование файла напрямую

```bash
# На локальном компьютере
scp src/db/leads_excel.py root@ваш_ip:/opt/Abricol_Assistant/src/db/leads_excel.py

# На сервере
cd /opt/Abricol_Assistant
docker-compose -f docker-compose.prod.yml up -d --build
```

### Вариант 4: Обновление только кода без пересборки (не рекомендуется)

```bash
# Только если изменения не требуют пересборки образа
cd /opt/Abricol_Assistant
git pull origin master
docker-compose -f docker-compose.prod.yml restart
```

---

## 🎮 Управление контейнером

### Запуск

```bash
# Запуск в фоновом режиме
docker-compose -f docker-compose.prod.yml up -d

# Запуск с просмотром логов
docker-compose -f docker-compose.prod.yml up

# Запуск с пересборкой
docker-compose -f docker-compose.prod.yml up -d --build
```

### Остановка

```bash
# Временная остановка (контейнер остается)
docker-compose -f docker-compose.prod.yml stop

# Полная остановка с удалением контейнера
docker-compose -f docker-compose.prod.yml down

# Остановка с удалением всех связанных ресурсов
docker-compose -f docker-compose.prod.yml down --remove-orphans
```

### Перезапуск

```bash
# Перезапуск контейнера
docker-compose -f docker-compose.prod.yml restart

# Перезапуск с пересборкой
docker-compose -f docker-compose.prod.yml up -d --build

# Перезапуск конкретного сервиса
docker-compose -f docker-compose.prod.yml restart abricol-bot
```

### Проверка статуса

```bash
# Статус контейнера
docker-compose -f docker-compose.prod.yml ps

# Детальная информация
docker-compose -f docker-compose.prod.yml ps -a

# Использование ресурсов
docker stats abricol-assistant

# Использование ресурсов без обновления
docker stats abricol-assistant --no-stream
```

---

## 🔨 Пересборка образа

### Полная пересборка

```bash
# Пересборка без кэша (чистая сборка)
docker-compose -f docker-compose.prod.yml build --no-cache

# Пересборка с кэшем (быстрее)
docker-compose -f docker-compose.prod.yml build

# Пересборка и запуск
docker-compose -f docker-compose.prod.yml up -d --build

# Пересборка конкретного сервиса
docker-compose -f docker-compose.prod.yml build abricol-bot
```

### Пересборка после изменения зависимостей

```bash
# 1. Обновите requirements.txt на сервере
# 2. Пересоберите образ
docker-compose -f docker-compose.prod.yml build --no-cache

# 3. Запустите контейнер
docker-compose -f docker-compose.prod.yml up -d
```

---

## 🧪 Тестирование

### Проверка работы бота

```bash
# 1. Проверка статуса контейнера
docker-compose -f docker-compose.prod.yml ps

# 2. Проверка логов на ошибки
docker-compose -f docker-compose.prod.yml logs | grep -i error

# 3. Проверка последних логов
docker-compose -f docker-compose.prod.yml logs --tail=50

# 4. Тест подключения к базе данных
docker-compose -f docker-compose.prod.yml exec abricol-bot python -c "
import asyncio
from src.db.session import init_engine_and_db
asyncio.run(init_engine_and_db())
print('✅ База данных работает')
"
```

### Выполнение команд внутри контейнера

```bash
# Вход в контейнер (интерактивная сессия)
docker-compose -f docker-compose.prod.yml exec abricol-bot bash

# Выполнение Python команды
docker-compose -f docker-compose.prod.yml exec abricol-bot python -c "print('Hello from container')"

# Проверка версии Python
docker-compose -f docker-compose.prod.yml exec abricol-bot python --version

# Проверка установленных пакетов
docker-compose -f docker-compose.prod.yml exec abricol-bot pip list

# Проверка переменных окружения
docker-compose -f docker-compose.prod.yml exec abricol-bot env | grep -E "BOT_TOKEN|DEEPSEEK"
```

### Тестирование в Telegram

1. Откройте Telegram
2. Найдите вашего бота
3. Отправьте команду `/start`
4. Проверьте ответ бота
5. Протестируйте основные функции:
   - Задайте вопрос из FAQ
   - Попробуйте записаться на обучение
   - Отправьте голосовое сообщение (если поддерживается)

### Тестирование после обновления

```bash
# 1. Обновите код
git pull origin master

# 2. Пересоберите и перезапустите
docker-compose -f docker-compose.prod.yml up -d --build

# 3. Проверьте логи на ошибки
docker-compose -f docker-compose.prod.yml logs --tail=100 | grep -i error

# 4. Протестируйте в Telegram
```

---

## 📊 Мониторинг и логи

### Просмотр логов

```bash
# Логи в реальном времени
docker-compose -f docker-compose.prod.yml logs -f

# Последние 100 строк логов
docker-compose -f docker-compose.prod.yml logs --tail=100

# Логи за последний час
docker-compose -f docker-compose.prod.yml logs --since 1h

# Логи за последние 30 минут
docker-compose -f docker-compose.prod.yml logs --since 30m

# Логи конкретного сервиса
docker-compose -f docker-compose.prod.yml logs -f abricol-bot

# Поиск ошибок в логах
docker-compose -f docker-compose.prod.yml logs | grep -i error

# Поиск предупреждений
docker-compose -f docker-compose.prod.yml logs | grep -i warning

# Поиск по конкретному тексту
docker-compose -f docker-compose.prod.yml logs | grep "текст_поиска"
```

### Просмотр логов из файла

```bash
# Логи из файла на сервере
tail -f /opt/Abricol_Assistant/data/bot.log

# Последние 50 строк
tail -n 50 /opt/Abricol_Assistant/data/bot.log

# Поиск в логах
grep -i "error" /opt/Abricol_Assistant/data/bot.log

# Поиск по дате
grep "2025-12-01" /opt/Abricol_Assistant/data/bot.log

# Подсчет ошибок
grep -i "error" /opt/Abricol_Assistant/data/bot.log | wc -l
```

### Мониторинг ресурсов

```bash
# Использование ресурсов контейнера
docker stats abricol-assistant

# Использование ресурсов без обновления
docker stats abricol-assistant --no-stream

# Использование дискового пространства
df -h

# Размер директорий
du -sh /opt/Abricol_Assistant/data
du -sh /opt/Abricol_Assistant/cache
du -sh /opt/Abricol_Assistant

# Детальная информация о размерах
du -h --max-depth=1 /opt/Abricol_Assistant
```

---

## 📚 Работа с базой знаний

### Сборка базы знаний

```bash
# Сборка базы знаний внутри контейнера
docker-compose -f docker-compose.prod.yml exec abricol-bot python -m src.build_kb

# Сборка с просмотром вывода
docker-compose -f docker-compose.prod.yml exec -T abricol-bot python -m src.build_kb

# Проверка размера базы знаний
ls -lh /opt/Abricol_Assistant/data/knowledge.db

# Проверка содержимого базы знаний
docker-compose -f docker-compose.prod.yml exec abricol-bot python -c "
import sqlite3
conn = sqlite3.connect('/app/data/knowledge.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM documents')
print(f'Документов в базе: {cursor.fetchone()[0]}')
conn.close()
"
```

### Обновление базы знаний

```bash
# 1. Добавьте новые PDF файлы в src/knowledge/data/
# 2. Пересоберите базу знаний
docker-compose -f docker-compose.prod.yml exec abricol-bot python -m src.build_kb

# 3. Проверьте логи на ошибки
docker-compose -f docker-compose.prod.yml logs | grep -i "build_kb"
```

### Проверка базы знаний

```bash
# Проверка наличия файла
test -f /opt/Abricol_Assistant/data/knowledge.db && echo "✅ База знаний существует" || echo "❌ База знаний отсутствует"

# Проверка размера
ls -lh /opt/Abricol_Assistant/data/knowledge.db
```

---

## 💾 Резервное копирование

### Создание резервной копии данных

```bash
# Создание директории для бэкапов
mkdir -p /opt/backups/abricol

# Резервная копия всех данных
tar -czf /opt/backups/abricol/backup-$(date +%Y%m%d-%H%M%S).tar.gz \
    /opt/Abricol_Assistant/data \
    /opt/Abricol_Assistant/.env

# Резервная копия только баз данных
cp /opt/Abricol_Assistant/data/abricol.db /opt/backups/abricol/abricol-$(date +%Y%m%d).db
cp /opt/Abricol_Assistant/data/knowledge.db /opt/backups/abricol/knowledge-$(date +%Y%m%d).db
cp /opt/Abricol_Assistant/data/leads.xlsx /opt/backups/abricol/leads-$(date +%Y%m%d).xlsx

# Резервная копия с сохранением прав доступа
tar -czf /opt/backups/abricol/full-backup-$(date +%Y%m%d-%H%M%S).tar.gz \
    --preserve-permissions \
    /opt/Abricol_Assistant/data \
    /opt/Abricol_Assistant/.env \
    /opt/Abricol_Assistant/cache
```

### Восстановление из резервной копии

```bash
# Остановка контейнера
docker-compose -f docker-compose.prod.yml down

# Восстановление данных
tar -xzf /opt/backups/abricol/backup-YYYYMMDD-HHMMSS.tar.gz -C /

# Восстановление прав доступа
chmod 666 /opt/Abricol_Assistant/data/*.db
chmod 666 /opt/Abricol_Assistant/data/*.xlsx
chmod 666 /opt/Abricol_Assistant/data/*.log

# Запуск контейнера
docker-compose -f docker-compose.prod.yml up -d
```

### Автоматическое резервное копирование

```bash
# Создание скрипта для автоматического бэкапа
cat > /opt/backups/abricol/auto-backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/backups/abricol"
DATE=$(date +%Y%m%d-%H%M%S)
mkdir -p $BACKUP_DIR
tar -czf $BACKUP_DIR/backup-$DATE.tar.gz \
    /opt/Abricol_Assistant/data \
    /opt/Abricol_Assistant/.env
# Удаление старых бэкапов (старше 7 дней)
find $BACKUP_DIR -name "backup-*.tar.gz" -mtime +7 -delete
EOF

chmod +x /opt/backups/abricol/auto-backup.sh

# Добавление в cron (ежедневно в 2:00)
# crontab -e
# 0 2 * * * /opt/backups/abricol/auto-backup.sh
```

---

## 🔧 Полезные команды

### Проверка конфигурации

```bash
# Проверка синтаксиса docker-compose файла
docker-compose -f docker-compose.prod.yml config

# Проверка переменных окружения
docker-compose -f docker-compose.prod.yml exec abricol-bot env | grep -E "BOT_TOKEN|DEEPSEEK"

# Проверка версии Docker
docker --version
docker-compose --version
```

### Работа с сетью

```bash
# Просмотр сетей
docker network ls

# Информация о сети
docker network inspect abricol-network

# Проверка подключения контейнера к сети
docker network inspect abricol-network | grep abricol-assistant
```

### Проверка файлов

```bash
# Проверка наличия важных файлов
test -f /opt/Abricol_Assistant/.env && echo "✅ .env существует" || echo "❌ .env отсутствует"
test -f /opt/Abricol_Assistant/data/abricol.db && echo "✅ База данных существует" || echo "❌ База данных отсутствует"

# Проверка прав доступа
ls -la /opt/Abricol_Assistant/data/
```

---

## ⚡ Быстрые команды

### Самые часто используемые

```bash
# Статус контейнера
docker-compose -f docker-compose.prod.yml ps

# Логи в реальном времени
docker-compose -f docker-compose.prod.yml logs -f

# Перезапуск
docker-compose -f docker-compose.prod.yml restart

# Обновление и перезапуск
cd /opt/Abricol_Assistant && git pull && docker-compose -f docker-compose.prod.yml up -d --build

# Остановка
docker-compose -f docker-compose.prod.yml down

# Запуск
docker-compose -f docker-compose.prod.yml up -d
```

### Команды для диагностики

```bash
# Проверка ошибок в логах
docker-compose -f docker-compose.prod.yml logs | grep -i error | tail -20

# Использование ресурсов
docker stats abricol-assistant --no-stream

# Размер данных
du -sh /opt/Abricol_Assistant/data
```

---

## ⚠️ Важные замечания

1. **Всегда делайте резервную копию** перед обновлением
2. **Проверяйте логи** после каждого изменения
3. **Тестируйте в Telegram** после обновления
4. **Не удаляйте директорию `data/`** - там хранятся все данные
5. **Файл `.env`** содержит секретные данные - не коммитьте его в Git
6. **Проверяйте статус контейнера** перед выполнением команд
7. **Используйте `--build`** при изменении кода или зависимостей

---

## 📞 Быстрая справка

```bash
# Статус
docker-compose -f docker-compose.prod.yml ps

# Логи
docker-compose -f docker-compose.prod.yml logs -f

# Перезапуск
docker-compose -f docker-compose.prod.yml restart

# Обновление
cd /opt/Abricol_Assistant && git pull && docker-compose -f docker-compose.prod.yml up -d --build

# Остановка
docker-compose -f docker-compose.prod.yml down

# Запуск
docker-compose -f docker-compose.prod.yml up -d
```

---

**Последнее обновление:** 2025-12-01
