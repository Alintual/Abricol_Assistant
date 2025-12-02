# 🚀 Быстрая инструкция: Запуск бота на сервере TimeWeb

## Шаг 1: Подключение к серверу

```bash
ssh root@ваш_ip_адрес
```

## Шаг 2: Установка Docker (если не установлен)

```bash
# Обновление системы
apt update && apt upgrade -y

# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Установка Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Запуск Docker
systemctl start docker
systemctl enable docker
```

## Шаг 3: Клонирование проекта

```bash
cd /opt
git clone https://github.com/Alintual/Abricol_Assistant.git
cd Abricol_Assistant
```

## Шаг 4: Создание файла .env

```bash
nano .env
```

Добавьте в файл (замените значения на свои):

```env
# Telegram Bot (ОБЯЗАТЕЛЬНО)
BOT_TOKEN=ваш_токен_бота

# DeepSeek API (ОБЯЗАТЕЛЬНО)
DEEPSEEK_API_KEY=ваш_ключ_deepseek

# Администратор (опционально)
ADMIN_CHAT_ID=ваш_telegram_id

# DeepSeek настройки (по умолчанию)
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com

# База данных (по умолчанию)
DB_PATH=sqlite+aiosqlite:///./abricol.db

# Excel файл (по умолчанию)
LEADS_EXCEL_PATH=./leads.xlsx

# Speech-to-Text настройки
STT_MODEL_SIZE=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_LANGUAGE=ru
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

## Шаг 5: Развертывание

```bash
# Сделайте скрипты исполняемыми
chmod +x deploy_timeweb.sh update_timeweb.sh status_timeweb.sh

# Запустите развертывание
./deploy_timeweb.sh
```

Скрипт автоматически:
- Проверит Docker
- Создаст необходимые файлы
- Соберет Docker образ (10-15 минут при первом запуске)
- Запустит контейнер с автозапуском
- Соберет базу знаний (если нужно)

**Примечание:** Если сборка базы знаний не запустилась автоматически, выполните:
```bash
docker-compose -f docker-compose.prod.yml exec abricol-bot python -m src.build_kb
```

## Шаг 6: Проверка работы

```bash
# Просмотр логов
docker-compose -f docker-compose.prod.yml logs -f

# Проверка статуса
./status_timeweb.sh
```

## Шаг 7: Проверка в Telegram

1. Откройте Telegram
2. Найдите вашего бота
3. Отправьте `/start`
4. Проверьте ответ

---

## 🔄 Обновление бота

Когда нужно обновить бота:

```bash
cd /opt/Abricol_Assistant
./update_timeweb.sh
```

## 📊 Полезные команды

```bash
# Просмотр логов
docker-compose -f docker-compose.prod.yml logs -f

# Остановка
docker-compose -f docker-compose.prod.yml stop

# Запуск
docker-compose -f docker-compose.prod.yml start

# Перезапуск
docker-compose -f docker-compose.prod.yml restart

# Статус
./status_timeweb.sh
```

## ⚠️ Важно

- На сервере используется `docker-compose.prod.yml` с автозапуском
- Все данные хранятся в директории `data/`
- Логи находятся в `data/bot.log`
- Бот будет автоматически перезапускаться при перезагрузке сервера

---

**Готово! Бот запущен на сервере! 🎉**

