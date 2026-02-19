
# Fix Cloud Run Permissions
# Usage: .\fix_permissions.ps1

$project = "kpmgpoc"
$service = "remote-a2a-agent"
$region = "us-central1"

Write-Host "🔓 Granting public access to $service..."

# Try simpler command first
gcloud run services add-iam-policy-binding $service `
    --member="allUsers" `
    --role="roles/run.invoker" `
    --region=$region `
    --project=$project

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Service is now public (protected by API Key app-level)." -ForegroundColor Green
}
else {
    Write-Warning "⚠️  Failed to grant permissions. Checking why..."
    # Check permissions
    gcloud projects get-iam-policy $project --flatten="bindings[].members" --format="table(bindings.role)" --filter="bindings.members:user:$(gcloud config get-value account 2>$null)"
}
