"""
Root (Consuming) Agent - A2A POC
Connects to the remote Hello World agent via A2A protocol.

The RemoteA2aAgent reads the agent card from the remote server and
delegates user requests to it transparently using the A2A protocol.

Config: Vertex AI (kpmgpoc / us-central1)

Auth note: The remote Cloud Run service uses --allow-unauthenticated with
an application-level API key (X-Agent-Key header). No OIDC token is needed.
"""

import os
import logging
import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env FIRST, before any Google SDK imports, so that
# GOOGLE_GENAI_USE_VERTEXAI / GOOGLE_CLOUD_PROJECT are visible to ADK.
# In Agent Engine, this .env file is bundled with the agent package.
# ---------------------------------------------------------------------------
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Now safe to import ADK (picks up env vars above)
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — read from environment (set by .env or Agent Engine config)
# No network calls at module level to ensure clean startup in Agent Engine.
# ---------------------------------------------------------------------------
REMOTE_AGENT_URL = os.getenv("REMOTE_AGENT_URL", "http://localhost:8081").rstrip("/")
REMOTE_AGENT_API_KEY = os.getenv("REMOTE_AGENT_API_KEY", "kpmg-dev-key-2026")

# ---------------------------------------------------------------------------
# HTTP client — API key header only.
# The Cloud Run service is --allow-unauthenticated; auth is handled by the
# X-Agent-Key application-level check in the remote agent's middleware.
# ---------------------------------------------------------------------------
_http_client = httpx.AsyncClient(
    headers={"X-Agent-Key": REMOTE_AGENT_API_KEY},
    timeout=httpx.Timeout(60.0),
)

# ---------------------------------------------------------------------------
# Root agent: delegates to the deployed Remote A2A Agent
# ---------------------------------------------------------------------------
agent_card_url = f"{REMOTE_AGENT_URL}/.well-known/agent.json"

root_agent = RemoteA2aAgent(
    name="a2a_root_agent",
    agent_card=agent_card_url,
    description="Root agent that connects to the remote Hello World A2A agent.",
    httpx_client=_http_client,
)

# ---------------------------------------------------------------------------
# Helpers kept for optional/future use (e.g. manual secret rotation script)
# Not called at module level to avoid blocking startup.
# ---------------------------------------------------------------------------

def get_gsm_secret(secret_id: str, version_id: str = "latest") -> str | None:
    """Fetch a secret from GCP Secret Manager on demand."""
    try:
        from google.cloud import secretmanager
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "kpmgpoc")
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.warning("GSM fetch failed for '%s': %s", secret_id, e)
        return None
