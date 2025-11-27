# Установка Git на Windows

## Способ 1: Официальный установщик (рекомендуется)

### Шаг 1: Скачивание Git

1. Откройте браузер и перейдите на официальный сайт:
   - **https://git-scm.com/download/win**
   - Или прямая ссылка: **https://github.com/git-for-windows/git/releases/latest**

2. Скачайте последнюю версию установщика:
   - Для 64-битных систем: `Git-2.x.x-64-bit.exe`
   - Для 32-битных систем: `Git-2.x.x-32-bit.exe`

### Шаг 2: Установка

1. Запустите скачанный файл `.exe`
2. Следуйте инструкциям установщика:
   - **Лицензия**: Нажмите "Next"
   - **Выбор компонентов**: Оставьте по умолчанию (или выберите нужные)
   - **Редактор по умолчанию**: Выберите "Use Visual Studio Code as Git's default editor" или "Nano" (простой редактор)
   - **Имя ветки по умолчанию**: Рекомендуется "Let Git decide" или "main"
   - **PATH Environment**: Выберите **"Git from the command line and also from 3rd-party software"** (важно!)
   - **HTTPS транспорты**: Оставьте "Use the OpenSSL library"
   - **Конвертация окончаний строк**: Выберите **"Checkout Windows-style, commit Unix-style line endings"**
   - **Эмулятор терминала**: Выберите "Use Windows' default console window"
   - **Дополнительные опции**: Оставьте по умолчанию
   - **Экспериментальные опции**: Можно оставить пустым

3. Нажмите **"Install"** и дождитесь завершения установки

### Шаг 3: Проверка установки

Откройте **PowerShell** или **Command Prompt** и выполните:

```powershell
git --version
```

Если установка прошла успешно, вы увидите версию Git, например:
```
git version 2.42.0
```

---

## Способ 2: Через пакетный менеджер (альтернатива)

### Через Chocolatey (если установлен):

```powershell
# От имени администратора
choco install git
```

### Через Winget (Windows 10/11):

```powershell
winget install --id Git.Git -e --source winget
```

---

## Способ 3: Через GitHub Desktop (для начинающих)

GitHub Desktop включает Git и предоставляет графический интерфейс:

1. Скачайте **GitHub Desktop**: https://desktop.github.com/
2. Установите приложение
3. Git будет установлен автоматически вместе с GitHub Desktop

---

## Настройка Git после установки

После установки настройте Git с вашими данными:

```powershell
# Установка имени пользователя
git config --global user.name "Ваше Имя"

# Установка email (используйте email, привязанный к GitHub)
git config --global user.email "your.email@example.com"

# Проверка настроек
git config --list
```

---

## Проверка работы Git

Выполните несколько команд для проверки:

```powershell
# Версия Git
git --version

# Помощь
git help

# Статус (в папке проекта)
git status
```

---

## Решение проблем

### Проблема: "git is not recognized as an internal or external command"

**Решение:**
1. Перезапустите PowerShell/Command Prompt после установки
2. Проверьте, что Git добавлен в PATH:
   - Откройте "Система" → "Дополнительные параметры системы" → "Переменные среды"
   - В "Системные переменные" найдите "Path"
   - Убедитесь, что там есть путь к Git (обычно `C:\Program Files\Git\cmd`)
3. Если пути нет, переустановите Git и выберите опцию "Git from the command line"

### Проблема: Git установлен, но команды не работают

**Решение:**
1. Закройте и откройте PowerShell заново
2. Проверьте PATH:
   ```powershell
   $env:PATH -split ';' | Select-String "Git"
   ```
3. Если Git не найден, добавьте вручную:
   ```powershell
   [Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Program Files\Git\cmd", "User")
   ```

---

## Полезные ссылки

- **Официальный сайт Git**: https://git-scm.com/
- **Документация Git**: https://git-scm.com/doc
- **Git для Windows**: https://git-for-windows.github.io/
- **GitHub Desktop**: https://desktop.github.com/

---

## Следующие шаги

После установки Git:

1. **Настройте Git** (имя и email)
2. **Создайте аккаунт на GitHub** (если еще нет)
3. **Следуйте инструкции** из файла `GITHUB_SETUP.md` для загрузки проекта

---

## Быстрая установка (краткая версия)

1. Скачайте: https://git-scm.com/download/win
2. Запустите установщик
3. Нажимайте "Next" (оставьте настройки по умолчанию)
4. Выберите "Git from the command line and also from 3rd-party software"
5. Завершите установку
6. Перезапустите PowerShell
7. Проверьте: `git --version`

