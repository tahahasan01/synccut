# Starts the SyncCut API (port 8000) and web app (port 3000) in two windows.
$root = Split-Path -Parent $PSScriptRoot

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\services\api'; .\.venv\Scripts\python -m uvicorn synccut.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\apps\web'; npm run dev"

Write-Host "API: http://localhost:8000/api/health"
Write-Host "App: http://localhost:3000"
