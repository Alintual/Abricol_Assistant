# Очистка диска Docker

## Почему Docker занимает место на диске?

При сборке образа Docker создает **слои** (layers), которые кэшируются для ускорения последующих сборок. Это занимает место на диске:

1. **Базовые образы** (например, `python:3.11-slim`) - ~100-200 МБ
2. **Слои образа бота** - каждый слой сохраняется отдельно
3. **Кэш сборки** - промежуточные слои от предыдущих сборок
4. **Контейнеры** - работающие и остановленные
5. **Тома (volumes)** - данные контейнеров
6. **Неиспользуемые образы** - старые версии образов

**Итого:** При сборке образа бота может заниматься **2-4 ГБ** дискового пространства.

---

## Проверка использования диска

### Посмотреть статистику Docker:
```powershell
docker system df
```

Эта команда покажет:
- **Images** - размер всех образов
- **Containers** - размер всех контейнеров
- **Local Volumes** - размер томов
- **Build Cache** - размер кэша сборки

### Детальная информация:
```powershell
# Размер каждого образа
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# Размер каждого контейнера
docker ps -a --format "table {{.Names}}\t{{.Size}}"
```

---

## Очистка диска (от безопасной к агрессивной)

### 1. Безопасная очистка (рекомендуется)

Удаляет только **неиспользуемые** ресурсы:

```powershell
# Удалить остановленные контейнеры
docker container prune -f

# Удалить dangling образы (без тегов)
docker image prune -f

# Удалить неиспользуемые тома
docker volume prune -f

# Удалить неиспользуемые сети
docker network prune -f

# Все сразу (безопасно)
docker system prune -f
```

**Что удаляется:**
- ✅ Остановленные контейнеры
- ✅ Образы без тегов (`<none>:<none>`)
- ✅ Неиспользуемые тома
- ✅ Неиспользуемые сети

**Что НЕ удаляется:**
- ✅ Образы с тегами (ваши образы останутся)
- ✅ Работающие контейнеры
- ✅ Используемые тома

---

### 2. Очистка кэша сборки

Освобождает **больше всего места**, но замедлит следующую сборку:

```powershell
# Удалить весь кэш сборки
docker builder prune -af
```

**Что удаляется:**
- ✅ Весь кэш сборки (промежуточные слои)
- ✅ Неиспользуемые образы сборки

**Результат:** Может освободить **1-3 ГБ** места.

---

### 3. Агрессивная очистка (осторожно!)

Удаляет **ВСЕ** неиспользуемые ресурсы, включая образы с тегами:

```powershell
# Удалить ВСЕ неиспользуемые образы (даже с тегами)
docker image prune -a -f

# Полная очистка системы (кроме работающих контейнеров)
docker system prune -a -f

# Полная очистка + кэш сборки
docker system prune -a -f --volumes
docker builder prune -af
```

**⚠️ ВНИМАНИЕ:**
- Удалит **все** неиспользуемые образы (даже `python:3.11`)
- При следующей сборке Docker снова скачает базовые образы
- Это займет время, но освободит максимум места

---

### 4. Удаление конкретных ресурсов

Если нужно удалить конкретный образ или контейнер:

```powershell
# Удалить конкретный контейнер
docker rm abricol-assistant

# Удалить конкретный образ
docker rmi abricol-assistant

# Удалить образ с принуждением
docker rmi abricol-assistant -f
```

---

## Рекомендуемая стратегия очистки

### Еженедельная очистка (безопасная):
```powershell
docker system prune -f
```

### Ежемесячная очистка (с кэшем):
```powershell
docker system prune -f
docker builder prune -af
```

### При нехватке места (агрессивная):
```powershell
docker system prune -a -f
docker builder prune -af
```

---

## Автоматическая очистка

### Настройка Docker Desktop (Windows):

1. Откройте **Docker Desktop**
2. Перейдите в **Settings** → **Resources** → **Advanced**
3. Включите **"Automatically clean up unused data"**
4. Настройте расписание очистки

### Через PowerShell скрипт:

Создайте файл `cleanup_docker.ps1` (уже создан в проекте) и запускайте периодически:

```powershell
.\cleanup_docker.ps1
```

---

## Где Docker хранит данные на Windows?

Docker Desktop на Windows хранит данные в **WSL2** (Windows Subsystem for Linux):

- **Путь в WSL2:** `/var/lib/docker/`
- **Виртуальный диск:** Обычно `C:\Users\<User>\AppData\Local\Docker\wsl\data\ext4.vhdx`

### Изменение размера виртуального диска:

1. Остановите Docker Desktop
2. Откройте PowerShell от имени администратора:
```powershell
# Список WSL дистрибутивов
wsl --list --verbose

# Остановить WSL
wsl --shutdown

# Оптимизировать диск (освободит место)
diskpart
select vdisk file="C:\Users\<User>\AppData\Local\Docker\wsl\data\ext4.vhdx"
compact vdisk
exit
```

---

## Проверка после очистки

После очистки проверьте результат:

```powershell
# Статистика до и после
docker system df

# Список оставшихся образов
docker images

# Список контейнеров
docker ps -a
```

---

## Частые вопросы

### Q: Безопасно ли удалять кэш сборки?
**A:** Да, но следующая сборка будет медленнее, так как Docker не сможет использовать кэшированные слои.

### Q: Удалится ли мой образ бота?
**A:** Нет, если он используется контейнером. Но если контейнер остановлен и образ не используется, он может быть удален при агрессивной очистке.

### Q: Как освободить максимум места?
**A:** Выполните:
```powershell
docker system prune -a -f
docker builder prune -af
```

### Q: Можно ли настроить автоматическую очистку?
**A:** Да, в Docker Desktop есть настройка "Automatically clean up unused data" в Settings → Resources → Advanced.

---

## Быстрая команда для освобождения места

Если нужно быстро освободить место:

```powershell
# Остановить контейнер бота
docker-compose down

# Полная очистка (кроме работающих контейнеров)
docker system prune -a -f
docker builder prune -af

# Пересобрать и запустить
docker-compose build --no-cache
docker-compose up -d
```

**Результат:** Освободит **2-4 ГБ** места, но следующая сборка займет больше времени.

---

## Как полностью закрыть Docker

### Способ 1: Через Docker Desktop (рекомендуется)

1. Откройте **Docker Desktop**
2. Нажмите на **иконку шестеренки** (Settings) в правом верхнем углу
3. Выберите **"Quit Docker Desktop"** из меню
4. Или просто **закройте окно Docker Desktop** - он останется в системном трее
5. **Правый клик** на иконку Docker в трее → **"Quit Docker Desktop"**

### Способ 2: Через PowerShell (остановить все контейнеры и Docker)

```powershell
# Остановить все работающие контейнеры
docker stop $(docker ps -q)

# Остановить контейнер бота (если запущен)
docker-compose down

# Закрыть Docker Desktop через PowerShell
Stop-Process -Name "Docker Desktop" -Force
```

### Способ 3: Через Диспетчер задач

1. Нажмите **Ctrl + Shift + Esc** (открыть Диспетчер задач)
2. Найдите процессы:
   - `Docker Desktop`
   - `com.docker.backend`
   - `com.docker.proxy`
3. **Правый клик** → **"Завершить задачу"**

### Способ 4: Остановить WSL2 (если Docker не закрывается)

Docker Desktop использует WSL2. Если Docker не закрывается:

```powershell
# Остановить все контейнеры Docker
docker stop $(docker ps -q)

# Остановить WSL2 (это остановит Docker)
wsl --shutdown
```

**⚠️ ВНИМАНИЕ:** Это остановит **все** WSL2 дистрибутивы, не только Docker.

---

## Проверка, что Docker закрыт

После закрытия Docker проверьте:

```powershell
# Эта команда должна выдать ошибку, если Docker закрыт
docker ps
```

Если Docker закрыт, вы увидите:
```
error during connect: This error may indicate that the docker daemon is not running.
```

---

## Автоматический запуск Docker при старте Windows

Если Docker запускается автоматически и вы хотите это отключить:

1. Откройте **Docker Desktop**
2. **Settings** → **General**
3. Снимите галочку **"Start Docker Desktop when you log in"**
4. Нажмите **"Apply & Restart"**

---

## Быстрая команда для остановки всего

Если нужно быстро остановить все контейнеры и закрыть Docker:

```powershell
# Остановить все контейнеры
docker stop $(docker ps -q) 2>$null

# Остановить Docker Desktop
Stop-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
Stop-Process -Name "com.docker.backend" -ErrorAction SilentlyContinue
```

Или создайте файл `stop_docker.ps1`:

```powershell
Write-Host "Остановка всех контейнеров Docker..." -ForegroundColor Yellow
docker stop $(docker ps -q) 2>$null

Write-Host "Остановка Docker Desktop..." -ForegroundColor Yellow
Stop-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
Stop-Process -Name "com.docker.backend" -ErrorAction SilentlyContinue

Write-Host "Docker остановлен!" -ForegroundColor Green
```

