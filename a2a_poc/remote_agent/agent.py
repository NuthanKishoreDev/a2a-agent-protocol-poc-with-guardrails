"""
Remote A2A Agent - Hello World Agent with Guardrails
Exposed via to_a2a() protocol on port 8081.

Tools:
  - roll_die(sides): Rolls a die with a given number of sides
  - check_prime(nums): Checks if a list of numbers are prime
  - get_weather(city): Gets current weather for a city (free, no API key)

Guardrails:
  1. Middleware API-key check  — rejects requests missing X-Agent-Key header
  2. Topic-scope guardrail     — rejects prompts unrelated to dice/primes/weather
  3. Content-safety guardrail  — blocks harmful/offensive content

Config: Vertex AI (kpmgpoc / us-central1)
"""

import os
import random
import urllib.request
import urllib.parse
import json
import logging
import time

from dotenv import load_dotenv

# Load environment variables from .env (must be before ADK imports)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.genai import types as genai_types

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("a2a_remote_agent")

# ---------------------------------------------------------------------------
# Guardrail configuration — easy to customise
# ---------------------------------------------------------------------------

# Optional: set to None to disable API-key auth entirely
REQUIRED_API_KEY = os.getenv("REMOTE_AGENT_API_KEY", "kpmg-dev-key-2026")

# Topics this agent is allowed to handle (keyword allowlist)
ALLOWED_KEYWORDS = [
    "dice", "die", "roll", "sides", "prime", "number",
    "weather", "temperature", "city", "forecast", "rain",
    "cloud", "wind", "humidity", "sun", "snow", "hello",
    "hi", "help", "what", "how", "can", "you", "is", "are",
]

# Hard-blocked phrases — always rejected regardless of topic
BLOCKED_PHRASES = [
    # Prompt injection / jailbreak attempts
    "hack", "exploit", "sql injection", "jailbreak", "ignore instructions",
    "forget your instructions", "act as", "pretend you are", "override",
    "system prompt", "ignore previous", "disregard",
    # Harmful content
    "bomb", "weapon", "violence", "illegal", "kill", "murder", "attack",
    # Hate speech / offensive language
    "i hate you", "hate you", "i hate", "you are stupid", "you are dumb",
    "idiot", "moron", "shut up", "you suck", "go to hell", "damn you",
    "worthless", "useless agent", "terrible agent",
]


# ---------------------------------------------------------------------------
# ASGI Middleware 1: API-Key Authentication
# ---------------------------------------------------------------------------

class APIKeyAuthMiddleware:
    """Rejects any request that doesn't carry the correct X-Agent-Key header."""

    EXEMPT_PATHS = {"/.well-known/agent.json", "/.well-known/agent-card.json"}

    def __init__(self, app):
        self.app = app
        self._logger = logging.getLogger("a2a_remote_agent.auth")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Skip auth for agent-card discovery endpoints
        if path in self.EXEMPT_PATHS or REQUIRED_API_KEY is None:
            await self.app(scope, receive, send)
            return

        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        provided_key = headers.get("x-agent-key", "")

        if provided_key != REQUIRED_API_KEY:
            self._logger.warning(
                "🚫 [AUTH] Rejected request to %s — invalid/missing X-Agent-Key (got: %r)",
                path, provided_key,
            )
            body = json.dumps({
                "error": "Unauthorized",
                "message": "Missing or invalid X-Agent-Key header.",
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({"type": "http.response.body", "body": body})
            return

        self._logger.info("✅ [AUTH] Request to %s authorised", path)
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# ASGI Middleware 2: Request/Response Logger
# ---------------------------------------------------------------------------

class A2ALoggingMiddleware:
    """Logs every A2A HTTP request body and response status."""

    def __init__(self, app):
        self.app = app
        self._logger = logging.getLogger("a2a_remote_agent.http")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        client = scope.get("client", ("unknown", 0))

        body_chunks = []

        async def receive_wrapper():
            message = await receive()
            if message.get("type") == "http.request":
                body_chunks.append(message.get("body", b""))
            return message

        response_status = [None]

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_status[0] = message.get("status", 0)
            await send(message)

        start = time.perf_counter()
        await self.app(scope, receive_wrapper, send_wrapper)
        elapsed_ms = (time.perf_counter() - start) * 1000

        body = b"".join(body_chunks)
        try:
            parsed = json.loads(body)
            body_display = json.dumps(parsed, indent=2)
        except Exception:
            body_display = body.decode(errors="replace") if body else "(empty)"

        self._logger.info(
            "\n"
            "┌─ A2A REQUEST ──────────────────────────────────────────\n"
            "│ %s %s  from %s:%s\n"
            "│ Body:\n%s\n"
            "└─ A2A RESPONSE ─────────────────────────────────────────\n"
            "│ Status : %s  |  Time : %.1f ms\n"
            "└────────────────────────────────────────────────────────",
            method, path, client[0], client[1],
            "\n".join("│   " + line for line in body_display.splitlines()),
            response_status[0], elapsed_ms,
        )


# ---------------------------------------------------------------------------
# ADK Guardrail: before_model_callback
# Fires before every LLM call — can return a blocked response immediately
# ---------------------------------------------------------------------------

def guardrail_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """
    Inspect the latest user message before it reaches Gemini.
    Returns an LlmResponse to block, or None to allow.
    """
    guard_logger = logging.getLogger("a2a_remote_agent.guardrail")

    # Extract the latest user text from the request
    user_text = ""
    if llm_request.contents:
        for content in reversed(llm_request.contents):
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if hasattr(part, "text") and part.text:
                        user_text = part.text.lower()
                        break
            if user_text:
                break

    if not user_text:
        return None  # nothing to check

    # ── Guardrail 1: Block harmful / unsafe content ──────────────────────────
    for phrase in BLOCKED_PHRASES:
        if phrase in user_text:
            guard_logger.warning(
                "🛑 [GUARDRAIL] Blocked harmful content — matched phrase: %r in: %r",
                phrase, user_text[:120],
            )
            return LlmResponse(
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(
                        text=(
                            "⛔ **Request Rejected** — Your message contains content "
                            "that violates this agent's usage policy and cannot be processed."
                        )
                    )],
                )
            )

    # ── Guardrail 2: Enforce topic scope ─────────────────────────────────────
    # Skip scope check only for very short messages (1–3 words: greetings etc.)
    if len(user_text.split()) > 3:
        has_allowed = any(kw in user_text for kw in ALLOWED_KEYWORDS)
        if not has_allowed:
            guard_logger.warning(
                "🛑 [GUARDRAIL] Blocked out-of-scope request: %r",
                user_text[:120],
            )
            return LlmResponse(
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(
                        text=(
                            "⛔ **Request Out of Scope** — This agent only handles:\n"
                            "- 🎲 Dice rolling\n"
                            "- 🔢 Prime number checking\n"
                            "- 🌤️  Current weather queries\n\n"
                            "Please rephrase your question within these topics."
                        )
                    )],
                )
            )

    guard_logger.info("✅ [GUARDRAIL] Request passed — text: %r", user_text[:80])
    return None  # allow


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def roll_die(sides: int, tool_context: ToolContext) -> int:
    """Roll a die and return the rolled result.

    Args:
        sides: The integer number of sides the die has.
        tool_context: The tool context (managed by ADK).

    Returns:
        An integer result of rolling the die.
    """
    result = random.randint(1, sides)
    logger.info("🎲 roll_die: sides=%d → result=%d", sides, result)
    if not hasattr(tool_context, "state"):
        tool_context.state = {}
    tool_context.state["last_roll"] = result
    return result


def check_prime(nums: list[int]) -> str:
    """Check if a given list of numbers are prime.

    Args:
        nums: The list of numbers to check.

    Returns:
        A string indicating which numbers are prime.
    """
    def is_prime(n: int) -> bool:
        if n < 2:
            return False
        if n == 2:
            return True
        if n % 2 == 0:
            return False
        for i in range(3, int(n**0.5) + 1, 2):
            if n % i == 0:
                return False
        return True

    results = [f"{n} is {'prime' if is_prime(n) else 'not prime'}" for n in nums]
    answer = ", ".join(results)
    logger.info("🔢 check_prime: nums=%s → %s", nums, answer)
    return answer


def get_weather(city: str) -> str:
    """Get the current weather for a city using the free Open-Meteo API (no API key required).

    Args:
        city: The name of the city to get weather for (e.g. 'London', 'Bangalore').

    Returns:
        A string describing the current weather conditions.
    """
    logger.info("🌤️  get_weather: city=%r", city)
    try:
        geo_url = (
            f"https://geocoding-api.open-meteo.com/v1/search"
            f"?name={urllib.parse.quote(city)}&count=1&language=en&format=json"
        )
        with urllib.request.urlopen(geo_url, timeout=10) as resp:
            geo_data = json.loads(resp.read().decode())

        if not geo_data.get("results"):
            return f"Could not find location for city: {city}"

        r = geo_data["results"][0]
        lat, lon = r["latitude"], r["longitude"]
        location_name, country = r.get("name", city), r.get("country", "")
        logger.info("📍 Geocoded %r → %s, %s (%.4f, %.4f)", city, location_name, country, lat, lon)

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
            f"&temperature_unit=celsius&wind_speed_unit=kmh"
        )
        with urllib.request.urlopen(weather_url, timeout=10) as resp:
            current = json.loads(resp.read().decode()).get("current", {})

        WMO = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Foggy", 48: "Icy fog", 51: "Light drizzle", 53: "Moderate drizzle",
            55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
            80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
            95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
        }
        result = (
            f"Current weather in {location_name}, {country}:\n"
            f"  Condition   : {WMO.get(current.get('weather_code', 0), 'Unknown')}\n"
            f"  Temperature : {current.get('temperature_2m', 'N/A')}°C\n"
            f"  Humidity    : {current.get('relative_humidity_2m', 'N/A')}%\n"
            f"  Wind Speed  : {current.get('wind_speed_10m', 'N/A')} km/h"
        )
        logger.info("✅ get_weather result:\n%s", result)
        return result
    except Exception as e:
        logger.error("❌ get_weather failed for %r: %s", city, e)
        return f"Failed to fetch weather for '{city}': {e}"


# ---------------------------------------------------------------------------
# Root Agent — with guardrail callback attached
# ---------------------------------------------------------------------------

root_agent = Agent(
    model="gemini-2.0-flash",
    name="hello_world_agent",
    description="Agent that can roll dice, check prime numbers, and get current weather.",
    instruction="""
    I can roll dice, check prime numbers, and get the current weather for any city.

    When I am asked to roll a die, call the roll_die tool with the number of sides (integer).
    When checking prime numbers, call the check_prime tool with a list of integers.
    When asked about weather, call the get_weather tool with the city name (string).

    When asked to roll a die AND check primes:
      1. Call roll_die first. Wait for the result.
      2. Call check_prime with that result.
      3. Always include the roll result in my response.
    """,
    tools=[roll_die, check_prime, get_weather],
    before_model_callback=guardrail_callback,
)

# ---------------------------------------------------------------------------
# Build ASGI app: Agent → Logging middleware → Auth middleware
# ---------------------------------------------------------------------------

_a2a_app   = to_a2a(root_agent, port=8081)
_logged    = A2ALoggingMiddleware(_a2a_app)
a2a_app    = APIKeyAuthMiddleware(_logged)

logger.info(
    "✅ A2A Remote Agent ready\n"
    "   Tools     : roll_die | check_prime | get_weather\n"
    "   Guardrails: content-safety | topic-scope | api-key auth (key=%r)",
    REQUIRED_API_KEY,
)
