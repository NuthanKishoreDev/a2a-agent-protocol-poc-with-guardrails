"""
Root (Consuming) Agent - A2A POC
Connects to the remote Hello World agent via A2A protocol.

The RemoteA2aAgent reads the agent card from the remote server and
delegates user requests to it transparently using the A2A protocol.

Config: Vertex AI (kpmgpoc / us-central1)
"""

import os
import httpx
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

# ---------------------------------------------------------------------------
# API key for the remote agent's auth middleware
# Must match REMOTE_AGENT_API_KEY in remote_agent's .env (default: kpmg-dev-key-2026)
# ---------------------------------------------------------------------------

REMOTE_AGENT_API_KEY = os.getenv("REMOTE_AGENT_API_KEY", "kpmg-dev-key-2026")

# Pre-configure an httpx client that always sends the X-Agent-Key header
_http_client = httpx.AsyncClient(
    headers={"X-Agent-Key": REMOTE_AGENT_API_KEY},
    timeout=httpx.Timeout(60.0),
)

# ---------------------------------------------------------------------------
# Root agent: delegates to the remote Hello World A2A agent
# ---------------------------------------------------------------------------

root_agent = RemoteA2aAgent(
    name="a2a_root_agent",
    agent_card="http://localhost:8081/.well-known/agent.json",
    description="Root agent that connects to the remote Hello World A2A agent.",
    httpx_client=_http_client,
)
