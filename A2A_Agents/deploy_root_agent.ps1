
# Deploy Root Agent to Vertex AI Agent Engine
# Usage: .\deploy_root_agent.ps1
# Prerequisites:
#   - gcloud authenticated with sufficient permissions
#   - adk CLI installed (pip install google-adk)
#   - remote-a2a-agent Cloud Run service already deployed

param(
    [string]$project = "kpmgpoc",
    [string]$region = "us-central1",
    [string]$service = "remote-a2a-agent",
    [string]$displayName = "A2A Root Agent POC"
)

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Deploying Root Agent → Agent Engine" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Project     : $project"
Write-Host "Region      : $region"
Write-Host "Remote Agent: $service"
Write-Host "Display Name: $displayName"
Write-Host ""

# ─── Step 1: Grant Cloud Run Invoker ───────────────────────────────────────
Write-Host "[1/2] Granting Cloud Run Invoker to Compute Service Account..." -ForegroundColor Yellow

$projectNumber = gcloud projects describe $project --format="value(projectNumber)"
if (-not $projectNumber) {
    Write-Error "❌ Could not retrieve project number for '$project'. Check your gcloud auth."
    exit 1
}

$computeSA = "${projectNumber}-compute@developer.gserviceaccount.com"
Write-Host "      SA: $computeSA"

gcloud run services add-iam-policy-binding $service `
    --member="serviceAccount:$computeSA" `
    --role="roles/run.invoker" `
    --region $region `
    --project $project 2>&1 | Out-Null

if ($LASTEXITCODE -eq 0) {
    Write-Host "      ✅ Cloud Run Invoker granted." -ForegroundColor Green
}
else {
    Write-Warning "      ⚠️  IAM binding failed. Agent may not be able to call the remote service."
    Write-Warning "         Ensure you have 'Cloud Run Admin' or 'Project IAM Admin' role."
}

# Also ensure compute SA can access the API key secret
Write-Host "      Granting Secret Accessor for 'remote-agent-api-key'..."
gcloud secrets add-iam-policy-binding remote-agent-api-key `
    --member="serviceAccount:$computeSA" `
    --role="roles/secretmanager.secretAccessor" `
    --project $project 2>&1 | Out-Null

if ($LASTEXITCODE -eq 0) {
    Write-Host "      ✅ Secret Accessor granted." -ForegroundColor Green
}
else {
    Write-Warning "      ⚠️  Secret IAM binding failed. Agent will fall back to .env key."
}

# ─── Step 2: Deploy to Agent Engine ────────────────────────────────────────
Write-Host ""
Write-Host "[2/2] Deploying to Agent Engine (may take 3-5 mins)..." -ForegroundColor Yellow

# Set UTF-8 output so the ADK's emoji-containing messages don't crash on Windows cp1252
$env:PYTHONIOENCODING = "utf-8"

$deployOutput = adk deploy agent_engine `
    --project $project `
    --region $region `
    --display_name $displayName `
    a2a_poc 2>&1

$env:PYTHONIOENCODING = $null  # restore

# adk deploy agent_engine exits 0 even on failure; parse output for actual status
$deployFailed = $deployOutput | Select-String -Pattern "Deploy failed" -Quiet
if ($deployFailed) {
    Write-Host ""
    $deployOutput | Write-Host
    Write-Error "❌ Agent Engine deployment failed. See error above."
    exit 1
}
Write-Host ""
Write-Host "✅ Root Agent successfully deployed to Agent Engine!" -ForegroundColor Green
Write-Host "👉 View at: https://console.cloud.google.com/vertex-ai/agents?project=$project" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test it: Send 'Roll a die' in the Agent Engine console test UI." -ForegroundColor Gray
