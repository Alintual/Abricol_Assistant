# Быстрые шаги оптимизации на сервере

## Шаг 1: Изменить модель на `tiny`

```bash
cd /opt/Abricol_Assistant
sed -i 's/STT_MODEL_SIZE=.*/STT_MODEL_SIZE=tiny/g' .env
grep STT_MODEL_SIZE .env
```

## Шаг 2: Обновить код

```bash
git pull origin master
```

## Шаг 3: Пересобрать и перезапустить

```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## Шаг 4: Проверить лимиты памяти

```bash
docker stats abricol-assistant --no-stream
```

Должно показать лимит 450MiB.

## Шаг 5: Проверить работу

```bash
# Откройте логи
docker-compose logs -f

# Отправьте голосовое сообщение боту
# Должны увидеть в логах:
# - "Голосовое сообщение скачано"
# - "Конвертация .oga в .wav"
# - "Загрузка модели STT (размер: tiny)"
# - "Транскрибация завершена"
```

---

**Все изменения уже в репозитории! Просто выполните команды выше на сервере.**

