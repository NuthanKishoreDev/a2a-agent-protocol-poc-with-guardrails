# Start Remote A2A Agent Server (Terminal 1)
# Activates venv and runs the remote Hello World agent on port 8001

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& "$PSScriptRoot\venv\Scripts\Activate.ps1"

Write-Host "Starting Remote A2A Agent on http://localhost:8081 ..." -ForegroundColor Green
uvicorn remote_agent.agent:a2a_app --host localhost --port 8081
