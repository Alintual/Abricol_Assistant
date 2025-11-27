# Инструкция по загрузке проекта в GitHub

## Шаг 1: Создание репозитория на GitHub

1. Зайдите на [GitHub.com](https://github.com) и войдите в свой аккаунт
2. Нажмите кнопку **"+"** в правом верхнем углу → **"New repository"**
3. Заполните форму:
   - **Repository name**: `Abricol_Assistant` (или другое имя)
   - **Description**: "Telegram бот-консультант для школы бильярда Абриколь"
   - **Visibility**: выберите **Public** (открытый) или **Private** (приватный)
   - **НЕ** ставьте галочки на "Add a README file", "Add .gitignore", "Choose a license" (если у вас уже есть эти файлы)
4. Нажмите **"Create repository"**

## Шаг 2: Инициализация Git в локальном проекте

Откройте PowerShell в папке проекта и выполните:

### Если Git еще не инициализирован:

```powershell
# Инициализация Git репозитория
git init

# Добавление всех файлов в индекс
git add .

# Первый коммит
git commit -m "Initial commit: Telegram bot for Abricol billiard school"
```

### Если Git уже инициализирован:

```powershell
# Проверка статуса
git status

# Добавление всех изменений
git add .

# Коммит изменений
git commit -m "Update project files"
```

## Шаг 3: Подключение к удаленному репозиторию

После создания репозитория на GitHub, скопируйте URL репозитория (например: `https://github.com/ваш-username/Abricol_Assistant.git`)

```powershell
# Добавление удаленного репозитория (замените URL на ваш)
git remote add origin https://github.com/ваш-username/Abricol_Assistant.git

# Проверка подключения
git remote -v
```

## Шаг 4: Отправка кода в GitHub

```powershell
# Отправка кода в GitHub (первый раз)
git push -u origin main
```

Если у вас используется ветка `master` вместо `main`:

```powershell
# Переименование ветки (если нужно)
git branch -M main

# Отправка кода
git push -u origin main
```

## Шаг 5: Проверка

Зайдите на GitHub и убедитесь, что все файлы загружены в репозиторий.

---

## Дополнительные команды

### Просмотр истории коммитов:
```powershell
git log --oneline
```

### Просмотр изменений:
```powershell
git status
git diff
```

### Обновление локального репозитория из GitHub:
```powershell
git pull origin main
```

### Создание новой ветки:
```powershell
git checkout -b feature/новая-функция
git push -u origin feature/новая-функция
```

---

## Настройка .gitignore

Убедитесь, что в корне проекта есть файл `.gitignore` со следующим содержимым:

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/
ENV/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Базы данных
*.db
*.sqlite
*.sqlite3

# Логи
*.log

# Переменные окружения
.env
.env.local

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Docker
.dockerignore

# Временные файлы
*.tmp
*.temp
leads.xlsx.tmp
```

---

## Решение проблем

### Ошибка: "remote origin already exists"
```powershell
# Удаление старого подключения
git remote remove origin

# Добавление нового
git remote add origin https://github.com/ваш-username/Abricol_Assistant.git
```

### Ошибка: "failed to push some refs"
```powershell
# Получение изменений с GitHub
git pull origin main --allow-unrelated-histories

# Повторная отправка
git push -u origin main
```

### Ошибка аутентификации
Если GitHub требует аутентификацию:

1. **Через Personal Access Token (рекомендуется):**
   - Создайте токен: GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Используйте токен вместо пароля при `git push`

2. **Через SSH (альтернатива):**
   ```powershell
   # Генерация SSH ключа (если еще нет)
   ssh-keygen -t ed25519 -C "your_email@example.com"
   
   # Добавление ключа в GitHub: Settings → SSH and GPG keys
   
   # Изменение URL на SSH
   git remote set-url origin git@github.com:ваш-username/Abricol_Assistant.git
   ```

---

## Быстрая команда для первого раза

Если проект еще не в Git, выполните все команды последовательно:

```powershell
# 1. Инициализация
git init

# 2. Добавление файлов
git add .

# 3. Первый коммит
git commit -m "Initial commit"

# 4. Подключение к GitHub (замените URL)
git remote add origin https://github.com/ваш-username/Abricol_Assistant.git

# 5. Переименование ветки в main (если нужно)
git branch -M main

# 6. Отправка в GitHub
git push -u origin main
```

---

## Полезные ссылки

- [GitHub Docs](https://docs.github.com/)
- [Git Handbook](https://guides.github.com/introduction/git-handbook/)
- [Git Cheat Sheet](https://education.github.com/git-cheat-sheet-education.pdf)

