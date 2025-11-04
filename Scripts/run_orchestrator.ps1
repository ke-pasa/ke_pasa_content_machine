#!/usr/bin/env pwsh
# Ensure working directory
Set-Location 'C:\spain-que-pasa'

# Consistent UTF-8 logging for Out-File by default
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# Environment (production-friendly)
$env:PYTHONIOENCODING = 'utf-8'
$env:USE_OPENAI_BATCH = '1'
$env:FIREBASE_LOG_DISABLED = '1'
$env:BYPASS_DB_CACHE = '0'
# Tighter batch thresholds so батчи улетают чаще
$env:MIN_BATCH_SIZE = '6'
$env:BATCH_MAX_WAIT_SEC = '60'
$env:ORCHESTRATOR_POLL_INTERVAL_SEC = '180'  # каждые 3 минуты
$env:RSS_POLL_INTERVAL_SEC = '1800'
# Limit items per RSS feed to avoid long blocking loops
$env:RSS_MAX_ITEMS_PER_FEED = '300'

# Paths
$python = 'C:/spain-que-pasa/.venv/Scripts/python.exe'
$log = 'C:/spain-que-pasa/orchestrator.log'

# Endless supervisor loop
while ($true) {
  try {
    # Stop any stale orchestrator processes
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'batch_orchestrator.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force } | Out-Null
  } catch {}

  # Clear Firestore lock
  try {
  & $python -u -c "from workers.tools.firebase_client import get_firebase_client; db=get_firebase_client().db; db.collection('locks').document('orchestrator').delete()" | Out-Null
  } catch {}

  # Start orchestrator (append logs with UTF-8)
  try {
    & $python -u 'batch_orchestrator.py' 2>&1 | Out-File -FilePath $log -Encoding utf8 -Append
  } catch {}

  # Backoff before restart if it exited
  Start-Sleep -Seconds 10
}
