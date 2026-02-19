"""
Test OAuth2 endpoint on remote agent.
Runs uvicorn in a subprocess, tests all 4 cases, then exits.
"""
import subprocess, sys, time, httpx, os, signal

BASE = "http://127.0.0.1:8082"
env = {**os.environ, "REMOTE_AGENT_API_KEY": "kpmg-dev-key-2026", "OAUTH_CLIENT_ID": "kpmg-gemini-client"}

print("Starting remote agent on port 8082...")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "remote_agent.agent:a2a_app",
     "--host", "127.0.0.1", "--port", "8082", "--log-level", "error"],
    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(3)  # wait for startup

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        result = fn()
        print(f"  ✅ PASS  {name}: {result}")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAIL  {name}: {e}")
        failed += 1

print("\n--- OAuth2 Token Endpoint Tests ---")

# T1: Valid client_id + client_secret → 200 + token
def t1():
    r = httpx.post(f"{BASE}/oauth2/token",
        data={"grant_type":"client_credentials","client_id":"kpmg-gemini-client","client_secret":"kpmg-dev-key-2026"},
        headers={"Content-Type":"application/x-www-form-urlencoded"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    t = r.json()
    return f"token={t['access_token']!r} type={t['token_type']}"
test("Valid client_id + secret → token", t1)

# T2: Wrong client_id → 401
def t2():
    r = httpx.post(f"{BASE}/oauth2/token",
        data={"grant_type":"client_credentials","client_id":"wrong-client","client_secret":"kpmg-dev-key-2026"},
        headers={"Content-Type":"application/x-www-form-urlencoded"})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    return f"rejected with 401 ({r.json()['error']})"
test("Wrong client_id → 401", t2)

# T3: Wrong client_secret → 401
def t3():
    r = httpx.post(f"{BASE}/oauth2/token",
        data={"grant_type":"client_credentials","client_id":"kpmg-gemini-client","client_secret":"wrong-secret"},
        headers={"Content-Type":"application/x-www-form-urlencoded"})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    return f"rejected with 401 ({r.json()['error']})"
test("Wrong client_secret → 401", t3)

# T4: Bearer token (obtained from T1) accepted on a protected path
def t4():
    r = httpx.get(f"{BASE}/.well-known/agent.json",
        headers={"Authorization": "Bearer kpmg-dev-key-2026"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    return f"agent name={r.json()['name']!r}"
test("Bearer token accepted on discovery", t4)

# T5: No auth on protected path → 401
def t5():
    r = httpx.post(f"{BASE}/", json={"jsonrpc":"2.0","method":"message/send","id":1,
        "params":{"message":{"role":"user","parts":[{"kind":"text","text":"hi"}]}}})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    return f"A2A endpoint correctly rejects unauthenticated (401)"
test("No auth on A2A endpoint → 401", t5)

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed")

proc.terminate()
proc.wait()
sys.exit(0 if failed == 0 else 1)
