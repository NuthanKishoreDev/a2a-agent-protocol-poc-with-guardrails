# GCP Deployment & Long-Term Maintenance Plan
# A2A Agent Protocol POC

> **Project:** `kpmgpoc` | **Region:** `us-central1` | **Framework:** Google ADK

---

## Part 1 — GCP Deployment Plan

### Architecture on GCP

```
┌──────────────────────────────────────────────────────────────────┐
│                     PRODUCTION ARCHITECTURE                       │
│                                                                  │
│  ┌──────────────┐    ┌─────────────────────┐    ┌────────────┐  │
│  │  Cloud Run   │    │     Cloud Run        │    │ Vertex AI  │  │
│  │  (Root/UI)   │───▶│  (Remote Agent)      │───▶│ Gemini 2.0 │  │
│  │  Port 8000   │A2A │  Port 8081           │    │ Flash      │  │
│  └──────────────┘    └─────────────────────┘    └────────────┘  │
│         │                     │                                  │
│         ▼                     ▼                                  │
│  ┌──────────────┐    ┌─────────────────────┐                    │
│  │  Cloud IAP   │    │  Secret Manager      │                    │
│  │  (Auth)      │    │  (API Keys / Creds)  │                    │
│  └──────────────┘    └─────────────────────┘                    │
│                                                                  │
│  ┌──────────────┐    ┌─────────────────────┐                    │
│  │  Cloud       │    │  Artifact Registry   │                    │
│  │  Logging     │    │  (Docker Images)     │                    │
│  └──────────────┘    └─────────────────────┘                    │
└──────────────────────────────────────────────────────────────────┘
```

---

### GCP Resources Required

| Resource                       | Service              | Purpose                                       | Tier                    |
| ------------------------------ | -------------------- | --------------------------------------------- | ----------------------- |
| **Cloud Run** (remote-agent)   | Cloud Run            | Hosts `remote_agent` ASGI app                 | Fully managed           |
| **Cloud Run** (root-agent-ui)  | Cloud Run            | Hosts `adk web` UI                            | Fully managed           |
| **Artifact Registry**          | Artifact Registry    | Stores Docker images                          | Standard                |
| **Secret Manager**             | Secret Manager       | Stores API key, credentials                   | Standard                |
| **Cloud Logging**              | Cloud Operations     | Centralized logs from both agents             | Built-in with Cloud Run |
| **Cloud Monitoring**           | Cloud Operations     | Alerting, dashboards, uptime checks           | Built-in                |
| **Vertex AI**                  | Vertex AI            | Gemini 2.0 Flash model inference              | Pay-per-use             |
| **VPC Connector** *(optional)* | VPC                  | Private networking between Cloud Run services | If private needed       |
| **Cloud IAP** *(optional)*     | Identity-Aware Proxy | Restrict UI access to corp users              | If auth needed          |

---

### Step 1 — Prepare Docker Images

#### `remote_agent/Dockerfile`
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8081
CMD ["python", "-m", "uvicorn", "remote_agent.agent:a2a_app", \
     "--host", "0.0.0.0", "--port", "8081", "--log-level", "info"]
```

#### `Dockerfile` (root agent / ADK web UI)
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "-m", "google.adk.cli", "web", ".", "--host", "0.0.0.0", "--port", "8000"]
```

---

### Step 2 — Store Secrets in Secret Manager

```bash
# Store the remote agent API key
echo -n "your-production-api-key" | gcloud secrets create REMOTE_AGENT_API_KEY \
  --data-file=- --project=kpmgpoc

# Verify
gcloud secrets versions access latest --secret="REMOTE_AGENT_API_KEY" --project=kpmgpoc
```

---

### Step 3 — Build & Push Docker Images to Artifact Registry

```bash
# Create Artifact Registry repo
gcloud artifacts repositories create a2a-agents \
  --repository-format=docker \
  --location=us-central1 \
  --project=kpmgpoc

# Set Docker auth
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build and push remote agent
docker build -t us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/remote-agent:latest \
  -f remote_agent/Dockerfile .
docker push us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/remote-agent:latest

# Build and push root agent UI
docker build -t us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/root-agent-ui:latest .
docker push us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/root-agent-ui:latest
```

---

### Step 4 — Deploy Remote Agent to Cloud Run

```bash
gcloud run deploy remote-agent \
  --image=us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/remote-agent:latest \
  --region=us-central1 \
  --project=kpmgpoc \
  --port=8081 \
  --min-instances=1 \
  --max-instances=10 \
  --memory=1Gi \
  --cpu=1 \
  --concurrency=80 \
  --timeout=300 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=kpmgpoc,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=true" \
  --set-secrets="REMOTE_AGENT_API_KEY=REMOTE_AGENT_API_KEY:latest" \
  --service-account=a2a-remote-agent-sa@kpmgpoc.iam.gserviceaccount.com \
  --no-allow-unauthenticated   # requires valid Google identity or service account
```

Note the deployed URL, e.g. `https://remote-agent-xxxx-uc.a.run.app`

---

### Step 5 — Deploy Root Agent UI to Cloud Run

```bash
gcloud run deploy root-agent-ui \
  --image=us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/root-agent-ui:latest \
  --region=us-central1 \
  --project=kpmgpoc \
  --port=8000 \
  --min-instances=1 \
  --max-instances=5 \
  --memory=512Mi \
  --cpu=1 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=kpmgpoc,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=true,REMOTE_AGENT_URL=https://remote-agent-xxxx-uc.a.run.app" \
  --set-secrets="REMOTE_AGENT_API_KEY=REMOTE_AGENT_API_KEY:latest" \
  --service-account=a2a-root-agent-sa@kpmgpoc.iam.gserviceaccount.com \
  --allow-unauthenticated   # or use Cloud IAP for corp-restricted access
```

---

### Step 6 — Create Service Accounts & IAM

```bash
# Remote Agent SA
gcloud iam service-accounts create a2a-remote-agent-sa \
  --display-name="A2A Remote Agent" --project=kpmgpoc

# Root Agent SA
gcloud iam service-accounts create a2a-root-agent-sa \
  --display-name="A2A Root Agent" --project=kpmgpoc

# Grant Vertex AI access
gcloud projects add-iam-policy-binding kpmgpoc \
  --member="serviceAccount:a2a-remote-agent-sa@kpmgpoc.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Grant Secret Manager access
gcloud secrets add-iam-policy-binding REMOTE_AGENT_API_KEY \
  --member="serviceAccount:a2a-remote-agent-sa@kpmgpoc.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=kpmgpoc

# Allow root agent to call remote agent (Cloud Run invoker)
gcloud run services add-iam-policy-binding remote-agent \
  --member="serviceAccount:a2a-root-agent-sa@kpmgpoc.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --region=us-central1 --project=kpmgpoc
```

---

### Step 7 — Update `agent.py` for Cloud Run URL

After deployment, update the remote agent URL in `agent.py`:

```python
REMOTE_AGENT_URL = os.getenv(
    "REMOTE_AGENT_URL",
    "https://remote-agent-xxxx-uc.a.run.app/.well-known/agent.json"
)
root_agent = RemoteA2aAgent(
    name="a2a_root_agent",
    agent_card=REMOTE_AGENT_URL,
    httpx_client=_http_client,
)
```

---

### Step 8 — CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy A2A Agents to Cloud Run

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Auth to GCP
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Build & Push Remote Agent
        run: |
          docker build -t us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/remote-agent:$GITHUB_SHA \
            -f a2a_poc/remote_agent/Dockerfile a2a_poc/
          docker push us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/remote-agent:$GITHUB_SHA

      - name: Deploy Remote Agent
        run: |
          gcloud run deploy remote-agent \
            --image=us-central1-docker.pkg.dev/kpmgpoc/a2a-agents/remote-agent:$GITHUB_SHA \
            --region=us-central1 --project=kpmgpoc
```

---

## Part 2 — Long-Term Maintenance Strategy

### 1. Security Maintenance

| Task                           | Frequency     | How                                                 |
| ------------------------------ | ------------- | --------------------------------------------------- |
| Rotate `REMOTE_AGENT_API_KEY`  | Every 90 days | Update Secret Manager + redeploy                    |
| Audit IAM permissions          | Quarterly     | Use `gcloud iam` / Policy Analyzer                  |
| Scan Docker images for CVEs    | Every build   | Enable Artifact Registry vulnerability scanning     |
| Review guardrail blocklist     | Monthly       | Update `BLOCKED_PHRASES` in `remote_agent/agent.py` |
| Revoke unused service accounts | Quarterly     | IAM audit logs                                      |

### 2. Model & ADK Version Management

| Task                               | Frequency   | Action                                                               |
| ---------------------------------- | ----------- | -------------------------------------------------------------------- |
| Track ADK release notes            | Monthly     | [github.com/google/adk-python](https://github.com/google/adk-python) |
| Test ADK upgrades                  | Per release | Run full test suite in staging before prod                           |
| Evaluate new Gemini models         | Per release | Test `gemini-2.5-flash` etc. for better quality/cost                 |
| Pin versions in `requirements.txt` | Always      | `google-adk[a2a]==X.Y.Z` to avoid surprise breaks                    |

```
# requirements.txt — always pin versions in production
google-adk[a2a]==1.x.x
uvicorn[standard]==0.x.x
httpx==0.x.x
python-dotenv==1.x.x
```

### 3. Observability & Monitoring

```bash
# Cloud Run automatically sends logs to Cloud Logging
# Create an alert for 5xx errors over 1% in 5 min
gcloud monitoring policies create \
  --notification-channels=YOUR_CHANNEL \
  --display-name="A2A Remote Agent Error Rate" \
  --condition-threshold-filter='resource.type="cloud_run_revision" AND metric.type="run.googleapis.com/request_count" AND metric.labels.response_code_class="5xx"'
```

**Key metrics to monitor:**

| Metric                    | Alert threshold | Service                         |
| ------------------------- | --------------- | ------------------------------- |
| Request error rate        | > 2% in 5 min   | Cloud Monitoring                |
| P99 latency               | > 10 seconds    | Cloud Run                       |
| Guardrail block rate      | Spike > 20%     | Custom metric via Cloud Logging |
| Vertex AI quota usage     | > 80%           | Vertex AI Quota dashboard       |
| Container cold-start time | > 5 seconds     | Cloud Run metrics               |

### 4. Cost Management

| Resource               | Cost Control Strategy                                                   |
| ---------------------- | ----------------------------------------------------------------------- |
| **Cloud Run**          | Set `--max-instances=10`, use `--min-instances=0` for dev, `1` for prod |
| **Vertex AI (Gemini)** | Monitor token usage; set billing alerts at $X/day in Cloud Billing      |
| **Artifact Registry**  | Add lifecycle policy to delete images older than 30 days                |
| **Cloud Logging**      | Set log retention to 30 days; export critical logs to GCS for long-term |

```bash
# Billing alert — alert at $50/day
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --display-name="A2A POC Daily Budget" \
  --budget-amount=50USD \
  --threshold-rule=percent=80 \
  --threshold-rule=percent=100
```

### 5. Scaling Strategy

| Load              | Configuration                                      |
| ----------------- | -------------------------------------------------- |
| **Dev/POC**       | `min=0, max=2` — cold starts acceptable            |
| **Internal prod** | `min=1, max=10` — no cold starts, moderate scale   |
| **High traffic**  | `min=2, max=50` + VPC connector + Cloud Armor DDoS |

### 6. Adding New Agents (Long-Term Growth)

As the A2A ecosystem grows, new specialist agents can be added:

```
New Specialist Agent (e.g. HR Agent, Finance Agent)
    → Deploy to Cloud Run
    → Register its Agent Card URL in a central Agent Registry
    → Root Agent discovers and calls it via A2A
```

**Agent Registry pattern** — store discovered agents in Firestore:
```python
# Future: dynamic agent discovery
agents = firestore.collection("a2a_agents").stream()
for agent_doc in agents:
    card_url = agent_doc.to_dict()["agent_card_url"]
    # dynamically add as sub-agent
```

### 7. Disaster Recovery

| Scenario           | Recovery Action                                                  | RTO      |
| ------------------ | ---------------------------------------------------------------- | -------- |
| Remote agent crash | Cloud Run auto-restarts; `min-instances=1` prevents cold starts  | < 30s    |
| Bad deployment     | `gcloud run services update-traffic --to-revisions=PREV_REV=100` | < 2 min  |
| Secret compromised | Rotate in Secret Manager + trigger new deployment                | < 5 min  |
| Region outage      | Deploy to secondary region (`us-east1`) + Cloud Load Balancer    | < 15 min |

```bash
# Rollback to previous revision instantly
gcloud run services update-traffic remote-agent \
  --to-revisions=PREV_REVISION_ID=100 \
  --region=us-central1 --project=kpmgpoc
```

### 8. Environment Strategy

| Environment | Branch      | Cloud Run service suffix | Min instances |
| ----------- | ----------- | ------------------------ | ------------- |
| Development | `feature/*` | `-dev`                   | 0             |
| Staging     | `develop`   | `-staging`               | 1             |
| Production  | `main`      | (none)                   | 2             |

---

## Deployment Checklist

```
PRE-DEPLOYMENT
[ ] Docker images built and tested locally
[ ] Secrets stored in Secret Manager
[ ] Service accounts created with least-privilege IAM
[ ] Staging deployment tested end-to-end
[ ] Guardrail blocklist reviewed
[ ] requirements.txt versions pinned

DEPLOYMENT
[ ] Remote agent deployed to Cloud Run
[ ] Root agent deployed to Cloud Run
[ ] Agent Card URL verified (curl /.well-known/agent.json)
[ ] API key auth verified (curl without key → 401)
[ ] End-to-end A2A call verified

POST-DEPLOYMENT
[ ] Cloud Monitoring alerts configured
[ ] Billing budget alert set
[ ] Rollback revision noted
[ ] Documentation updated
```
