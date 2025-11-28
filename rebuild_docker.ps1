# Скрипт для полной пересборки и перезапуска Docker образа
# Использование: .\rebuild_docker.ps1

# Устанавливаем кодировку UTF-8 для корректного отображения русского текста
try {
    chcp 65001 | Out-Null
    $OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    $PSDefaultParameterValues['*:Encoding'] = 'utf8'
} catch {
    # Если не удалось установить UTF-8, продолжаем работу
}

$separator = "=" * 80

Write-Host $separator -ForegroundColor Cyan
Write-Host "Пересборка и перезапуск Docker образа" -ForegroundColor Yellow
Write-Host $separator -ForegroundColor Cyan
Write-Host ""

# ШАГ 1: Остановка и удаление существующего контейнера
Write-Host "1. Остановка и удаление существующего контейнера..." -ForegroundColor Yellow
try {
    docker-compose down 2>&1 | Out-Null
    Write-Host "   [OK] Контейнер остановлен и удален" -ForegroundColor Green
} catch {
    Write-Host "   [WARNING] Контейнер не найден или уже остановлен" -ForegroundColor Yellow
}

Write-Host ""

# ШАГ 2: Удаление старого образа (опционально, для полной очистки)
Write-Host "2. Удаление старого образа..." -ForegroundColor Yellow
$removeOld = Read-Host "   Удалить старый образ перед пересборкой? (y/n)"
if ($removeOld -eq 'y' -or $removeOld -eq 'Y') {
    try {
        $imageName = docker-compose config --images 2>&1 | Select-String -Pattern "abricol" | ForEach-Object { $_.Line.Trim() }
        if ($imageName) {
            docker rmi $imageName -f 2>&1 | Out-Null
            Write-Host "   [OK] Старый образ удален" -ForegroundColor Green
        } else {
            Write-Host "   [OK] Старый образ не найден" -ForegroundColor Gray
        }
    } catch {
        Write-Host "   [WARNING] Не удалось удалить старый образ: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "   Старый образ сохранен" -ForegroundColor Gray
}

Write-Host ""

# ШАГ 3: Пересборка образа без кэша
Write-Host "3. Пересборка образа без кэша..." -ForegroundColor Yellow
Write-Host "   Это может занять несколько минут..." -ForegroundColor Gray
try {
    docker-compose build --no-cache
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   [OK] Образ успешно пересобран" -ForegroundColor Green
    } else {
        Write-Host "   [ERROR] Ошибка при пересборке образа" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "   [ERROR] Ошибка при пересборке образа: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ШАГ 4: Запуск нового контейнера
Write-Host "4. Запуск нового контейнера..." -ForegroundColor Yellow
try {
    docker-compose up -d
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   [OK] Контейнер успешно запущен" -ForegroundColor Green
    } else {
        Write-Host "   [ERROR] Ошибка при запуске контейнера" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "   [ERROR] Ошибка при запуске контейнера: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ШАГ 5: Проверка статуса
Write-Host "5. Проверка статуса контейнера..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
try {
    $status = docker-compose ps
    Write-Host $status
    Write-Host "   [OK] Контейнер работает" -ForegroundColor Green
} catch {
    Write-Host "   [WARNING] Не удалось проверить статус: $_" -ForegroundColor Yellow
}

Write-Host ""
Write-Host $separator -ForegroundColor Cyan
Write-Host "Пересборка завершена!" -ForegroundColor Green
Write-Host $separator -ForegroundColor Cyan
Write-Host ""
Write-Host 'Для просмотра логов используйте:' -ForegroundColor Yellow
Write-Host '  docker-compose logs -f' -ForegroundColor Cyan
Write-Host ""

