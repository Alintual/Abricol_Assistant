# Устанавливаем кодировку UTF-8 ПЕРЕД всем остальным
chcp 65001 | Out-Null
[System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[System.Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$PSDefaultParameterValues['*:Encoding'] = 'utf8'

# Скрипт для очистки диска Docker
# Использование: .\cleanup_docker_disk.ps1

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

$separator = '=' * 80

Write-Host $separator -ForegroundColor Cyan
Write-Host 'Очистка диска Docker' -ForegroundColor Yellow
Write-Host $separator -ForegroundColor Cyan
Write-Host ''

# Показываем статистику ДО очистки
Write-Host 'Статистика ДО очистки:' -ForegroundColor Yellow
docker system df
Write-Host ''

# ШАГ 1: Безопасная очистка неиспользуемых ресурсов
Write-Host '1. Безопасная очистка неиспользуемых ресурсов...' -ForegroundColor Yellow
Write-Host '   (остановленные контейнеры, dangling образы, неиспользуемые тома/сети)' -ForegroundColor Gray

try {
    docker system prune -f 2>&1 | Out-Null
    Write-Host '   [OK] Безопасная очистка выполнена' -ForegroundColor Green
} catch {
    Write-Host "   [ERROR] Ошибка при безопасной очистке: $_" -ForegroundColor Red
}

Write-Host ''

# ШАГ 2: Очистка кэша сборки
Write-Host '2. Очистка кэша сборки...' -ForegroundColor Yellow
Write-Host '   (освободит больше всего места, но замедлит следующую сборку)' -ForegroundColor Gray

$cleanCache = Read-Host '   Удалить кэш сборки? (y/n)'
if ($cleanCache -eq 'y' -or $cleanCache -eq 'Y') {
    try {
        docker builder prune -af 2>&1 | Out-Null
        Write-Host '   [OK] Кэш сборки удален' -ForegroundColor Green
    } catch {
        Write-Host "   [ERROR] Ошибка при удалении кэша: $_" -ForegroundColor Red
    }
} else {
    Write-Host '   Кэш сборки сохранен' -ForegroundColor Gray
}

Write-Host ''

# ШАГ 3: Агрессивная очистка (опционально)
Write-Host '3. Агрессивная очистка...' -ForegroundColor Yellow
Write-Host '   (удалит ВСЕ неиспользуемые образы, включая базовые)' -ForegroundColor Gray
Write-Host '   [ВНИМАНИЕ] При следующей сборке Docker снова скачает базовые образы' -ForegroundColor Red

$aggressiveClean = Read-Host '   Выполнить агрессивную очистку? (y/n)'
if ($aggressiveClean -eq 'y' -or $aggressiveClean -eq 'Y') {
    try {
        docker system prune -a -f 2>&1 | Out-Null
        Write-Host '   [OK] Агрессивная очистка выполнена' -ForegroundColor Green
    } catch {
        Write-Host "   [ERROR] Ошибка при агрессивной очистке: $_" -ForegroundColor Red
    }
} else {
    Write-Host '   Агрессивная очистка пропущена' -ForegroundColor Gray
}

Write-Host ''

# Показываем статистику ПОСЛЕ очистки
Write-Host 'Статистика ПОСЛЕ очистки:' -ForegroundColor Yellow
docker system df
Write-Host ''

Write-Host $separator -ForegroundColor Cyan
Write-Host 'Очистка завершена!' -ForegroundColor Green
Write-Host $separator -ForegroundColor Cyan