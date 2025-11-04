# Скрипт автоматического запуска системы RSS-бота
# PowerShell script для Windows

# Установка рабочей директории
Set-Location 'c:\Development\ke-pasa'

# Настройка кодировки
$env:PYTHONIOENCODING = 'utf-8'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# Настройка переменных окружения для тестирования
$env:USE_OPENAI_BATCH = '1'
$env:BYPASS_DB_CACHE = '1'
$env:MIN_BATCH_SIZE = '3'
$env:BATCH_MAX_WAIT_SEC = '30'
$env:RSS_MAX_ITEMS_PER_FEED = '5'
$env:ORCHESTRATOR_POLL_INTERVAL_SEC = '30'

Write-Host "🚀 Запуск системы RSS-бота для мигрантов в Испании" -ForegroundColor Green

# Путь к Python
$python = 'c:/Development/ke-pasa/.venv/Scripts/python.exe'

# Проверяем наличие Python
if (-not (Test-Path $python)) {
    Write-Host "❌ Python не найден по пути: $python" -ForegroundColor Red
    Write-Host "Используем системный python..." -ForegroundColor Yellow
    $python = 'python'
}

# Очищаем блокировки оркестратора
Write-Host "🧹 Очищаем блокировки..." -ForegroundColor Yellow
try {
    & $python -u -c "from firebase_client import get_firebase_client; db=get_firebase_client().db; db.collection('locks').document('orchestrator').delete()" 2>$null
} catch {
    Write-Host "⚠️ Не удалось очистить блокировки" -ForegroundColor Yellow
}

# Настройка свежей системы
Write-Host "⚙️ Настройка системы..." -ForegroundColor Yellow
try {
    & $python setup_fresh_system.py
    Write-Host "✅ Система настроена" -ForegroundColor Green
} catch {
    Write-Host "❌ Ошибка настройки системы: $_" -ForegroundColor Red
    exit 1
}

# Запуск оркестратора в фоне
Write-Host "🚀 Запуск оркестратора..." -ForegroundColor Yellow
$orchestratorJob = Start-Job -ScriptBlock {
    param($pythonPath, $workDir)
    Set-Location $workDir
    & $pythonPath simple_orchestrator.py
} -ArgumentList $python, (Get-Location).Path

Write-Host "✅ Оркестратор запущен (Job ID: $($orchestratorJob.Id))" -ForegroundColor Green

# Мониторинг системы
Write-Host "`n📊 Мониторинг системы (нажмите Ctrl+C для остановки)..." -ForegroundColor Cyan

$monitoringCount = 0
try {
    while ($true) {
        Start-Sleep -Seconds 30
        $monitoringCount++
        
        Write-Host "`n--- Проверка #$monitoringCount $(Get-Date -Format 'HH:mm:ss') ---" -ForegroundColor Cyan
        
        # Проверяем состояние оркестратора
        $jobState = Get-Job -Id $orchestratorJob.Id | Select-Object -ExpandProperty State
        Write-Host "Оркестратор: $jobState" -ForegroundColor $(if ($jobState -eq 'Running') { 'Green' } else { 'Red' })
        
        # Показываем логи оркестратора
        $jobOutput = Receive-Job -Id $orchestratorJob.Id -Keep
        if ($jobOutput) {
            $recentOutput = ($jobOutput | Select-Object -Last 3) -join "`n"
            Write-Host "Последние логи: $recentOutput" -ForegroundColor Gray
        }
        
        # Проверяем состояние системы
        try {
            & $python debug_system.py
        } catch {
            Write-Host "⚠️ Ошибка проверки состояния: $_" -ForegroundColor Yellow
        }
        
        # Перезапускаем оркестратор если он упал
        if ($jobState -ne 'Running') {
            Write-Host "🔄 Перезапуск оркестратора..." -ForegroundColor Yellow
            Remove-Job -Id $orchestratorJob.Id -Force
            
            $orchestratorJob = Start-Job -ScriptBlock {
                param($pythonPath, $workDir)
                Set-Location $workDir
                & $pythonPath simple_orchestrator.py
            } -ArgumentList $python, (Get-Location).Path
            
            Write-Host "✅ Оркестратор перезапущен (Job ID: $($orchestratorJob.Id))" -ForegroundColor Green
        }
    }
} catch {
    Write-Host "`n🛑 Остановка системы..." -ForegroundColor Red
} finally {
    # Останавливаем оркестратор
    if ($orchestratorJob) {
        Stop-Job -Id $orchestratorJob.Id -ErrorAction SilentlyContinue
        Remove-Job -Id $orchestratorJob.Id -Force -ErrorAction SilentlyContinue
        Write-Host "✅ Оркестратор остановлен" -ForegroundColor Green
    }
    
    Write-Host "👋 Система остановлена" -ForegroundColor Yellow
}

