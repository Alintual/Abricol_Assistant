# Скрипт для очистки кэша Python и остановки всех запущенных копий бота
# Использование: .\cleanup_bot.ps1

# Подавляем информационные сообщения PowerShell
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'SilentlyContinue'

Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host "Очистка кэша Python и остановка всех копий бота" -ForegroundColor Yellow
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host ""

# ШАГ 1: Очистка кэша Python
Write-Host "1. Очистка кэша Python..." -ForegroundColor Yellow

$cacheCount = 0

# Удаляем все __pycache__ директории
$pycacheDirs = Get-ChildItem -Path . -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue
foreach ($dir in $pycacheDirs) {
    try {
        $null = Remove-Item -Path $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue 2>&1
        $cacheCount++
    } catch {
        # Игнорируем ошибки
    }
}

# Удаляем все .pyc файлы
$pycFiles = Get-ChildItem -Path . -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue
foreach ($file in $pycFiles) {
    try {
        $null = Remove-Item -Path $file.FullName -Force -ErrorAction SilentlyContinue 2>&1
        $cacheCount++
    } catch {
        # Игнорируем ошибки
    }
}

if ($cacheCount -gt 0) {
    Write-Host "   Кэш очищен: удалено $cacheCount элементов" -ForegroundColor Green
} else {
    Write-Host "   Кэш не найден (уже очищен)" -ForegroundColor Gray
}

Write-Host ""

# ШАГ 2: Остановка всех запущенных копий бота
Write-Host "2. Остановка всех запущенных копий бота..." -ForegroundColor Yellow

$projectPath = (Get-Location).Path
$killedCount = 0

# Находим все процессы Python, связанные с ботом
$pythonProcesses = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $process = $_
    $isBotProcess = $false
    
    # Проверяем командную строку процесса
    try {
        $cmdline = (Get-WmiObject Win32_Process -Filter "ProcessId = $($process.Id)").CommandLine
        if ($cmdline) {
            # Проверяем, что это процесс бота
            if ($cmdline -like "*src.bot*" -or 
                $cmdline -like "*src\bot*" -or 
                $cmdline -like "*src/bot*" -or
                $cmdline -like "*$projectPath*") {
                $isBotProcess = $true
            }
        }
    } catch {
        # Если не удалось получить командную строку, проверяем по пути
        if ($process.Path -like "*$projectPath*") {
            $isBotProcess = $true
        }
    }
    
    return $isBotProcess
}

# Останавливаем найденные процессы
foreach ($proc in $pythonProcesses) {
    try {
        Write-Host "   Остановка процесса PID: $($proc.Id)" -ForegroundColor Gray
        $null = Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue 2>&1
        $killedCount++
    } catch {
        Write-Host "   Не удалось остановить процесс PID: $($proc.Id)" -ForegroundColor Red
    }
}

if ($killedCount -gt 0) {
    Write-Host "   Остановлено процессов бота: $killedCount" -ForegroundColor Green
} else {
    Write-Host "   Запущенные копии бота не найдены" -ForegroundColor Gray
}

Write-Host ""
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host "Очистка завершена!" -ForegroundColor Green
Write-Host ("=" * 80) -ForegroundColor Cyan

