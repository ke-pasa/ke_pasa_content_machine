# Quick activation script for ke-pasa content machine
# Loads .env variables and activates venv_new

$ProjectRoot = $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"
$VenvActivate = Join-Path $ProjectRoot "venv_new\Scripts\Activate.ps1"

Write-Host "`n🚀 Activating ke-pasa environment..." -ForegroundColor Cyan

# Load .env file
if (Test-Path $EnvFile) {
    Write-Host "`n📝 Loading environment variables from .env..." -ForegroundColor Green
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        # Skip empty lines and comments
        if ($line -and -not $line.StartsWith("#")) {
            # Parse KEY=VALUE
            if ($line -match "^([^=]+)=(.*)$") {
                $key = $matches[1].Trim()
                $value = $matches[2].Trim()
                # Remove quotes if present
                $value = $value -replace '^"(.*)"$', '$1'
                $value = $value -replace "^'(.*)'$", '$1'
                Set-Item -Path "env:$key" -Value $value
                Write-Host "  ✓ Loaded: $key" -ForegroundColor Cyan
            }
        }
    }
    Write-Host "✅ Environment variables loaded!`n" -ForegroundColor Green
} else {
    Write-Warning "⚠️  .env file not found at: $EnvFile`n"
}

# Activate venv_new
if (Test-Path $VenvActivate) {
    Write-Host "🐍 Activating Python virtual environment (venv_new)..." -ForegroundColor Green
    & $VenvActivate
    Write-Host "✅ Virtual environment activated!`n" -ForegroundColor Green
} else {
    Write-Error "❌ Virtual environment not found at: $VenvActivate"
    Write-Host "Run 'python -m venv venv_new' to create it.`n" -ForegroundColor Yellow
}
