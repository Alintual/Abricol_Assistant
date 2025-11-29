# Устанавливаем кодировку UTF-8 ПЕРЕД всем остальным
chcp 65001 | Out-Null
[System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[System.Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$PSDefaultParameterValues['*:Encoding'] = 'utf8'

# Скрипт для полной остановки Docker
# Использование: .\stop_docker.ps1

# Переопределяем Write-Host для корректного вывода русского текста
function Write-Host {
    param(
        [Parameter(ValueFromPipeline)]
        [object]$Object,
        [switch]$NoNewline,
        [object]$Separator,
        [ConsoleColor]$ForegroundColor = [ConsoleColor]::White,
        [ConsoleColor]$BackgroundColor
    )
    
    $text = if ($Object) { $Object.ToString() } else { "" }
    
    if ($ForegroundColor) {
        $originalFg = [Console]::ForegroundColor
        [Console]::ForegroundColor = $ForegroundColor
    }
    
    if ($BackgroundColor) {
        $originalBg = [Console]::BackgroundColor
        [Console]::BackgroundColor = $BackgroundColor
    }
    
    if ($NoNewline) {
        [Console]::Write($text)
    } else {
        [Console]::WriteLine($text)
    }
    
    if ($ForegroundColor) {
        [Console]::ForegroundColor = $originalFg
    }
    if ($BackgroundColor) {
        [Console]::BackgroundColor = $originalBg
    }
}

$separator = "=" * 80

Write-Host $separator -ForegroundColor Cyan
Write-Host "Остановка Docker" -ForegroundColor Yellow
Write-Host $separator -ForegroundColor Cyan
Write-Host ""

# ШАГ 1: Остановить все работающие контейнеры
Write-Host "1. Остановка всех работающих контейнеров..." -ForegroundColor Yellow
try {
    $runningContainers = docker ps -q
    if ($runningContainers) {
        docker stop $runningContainers 2>&1 | Out-Null
        Write-Host "   [OK] Контейнеры остановлены" -ForegroundColor Green
    } else {
        Write-Host "   [OK] Нет работающих контейнеров" -ForegroundColor Gray
    }
} catch {
    Write-Host "   [ERROR] Ошибка при остановке контейнеров: $_" -ForegroundColor Red
}

Write-Host ""

# ШАГ 2: Остановить контейнер бота через docker-compose (если есть)
Write-Host "2. Остановка контейнера бота (docker-compose)..." -ForegroundColor Yellow
if (Test-Path "docker-compose.yml") {
    try {
        docker-compose down 2>&1 | Out-Null
        Write-Host "   [OK] Контейнер бота остановлен" -ForegroundColor Green
    } catch {
        Write-Host "   [ERROR] Ошибка при остановке через docker-compose: $_" -ForegroundColor Red
    }
} else {
    Write-Host "   [OK] Файл docker-compose.yml не найден, пропущено" -ForegroundColor Gray
}

Write-Host ""

# ШАГ 3: Закрыть Docker Desktop
Write-Host "3. Закрытие Docker Desktop..." -ForegroundColor Yellow
try {
    $dockerProcesses = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if ($dockerProcesses) {
        Stop-Process -Name "Docker Desktop" -Force -ErrorAction SilentlyContinue
        Write-Host "   [OK] Docker Desktop закрыт" -ForegroundColor Green
    } else {
        Write-Host "   [OK] Docker Desktop уже закрыт" -ForegroundColor Gray
    }
    
    # Также закрываем связанные процессы
    Stop-Process -Name "com.docker.backend" -Force -ErrorAction SilentlyContinue
    Stop-Process -Name "com.docker.proxy" -Force -ErrorAction SilentlyContinue
} catch {
    Write-Host "   [ERROR] Ошибка при закрытии Docker Desktop: $_" -ForegroundColor Red
}

Write-Host ""

# Проверка, что Docker закрыт
Write-Host "Проверка статуса Docker..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
try {
    docker ps 2>&1 | Out-Null
    Write-Host "   [WARNING] Docker все еще работает" -ForegroundColor Yellow
} catch {
    Write-Host "   [OK] Docker успешно закрыт" -ForegroundColor Green
}

Write-Host ""
Write-Host $separator -ForegroundColor Cyan
Write-Host "Остановка Docker завершена!" -ForegroundColor Green
Write-Host $separator -ForegroundColor Cyan

