
# Deploy Remote Agent to Cloud Run (with Secret Manager)
# Usage: .\deploy_remote_agent.ps1 <GCP_PROJECT_ID> <SERVICE_NAME> <REGION>

param(
    [string]$project = "kpmgpoc",
    [string]$service = "remote-a2a-agent",
    [string]$region = "us-central1"
)

$ErrorActionPreference = "Continue"

Write-Host "[*] Deploying Remote Agent to Cloud Run (Secured) ..." -ForegroundColor Cyan
Write-Host "Project: $project | Service: $service | Region: $region"

# 1. Check prerequisites
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "gcloud CLI is not installed or not in PATH."
    exit 1
}

# 2. Build and Submit Container Image to ARTIFACT REGISTRY
$repoName = "a2a-containers"
$arLocation = $region
$image = "$arLocation-docker.pkg.dev/$project/$repoName/$service"

Write-Host "[*] Ensuring Artifact Registry repo '$repoName' exists..."
gcloud artifacts repositories describe $repoName --location=$arLocation --project=$project >$null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "    Creating Artifact Registry repository..."
    gcloud artifacts repositories create $repoName --repository-format=docker --location=$arLocation --description="Containers for A2A Agents" --project=$project
}

Write-Host "[*] Building container image: $image ..."
# We expect Dockerfile in current directory
if (-not (Test-Path "Dockerfile")) {
    if (Test-Path "remote_agent.Dockerfile") {
        Move-Item "remote_agent.Dockerfile" "Dockerfile" -Force
    }
    else {
        Write-Error "Dockerfile not found."
        exit 1
    }
}

gcloud builds submit --tag $image . --project $project
if ($LASTEXITCODE -ne 0) { 
    Write-Error "[-] Build failed. Please check gcloud builds log above."
    exit 1 
}

# 3. Handle Secrets
Write-Host "[*] Configuring Secret Manager..."

# Enable Secret Manager API
gcloud services enable secretmanager.googleapis.com --project $project 2>&1 | Out-Null

# Get API Key from .env
$envFile = "remote_agent\.env"
$apiKey = "dev-key"
if (Test-Path $envFile) {
    $content = Get-Content $envFile
    foreach ($line in $content) {
        if ($line -match "^REMOTE_AGENT_API_KEY=(.*)") {
            $apiKey = $matches[1]
            break
        }
    }
}

$secretName = "remote-agent-api-key"
$secretFile = "secret.tmp"

# Check/Create Secret
$secretExists = gcloud secrets list --filter="name:$secretName" --project $project --format="value(name)"
if (-not $secretExists) {
    Write-Host "    Creating secret '$secretName'..."
    gcloud secrets create $secretName --replication-policy="automatic" --project="$project"
}

# Add Secret Version
Write-Host "    Adding new secret version..."
$secretPath = Join-Path $PWD $secretFile
[System.IO.File]::WriteAllText($secretPath, $apiKey)
try {
    gcloud secrets versions add $secretName --data-file="$secretPath" --project="$project"
}
finally {
    Remove-Item $secretPath -ErrorAction SilentlyContinue
}

# Grant Identity Access (Best Effort)
$projectNumber = gcloud projects describe $project --format="value(projectNumber)"
$saEmail = "${projectNumber}-compute@developer.gserviceaccount.com"
Write-Host "    Granting 'Secret Accessor' to $saEmail..."
gcloud secrets add-iam-policy-binding $secretName `
    --member="serviceAccount:$saEmail" `
    --role="roles/secretmanager.secretAccessor" `
    --project="$project" 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Warning "[!] Failed to grant IAM permission. Ensure you have 'Secret Manager Admin' role."
}

# 4. Deploy to Cloud Run
Write-Host "[*] Deploying to Cloud Run..."

# Deploy and capture output to find URL (using --format to output URL to stdout, stderr to unrelated)
$deployOutput = gcloud run deploy $service `
    --image $image `
    --platform managed `
    --region $region `
    --allow-unauthenticated `
    --project $project `
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$project,GOOGLE_CLOUD_LOCATION=$region,GOOGLE_GENAI_USE_VERTEXAI=true" `
    --set-secrets "REMOTE_AGENT_API_KEY=${secretName}:latest" `
    --port 8080 `
    --format="value(status.url)" 2>&1

if ($LASTEXITCODE -eq 0) {
    # Extract URL (parse output for https URL)
    $url = $deployOutput | Select-String -Pattern "https://.*\.run\.app" -AllMatches | ForEach-Object { $_.Matches } | ForEach-Object { $_.Value } | Select-Object -First 1
    
    if (-not $url) {
        # Fallback query
        $url = gcloud run services describe $service --platform managed --region $region --format 'value(status.url)' --project $project
    }

    Write-Host "[+] Deployment successful! URL: $url" -ForegroundColor Green
    
    if ($url) {
        Write-Host "[*] Updating SERVICE_URL env var to $url..."
        gcloud run services update $service --project $project --region $region --set-env-vars "SERVICE_URL=$url" >$null 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[+] SERVICE_URL updated."
        }
        else {
            Write-Warning "[!] Failed to update SERVICE_URL."
        }
    }
}
else {
    Write-Error "[-] Deployment failed."
    Write-Host $deployOutput
}
