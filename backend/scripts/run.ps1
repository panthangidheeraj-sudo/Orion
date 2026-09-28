# VisionField Copilot backend — Windows launcher.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run.ps1
#
# Creates a virtual environment on first run, installs the base dependencies
# and starts the service on http://127.0.0.1:8756.
#
# Snapdragon: the reasoning model (Qwen3-VL-4B-Instruct via GenieX + QAIRT)
# needs ARM64 Python 3.10+ and requirements-snapdragon.txt — see
# docs\SNAPDRAGON_SETUP.md.

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
