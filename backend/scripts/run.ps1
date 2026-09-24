# VisionField Copilot backend — Windows launcher.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run.ps1
#
# Creates a virtual environment on first run, installs the base dependencies
# and starts the service on http://127.0.0.1:8756.
#
# Snapdragon note (§5): Qualcomm's current README says X Elite / X2 Elite
# Windows users should use AMD64/x86-64 Python for qai_hub_models. Check the
# current requirement before setting this machine up.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}

Write-Host "Starting VisionField Copilot backend on http://127.0.0.1:8756" -ForegroundColor Green
& .\.venv\Scripts\python.exe -m app.main
