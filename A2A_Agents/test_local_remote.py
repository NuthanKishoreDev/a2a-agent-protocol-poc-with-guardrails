
import asyncio
import httpx
import uuid
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("test_local_remote")

REMOTE_URL = "http://localhost:8081"
API_KEY = "kpmg-dev-key-2026"

async def test_local_remote():
    logger.info(f"🚀 Testing Local Remote Agent at: {REMOTE_URL}")
    
    # 1. Test Discovery
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{REMOTE_URL}/.well-known/agent.json")
            if resp.status_code == 200:
                logger.info("✅ Discovery Endpoint: OK")
            else:
                logger.error(f"❌ Discovery Failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"❌ Connection Error: {e}")
            return

    endpoint_candidates = [
        f"{REMOTE_URL}/message/send",
        f"{REMOTE_URL}/",
        f"{REMOTE_URL}/hello_world_agent/message/send",
        f"{REMOTE_URL}/a2a/message/send"
    ]

    async with httpx.AsyncClient() as client:
        for endpoint in endpoint_candidates:
            try:
                logger.info(f"📤 Probing {endpoint}...")
                resp = await client.post(endpoint, json=payload, headers=headers, timeout=5.0)
                
                if resp.status_code == 200:
                    logger.info(f"✅ FOUND! Endpoint: {endpoint}")
                    print(json.dumps(resp.json(), indent=2))
                    return # Stop on first success
                elif resp.status_code != 404:
                    logger.info(f"⚠️  {endpoint} returned {resp.status_code} (Not 404)")
                else:
                    logger.info(f"❌ {endpoint} -> 404")

            except Exception as e:
                logger.error(f"❌ Request Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_local_remote())
