
import asyncio
import httpx
import uuid
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("test_cloud_run")

REMOTE_URL = "https://remote-a2a-agent-495485641332.us-central1.run.app"
API_KEY = "kpmg-dev-key-2026"

import subprocess

def get_id_token():
    try:
        token = subprocess.check_output("gcloud auth print-identity-token", shell=True).decode().strip()
        logger.info("🔑 Obtained ID Token")
        return token
    except Exception as e:
        logger.warning(f"⚠️  Could not get ID token: {e}")
        return None

async def test_cloud_run():
    logger.info(f"🚀 Testing Remote Agent at: {REMOTE_URL}")
    
    token = get_id_token()
    auth_headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 1. Test Discovery Endpoint (No Auth? Actually Cloud Run requires auth if private)
    async with httpx.AsyncClient() as client:
        try:
            # Add auth headers for Cloud Run access
            resp = await client.get(f"{REMOTE_URL}/.well-known/agent.json", headers=auth_headers)
            if resp.status_code == 200:
                logger.info("✅ Discovery Endpoint (.well-known/agent.json): OK")
                logger.info(f"   Response: {resp.text}")
            else:
                logger.error(f"❌ Discovery Failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"❌ Connection Error: {e}")
            return

    # 2. Test A2A Endpoint Candidates
    endpoint_candidates = [
        f"{REMOTE_URL}/message/send",
        f"{REMOTE_URL}/message/send/",
        f"{REMOTE_URL}/",
        f"{REMOTE_URL}/hello_world_agent/message/send",
        f"{REMOTE_URL}/a2a/message/send"
    ]
    
    headers = {
        "X-Agent-Key": API_KEY,
        "Content-Type": "application/json"
    }
    headers.update(auth_headers)
    
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": str(uuid.uuid4()),
        "params": {
            "message_id": str(uuid.uuid4()),
            "message": {
                "role": "user",
                "parts": [{"text": "Roll a die"}]
            }
        }
    }

    async with httpx.AsyncClient() as client:
        for endpoint in endpoint_candidates:
            try:
                logger.info(f"📤 Probing {endpoint}...")
                resp = await client.post(endpoint, json=payload, headers=headers, timeout=10.0)
                
                if resp.status_code == 200:
                    logger.info(f"✅ FOUND! Endpoint: {endpoint}")
                    print(json.dumps(resp.json(), indent=2))
                    return
                elif resp.status_code != 404:
                    logger.info(f"⚠️  {endpoint} returned {resp.status_code} (Not 404)")
                    logger.info(f"   Body: {resp.text[:200]}")
                else:
                    logger.info(f"❌ {endpoint} -> 404")

            except Exception as e:
                logger.error(f"❌ Request Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_cloud_run())
