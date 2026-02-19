# A2A Agent Deployment — Troubleshooting Reference

All issues encountered during the A2A POC deployment (Remote Agent → Cloud Run, Root Agent → Agent Engine).

---

## 1. Vertex AI Environment Variable Typo on Cloud Run

**Symptom:** Remote Agent started but crashed on every request with `Missing key inputs` (Vertex AI auth failure).

**Root Cause:** `deploy_remote_agent.ps1` had a case typo in the `--set-env-vars` flag:
```
GOOGLE_Cloud_PROJECT   ❌  (Python env vars are case-sensitive)
GOOGLE_CLOUD_PROJECT   ✅
```

**Fix:** Corrected the typo in `deploy_remote_agent.ps1`. Also patched the live service immediately without a full redeploy:
```powershell
gcloud run services update remote-a2a-agent `
  --set-env-vars "GOOGLE_CLOUD_PROJECT=kpmgpoc,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=true" `
  --region us-central1 --project kpmgpoc
```

---

## 2. `gcloud auth print-identity-token` Fails in Agent Engine

**Symptom:** Root Agent worked locally but would fail in Agent Engine.

**Root Cause:** `agent.py` used `subprocess.check_output("gcloud auth print-identity-token")` to get an OIDC token. The `gcloud` CLI is not available in Agent Engine's runtime container.

**Fix:** Replaced with `google.oauth2.id_token.fetch_id_token()` which uses Application Default Credentials (ADC) via the metadata server — works in all GCP runtimes without the CLI.

```python
# Before
token = subprocess.check_output("gcloud auth print-identity-token", shell=True).decode().strip()

# After
import google.auth.transport.requests
import google.oauth2.id_token
auth_req = google.auth.transport.requests.Request()
token = google.oauth2.id_token.fetch_id_token(auth_req, audience)
```

---

## 3. Agent Engine: `RemoteA2aAgent` Import Fails at Startup

**Symptom:** Every Agent Engine deployment failed with `UserCodeControlPlaneError` at `load_agent_from_python_spec/config.py`.

**Root Cause:** `adk deploy agent_engine` auto-generates a `requirements.txt` when none exists inside the agent directory. The auto-generated file uses plain `google-adk` (no extras), so:
```python
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent  # ModuleNotFoundError
```

**Evidence:** The deploy logs showed:
```
Creating a2a_poc_tmp.../requirements.txt...   ← auto-generated, missing [a2a]
```

**Fix:** Create `requirements.txt` **inside the agent directory** (`a2a_poc/requirements.txt`):
```
google-adk[a2a]
httpx
google-auth[requests]
google-cloud-secret-manager
python-dotenv
```
After the fix, the logs changed to show no "Creating" step — confirming the ADK used the provided file.

> ⚠️ The `requirements.txt` in the project root is **not** used by `adk deploy agent_engine`. It must be inside the agent module directory.

---

## 4. Module-Level Network Calls Block Agent Engine Startup

**Symptom:** Agent Engine startup timeout / `UserCodeControlPlaneError`.

**Root Cause:** `agent.py` called `get_gsm_secret()` (Secret Manager) and `get_id_token()` (OIDC) at module import time. In Agent Engine, these can hang before the runtime network is fully ready.

**Fix:** Removed all module-level network calls. API key is now read directly from `os.getenv()` (loaded by `load_dotenv()` from the bundled `.env` file). Secret Manager fetching is preserved as an on-demand helper but never called at import time.

---

## 5. Windows `charmap` Codec Makes Success Look Like Failure

**Symptom:** `deploy_root_agent.ps1` printed "Deploy failed" even for successful deployments.

**Root Cause:** On Windows terminals using `cp1252` encoding, Python can't print the `✅` emoji (`\u2705`) that the ADK includes in its success message. The exception is caught by the ADK and printed as:
```
Deploy failed: 'charmap' codec can't encode character '\u2705' in position 0
```

**Fix:** Set UTF-8 output encoding before calling `adk deploy agent_engine`:
```powershell
$env:PYTHONIOENCODING = "utf-8"
$deployOutput = adk deploy agent_engine ... 2>&1
$env:PYTHONIOENCODING = $null
```

> Note: `adk deploy agent_engine` always exits with code 0 regardless of success or failure, so exit code checks don't work. Parse the output for `"Deploy failed"` instead.

---

## 6. Cloud Run Service Is Private — Agent Engine Gets 403

**Symptom:** Agent Engine started successfully but every request failed with:
```
Failed to resolve AgentCard: HTTP Error 403: Client error '403 Forbidden' for url '.../.well-known/agent.json'
```

**Root Cause:** The Cloud Run `remote-a2a-agent` service had no IAM bindings (private by default). Agent Engine's requests were rejected by Cloud Run's IAM layer before the app even saw them.

**Fix:** Grant `allUsers` the `roles/run.invoker` role (requires Cloud Run Admin or Project IAM Admin):
```bash
gcloud run services add-iam-policy-binding remote-a2a-agent \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --region us-central1 \
  --project kpmgpoc
```

> The app-level `X-Agent-Key` header check in the remote agent middleware still enforces authentication at the application layer.

> ⚠️ The `nuthan.kishore2025@gmail.com` account lacks `run.services.setIamPolicy`. Use the admin account (`ITSupport@winwire.com`) or the Cloud Console.

---

## 7. Agentspace / Gemini Integration — Missing `discoveryengine.setIamPolicy`

**Symptom:**
```
Missing or blocked permissions: discoveryengine.googleapis.com/agents.setIamPolicy
```

**Root Cause:** Integrating Agent Engine with Agentspace or Gemini for Workspace requires the `roles/discoveryengine.admin` role, which the standard dev account doesn't have.

**Fix (run as admin):**

*PowerShell:*
```powershell
gcloud projects add-iam-policy-binding kpmgpoc `
  --member="user:nuthan.kishore2025@gmail.com" `
  --role="roles/discoveryengine.admin"
```

*Bash:*
```bash
gcloud projects add-iam-policy-binding kpmgpoc \
  --member="user:nuthan.kishore2025@gmail.com" \
  --role="roles/discoveryengine.admin"
```

---

## Quick Reference: Account Permissions

| Action                             | Required Role                           | Working Account                |
| ---------------------------------- | --------------------------------------- | ------------------------------ |
| Deploy Cloud Run                   | `roles/run.developer`                   | `nuthan.kishore2025@gmail.com` |
| Set Cloud Run IAM (public/private) | `roles/run.admin`                       | `ITSupport@winwire.com`        |
| Set project-level IAM              | `roles/resourcemanager.projectIamAdmin` | `ITSupport@winwire.com`        |
| Discovery Engine / Agentspace      | `roles/discoveryengine.admin`           | Grant via admin                |

---

## Quick Reference: `adk deploy agent_engine` Gotchas

| Gotcha                            | Detail                                                                  |
| --------------------------------- | ----------------------------------------------------------------------- |
| `requirements.txt` location       | Must be **inside the agent dir** (`a2a_poc/`), not the project root     |
| Exit code                         | Always `0` — parse output for `"Deploy failed"` string                  |
| Windows emoji crash               | Set `PYTHONIOENCODING=utf-8` before running                             |
| Module-level code                 | Runs at **import time** in Agent Engine — no network calls allowed      |
| `.env` file                       | **IS** bundled with the package — `load_dotenv()` works in Agent Engine |
| `GOOGLE_CLOUD_PROJECT`/`LOCATION` | Ignored from `.env` if `--project`/`--region` are explicitly passed     |
