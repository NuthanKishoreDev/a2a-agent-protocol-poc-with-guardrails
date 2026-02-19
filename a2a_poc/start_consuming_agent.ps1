# Start Consuming Agent via ADK Web (Terminal 2)
# Activates venv and runs adk web for the root a2a_poc agent

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& "$PSScriptRoot\venv\Scripts\Activate.ps1"

Write-Host "Starting ADK Web UI on http://localhost:8000 ..." -ForegroundColor Green
Write-Host "Make sure the Remote Agent is running on port 8001 first!" -ForegroundColor Yellow

Set-Location "$PSScriptRoot\.."
adk web a2a_poc
