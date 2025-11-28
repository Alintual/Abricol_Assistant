# 🚀 Развертывание на Timeweb

## 📋 Пошаговая инструкция

### Шаг 1: Создание VPS на Timeweb

1. Зайдите на https://timeweb.com/
2. Войдите в панель управления
3. Перейдите в раздел **VPS**
4. Создайте новый сервер:
   - **ОС:** Ubuntu 22.04 LTS
   - **Конфигурация:** 4 vCPU, 8 GB RAM, 100 GB SSD (рекомендуется)
   - **Минимум:** 2 vCPU, 4 GB RAM, 50 GB SSD

---

### Шаг 2: Подключение к серверу

Получите данные для подключения:
- IP адрес сервера
- Логин (обычно `root`)
- Пароль (или SSH ключ)

Подключитесь по SSH:
```bash
ssh root@ваш_ip_адрес
```

---

### Шаг 3: Установка Docker и Docker Compose

```bash
# Обновление системы
apt update && apt upgrade -y

# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Проверка установки
docker --version

# Установка Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Проверка
docker-compose --version
```

---

### Шаг 4: Клонирование проекта

```bash
# Переход в директорию
cd /opt

# Клонирование репозитория
git clone https://github.com/Alintual/Abricol_Assistant.git
cd Abricol_Assistant

# Проверка файлов
ls -la
```

---

### Шаг 5: Создание файла .env

```bash
# Создание файла .env
nano .env
```

Добавьте следующие переменные:

```env
# Telegram Bot (ОБЯЗАТЕЛЬНО)
BOT_TOKEN=7802643529:AAFB3KbXbK5I303JtkbiS44uCJeW6IvxCas

# DeepSeek API (ОБЯЗАТЕЛЬНО)
DEEPSEEK_API_KEY=ваш_ключ_от_DeepSeek

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

**Сохраните:** `Ctrl+O`, `Enter`, `Ctrl+X`

---

### Шаг 6: Создание директорий и файлов для данных

```bash
# Создание директорий
mkdir -p cache/models
mkdir -p data

# Создание пустых файлов баз данных (если их нет)
touch abricol.db knowledge.db leads.xlsx bot.log

# Установка прав доступа
chmod 666 abricol.db knowledge.db leads.xlsx bot.log
```

**Важно:** Файлы баз данных должны существовать перед запуском контейнера, иначе SQLite не сможет их создать из-за монтирования томов.

---

### Шаг 7: Сборка и запуск контейнера

Запустить Docker на VPS
Выполните по очереди:


bash
systemctl status docker
Если в выводе не active (running), запустите:


bash
systemctl start docker
systemctl enable docker
enable сделает так, чтобы Docker запускался сам при перезагрузке сервера.

Проверьте ещё раз:


bash
systemctl status docker
Должно быть что-то вроде: Active: 

Повторить сборку
Теперь переходите в каталог проекта:


bash
cd /opt/Abricol_Assistant
И запускайте:


bash
docker compose build --progress=plain
# или, если у вас только docker-compose (старая версия):
# docker-compose build
После успешной сборки — запуск:


bash
docker compose up -d
# или
# docker-compose up -d

```bash
# Сборка образа (первый раз может занять 10-15 минут)
docker-compose build

# Запуск в фоновом режиме
docker-compose up -d

# Проверка статуса
docker-compose ps

# Просмотр логов
docker-compose logs -f
```

---

### Шаг 8: Настройка автозапуска

Создайте systemd сервис:

```bash
nano /etc/systemd/system/abricol-bot.service
```

Добавьте содержимое:

```ini
[Unit]
Description=Abricol Assistant Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/Abricol_Assistant
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

Активируйте сервис:

```bash
# Перезагрузка systemd
systemctl daemon-reload

# Включение автозапуска
systemctl enable abricol-bot.service

# Запуск сервиса
systemctl start abricol-bot.service

# Проверка статуса
systemctl status abricol-bot.service
```

---

## 🔍 Проверка работы

### Просмотр логов

```bash
# Логи в реальном времени
docker-compose logs -f

# Последние 100 строк
docker-compose logs --tail=100

# Логи за последний час
docker-compose logs --since 1h
```

### Проверка в Telegram

1. Откройте Telegram
2. Найдите вашего бота
3. Отправьте `/start`
4. Проверьте ответ

---

## 🛠️ Управление ботом

### Перезапуск

```bash
cd /opt/Abricol_Assistant
docker-compose restart
```

### Остановка

```bash
docker-compose stop
```

### Запуск

```bash
docker-compose start
```

### Полная перезагрузка

```bash
docker-compose down
docker-compose up -d
```

---

## 🔄 Обновление бота

```bash
# Переход в директорию проекта
cd /opt/Abricol_Assistant

# Получение обновлений из GitHub
git pull origin master

# Пересборка и перезапуск
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

Или используйте скрипт:

```bash
# Создание скрипта обновления
nano /opt/Abricol_Assistant/update.sh
```

Добавьте:

```bash
#!/bin/bash
cd /opt/Abricol_Assistant
git pull origin master
docker-compose down
docker-compose build --no-cache
docker-compose up -d
echo "Бот обновлен!"
```

Сделайте исполняемым:

```bash
chmod +x /opt/Abricol_Assistant/update.sh
```

Запуск обновления:

```bash
/opt/Abricol_Assistant/update.sh
```

---

## 💾 Резервное копирование

Создайте скрипт для бэкапа:

```bash
nano /opt/Abricol_Assistant/backup.sh
```

Добавьте:

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Бэкап базы данных и файлов
docker-compose exec -T abricol-bot tar czf - /app/abricol.db /app/knowledge.db /app/leads.xlsx > $BACKUP_DIR/db_$DATE.tar.gz

# Бэкап конфигурации
tar czf $BACKUP_DIR/config_$DATE.tar.gz .env docker-compose.yml Dockerfile

# Удаление старых бэкапов (старше 7 дней)
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Бэкап создан: $DATE"
```

Настройте автоматический бэкап:

```bash
chmod +x /opt/Abricol_Assistant/backup.sh

# Добавление в cron (ежедневно в 2:00)
crontab -e
# Добавьте строку:
0 2 * * * /opt/Abricol_Assistant/backup.sh
```

---

## 🐛 Решение проблем

### Ошибка "unable to open database file"

**Причина:** Файлы баз данных не существуют или нет прав доступа.

**Решение:**
```bash
# Создайте файлы баз данных
touch abricol.db knowledge.db leads.xlsx bot.log

# Установите права доступа
chmod 666 abricol.db knowledge.db leads.xlsx bot.log

# Перезапустите контейнер
docker-compose restart
```

### Бот не запускается

```bash
# Проверьте логи
docker-compose logs

# Проверьте статус контейнера
docker-compose ps

# Проверьте файл .env
cat .env

# Проверьте существование файлов баз данных
ls -la abricol.db knowledge.db
```

### Ошибка "Cannot connect to Docker daemon"

```bash
# Перезапуск Docker
systemctl restart docker

# Проверка статуса Docker
systemctl status docker
```

### Высокое использование памяти

```bash
# Проверка использования ресурсов
docker stats

# Если нужно, уменьшите размер модели в .env:
# STT_MODEL_SIZE=small (вместо medium)
```

### Проблемы с сетью

```bash
# Проверка подключения к интернету
ping 8.8.8.8

# Проверка DNS
nslookup api.deepseek.com
```

---

## 📊 Мониторинг ресурсов

```bash
# Использование CPU и памяти
docker stats

# Использование диска
df -h

# Использование памяти
free -h
```

---

## 🔒 Безопасность

### Настройка Firewall

```bash
# Установка UFW
apt install ufw -y

# Разрешить SSH
ufw allow 22/tcp

# Включить firewall
ufw enable

# Проверка статуса
ufw status
```

### Обновление системы

```bash
# Настройка автоматических обновлений безопасности
apt install unattended-upgrades -y
dpkg-reconfigure -plow unattended-upgrades
```

---

## 📞 Полезные ссылки

- [Timeweb - Панель управления](https://timeweb.com/)
- [Timeweb - Документация](https://timeweb.com/ru/docs/)
- [Docker Documentation](https://docs.docker.com/)
- [Ваш репозиторий](https://github.com/Alintual/Abricol_Assistant)

---

## ✅ Чеклист развертывания

- [ ] Создан VPS на Timeweb
- [ ] Установлен Docker и Docker Compose
- [ ] Клонирован репозиторий
- [ ] Создан файл .env с переменными
- [ ] Собран Docker образ
- [ ] Запущен контейнер
- [ ] Настроен автозапуск через systemd
- [ ] Проверена работа бота в Telegram
- [ ] Настроено резервное копирование
- [ ] Настроена безопасность (firewall)

---

**Удачи с развертыванием на Timeweb! 🚀**

