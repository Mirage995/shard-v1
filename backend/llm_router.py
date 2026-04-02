"""LLM Router -- Multi-provider completion with exponential backoff + circuit breaker.

Provider chain: Claude (Anthropic) -> Groq (LLaMA-70B) -> Gemini (Flash) -> Ollama (local).
Each provider has its own in-memory circuit breaker and retry policy.

Retry logic:
  - Transient errors (rate limit, timeout, 5xx): exponential backoff, up to 3 attempts.
  - Hard errors (auth, 404): immediate fallthrough to next provider, no retry wasted.
  - Circuit breaker: trips after 3 consecutive failures, recovers after 60s probe.

Log markers to watch:
  [CIRCUIT] *** <name> -> OPEN ***   -- provider is down, being skipped
  [CIRCUIT] <name> -> HALF_OPEN      -- probing recovery
  [CIRCUIT] <name> -> CLOSED         -- provider back online
  [LLM_ROUTER] <name> exhausted     -- all retries done, falling through
  [LLM_ROUTER] *** ALL PROVIDERS FAILED ***
"""
import asyncio
import logging
import os
import random
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger("shard.llm_router")

# Weak ref to consciousness -- set by server.py after init
_consciousness_ref = None

def set_consciousness(c):
    global _consciousness_ref
    _consciousness_ref = c

def _log_fallback(from_p: str, to_p: str, reason: str):
    if _consciousness_ref and hasattr(_consciousness_ref, 'interpretability'):
        try:
            _consciousness_ref.interpretability.log_provider_fallback(from_p, to_p, reason)
        except Exception:
            pass

# ── Tunables ───────────────────────────────────────────────────────────────────
_FAILURE_THRESHOLD = 3     # consecutive failures before circuit trips
_RECOVERY_TIMEOUT  = 60.0  # seconds before HALF_OPEN probe
_MAX_RETRIES       = 3     # total attempts per provider (1 + 2 retries)
_BASE_DELAY        = 1.0   # seconds -- doubles each retry
_MAX_DELAY         = 16.0  # backoff ceiling

_TIMEOUT: dict[str, float] = {
    "Claude": 90.0,
    "Groq":   25.0,
    "Gemini": 60.0,   # synthesis su testi lunghi richiede più tempo
    "OpenAI": 60.0,
}

# ── Error classification ───────────────────────────────────────────────────────
_TRANSIENT = (
    "rate", "limit", "timeout", "timed out",
    "503", "502", "500", "server error",
    "connection", "temporarily", "overloaded",
)
_HARD = (
    "401", "403", "400", "invalid api key", "authentication",
    "unauthorized", "not found", "404", "invalid_api_key",
    "credit", "billing", "balance", "payment", "quota exceeded",
    "insufficient", "overdue", "spend limit", "too low",
    "bad request",
)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _TRANSIENT)


def _is_hard(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _HARD)


# ── Circuit breaker ────────────────────────────────────────────────────────────
_CLOSED    = "CLOSED"
_OPEN      = "OPEN"
_HALF_OPEN = "HALF_OPEN"


@dataclass
class _CircuitBreaker:
    name: str
    failure_threshold: int   = _FAILURE_THRESHOLD
    recovery_timeout: float  = _RECOVERY_TIMEOUT
    state: str               = field(default=_CLOSED,    init=False)
    failure_count: int       = field(default=0,          init=False)
    last_failure_time: float = field(default=0.0,        init=False)

    def is_available(self) -> bool:
        if self.state == _CLOSED:
            return True
        if self.state == _OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = _HALF_OPEN
                logger.warning(
                    "[CIRCUIT] %s -> HALF_OPEN -- probing recovery after %.0fs down",
                    self.name, elapsed,
                )
                return True
            return False
        return True  # HALF_OPEN: let one request through

    def record_success(self):
        if self.state != _CLOSED:
            logger.info("[CIRCUIT] %s -> CLOSED (provider recovered)", self.name)
        self.state = _CLOSED
        self.failure_count = 0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        prev = self.state
        if self.failure_count >= self.failure_threshold or self.state == _HALF_OPEN:
            self.state = _OPEN
            if prev != _OPEN:
                logger.critical(
                    "[CIRCUIT] *** %s -> OPEN -- provider DOWN after %d failures,"
                    " skipping for %.0fs ***",
                    self.name, self.failure_count, self.recovery_timeout,
                )


_breakers: dict[str, _CircuitBreaker] = {
    "Claude": _CircuitBreaker("Claude"),
    "Groq":   _CircuitBreaker("Groq"),
    "Gemini": _CircuitBreaker("Gemini"),
    "OpenAI": _CircuitBreaker("OpenAI"),
}

# ── Semaphores ────────────────────────────────────────────────────────────────
_CLAUDE_SEMAPHORE  = asyncio.Semaphore(3)
_GROQ_SEMAPHORE    = asyncio.Semaphore(5)
_GEMINI_SEMAPHORE  = asyncio.Semaphore(5)
_OPENAI_SEMAPHORE  = asyncio.Semaphore(3)


# ── Retry + backoff core ───────────────────────────────────────────────────────

async def _call_with_backoff(
    name: str,
    coro_factory: Callable[[], Awaitable[str]],
) -> str:
    """Run coro_factory() with exponential backoff; update circuit breaker on outcome.

    coro_factory is called fresh on every attempt (new coroutine each time).
    Hard errors propagate immediately -- no backoff wasted.
    """
    cb      = _breakers[name]
    timeout = _TIMEOUT[name]
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = await asyncio.wait_for(coro_factory(), timeout=timeout)
            cb.record_success()
            return result

        except asyncio.TimeoutError as exc:
            last_exc = exc
            logger.warning(
                "[LLM_ROUTER] %s attempt %d/%d timed out (%.0fs)",
                name, attempt, _MAX_RETRIES, timeout,
            )
            # Timeouts are always transient -- fall through to backoff logic below

        except Exception as exc:
            last_exc = exc
            if _is_hard(exc):
                logger.error(
                    "[LLM_ROUTER] %s hard error -- no retry: %s", name, exc,
                )
                cb.record_failure()
                raise  # caller sees this and falls through to next provider

            logger.warning(
                "[LLM_ROUTER] %s attempt %d/%d failed: %s",
                name, attempt, _MAX_RETRIES, exc,
            )

        if attempt < _MAX_RETRIES:
            delay  = min(_MAX_DELAY, _BASE_DELAY * (2 ** (attempt - 1)))
            jitter = random.uniform(0, delay * 0.2)
            wait   = round(delay + jitter, 2)
            logger.info(
                "[LLM_ROUTER] %s backoff %.1fs before retry %d/%d",
                name, wait, attempt + 1, _MAX_RETRIES,
            )
            await asyncio.sleep(wait)

    # All attempts exhausted
    cb.record_failure()
    raise last_exc or RuntimeError(f"{name}: all {_MAX_RETRIES} attempts failed")


# ── Lazy singletons ────────────────────────────────────────────────────────────
_anthropic_client = None
_groq_client      = None
_gemini_client    = None
_openai_client    = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            try:
                import anthropic
                _anthropic_client = anthropic.Anthropic(api_key=key)
            except ImportError:
                logger.warning("[LLM_ROUTER] anthropic package not installed.")
    return _anthropic_client


def _get_groq():
    global _groq_client
    if _groq_client is None:
        key = os.getenv("GROQ_API_KEY")
        if key:
            try:
                from groq import Groq
                _groq_client = Groq(api_key=key)
            except ImportError:
                logger.warning("[LLM_ROUTER] groq package not installed.")
    return _groq_client


def _get_openai():
    global _openai_client
    if _openai_client is None:
        key = os.getenv("OPENAI_API_KEY")
        if key:
            try:
                from openai import OpenAI
                _openai_client = OpenAI(api_key=key)
                logger.info("[LLM_ROUTER] OpenAI client initialized OK.")
            except ImportError:
                logger.warning("[LLM_ROUTER] openai package not installed.")
    return _openai_client


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            logger.warning("[LLM_ROUTER] GEMINI_API_KEY not set -- Gemini Flash disabled.")
            return None
        try:
            from google import genai
            _gemini_client = genai.Client(api_key=key)
            logger.info("[LLM_ROUTER] Gemini Flash client initialized OK.")
        except ImportError:
            logger.warning("[LLM_ROUTER] google-genai package not installed -- Gemini Flash disabled.")
        except Exception as exc:
            logger.critical("[LLM_ROUTER] Gemini Flash init FAILED: %s", exc)
    return _gemini_client





# ── Main router ────────────────────────────────────────────────────────────────

async def llm_complete(
    prompt: str,
    system: str = "You are a precise code repair assistant. Output only valid Python code, no markdown.",
    max_tokens: int = 4096,
    temperature: float = 0.1,
    providers: list[str] = ["OpenAI", "Gemini", "Groq", "Claude"]
) -> str:
    """Return a completion, trying the specified providers in order.

    Raises RuntimeError only if ALL specified providers are exhausted or open.
    """
    errors: list[str] = []

    for provider in providers:
        if provider == "Claude":
            if _breakers["Claude"].is_available():
                client = _get_anthropic()
                if client:
                    try:
                        async def _claude_call():
                            async with _CLAUDE_SEMAPHORE:
                                def _sync():
                                    return client.messages.create(
                                        model="claude-3-5-sonnet-20241022",
                                        max_tokens=max_tokens,
                                        system=system,
                                        messages=[{"role": "user", "content": prompt}],
                                    )
                                msg = await asyncio.to_thread(_sync)
                                return msg.content[0].text.strip()

                        result = await _call_with_backoff("Claude", _claude_call)
                        logger.info("[LLM_ROUTER] Claude OK (%d chars)", len(result))
                        return result
                    except Exception as exc:
                        logger.warning("[LLM_ROUTER] Claude exhausted -- falling through. Reason: %s", exc)
                        errors.append(f"Claude: {exc}")
                        _log_fallback("Claude", "Groq", str(exc))
            else:
                logger.warning("[LLM_ROUTER] Claude circuit OPEN")
                errors.append("Claude: circuit breaker OPEN")

        elif provider == "Groq":
            if _breakers["Groq"].is_available():
                groq = _get_groq()
                if groq:
                    try:
                        async def _groq_call():
                            async with _GROQ_SEMAPHORE:
                                def _sync():
                                    return groq.chat.completions.create(
                                        model="llama-3.3-70b-versatile",
                                        messages=[
                                            {"role": "system", "content": system},
                                            {"role": "user", "content": prompt},
                                        ],
                                        temperature=temperature,
                                        max_tokens=min(max_tokens, 32768),
                                    )
                                resp = await asyncio.to_thread(_sync)
                                return resp.choices[0].message.content.strip()

                        result = await _call_with_backoff("Groq", _groq_call)
                        logger.info("[LLM_ROUTER] Groq OK (%d chars)", len(result))
                        return result
                    except Exception as exc:
                        logger.warning("[LLM_ROUTER] Groq exhausted -- falling through. Reason: %s", exc)
                        errors.append(f"Groq: {exc}")
                        _log_fallback("Groq", "Gemini", str(exc))
            else:
                logger.warning("[LLM_ROUTER] Groq circuit OPEN")
                errors.append("Groq: circuit breaker OPEN")

        elif provider == "OpenAI":
            if _breakers["OpenAI"].is_available():
                openai = _get_openai()
                if openai:
                    try:
                        async def _openai_call():
                            async with _OPENAI_SEMAPHORE:
                                def _sync():
                                    return openai.chat.completions.create(
                                        model="gpt-4o-mini",
                                        messages=[
                                            {"role": "system", "content": system},
                                            {"role": "user", "content": prompt},
                                        ],
                                        temperature=temperature,
                                        max_tokens=max_tokens,
                                    )
                                resp = await asyncio.to_thread(_sync)
                                return resp.choices[0].message.content.strip()

                        result = await _call_with_backoff("OpenAI", _openai_call)
                        logger.info("[LLM_ROUTER] OpenAI OK (%d chars)", len(result))
                        return result
                    except Exception as exc:
                        logger.warning("[LLM_ROUTER] OpenAI exhausted -- falling through. Reason: %s", exc)
                        errors.append(f"OpenAI: {exc}")
            else:
                logger.warning("[LLM_ROUTER] OpenAI circuit OPEN")
                errors.append("OpenAI: circuit breaker OPEN")

        elif provider == "Gemini":
            if _breakers["Gemini"].is_available():
                genai = _get_gemini()
                if genai:
                    try:
                        async def _gemini_call():
                            async with _GEMINI_SEMAPHORE:
                                from google.genai import types
                                resp = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        lambda: genai.models.generate_content(
                                            model="gemini-2.0-flash",
                                            contents=prompt,
                                            config=types.GenerateContentConfig(
                                                system_instruction=system,
                                                temperature=temperature,
                                                max_output_tokens=max_tokens,
                                            ),
                                        )
                                    ),
                                    timeout=55.0,  # hard inner timeout < outer 60s
                                )
                                return resp.text.strip()

                        result = await _call_with_backoff("Gemini", _gemini_call)
                        logger.info("[LLM_ROUTER] Gemini OK (%d chars)", len(result))
                        return result
                    except Exception as exc:
                        logger.critical("[LLM_ROUTER] Gemini exhausted -- RAW ERROR: %s", exc)
                        errors.append(f"Gemini: {exc}")
            else:
                logger.warning("[LLM_ROUTER] Gemini circuit OPEN")
                errors.append("Gemini: circuit breaker OPEN")

    raise RuntimeError(
        "[LLM_ROUTER] *** ALL PROVIDERS FAILED ***\n"
        + "\n".join(f"  {e}" for e in errors)
    )


# ── Health / introspection ─────────────────────────────────────────────────────

def get_circuit_breaker_status() -> dict:
    """Snapshot of all circuit breakers -- plug into a /health endpoint."""
    return {
        name: {
            "state": cb.state,
            "failure_count": cb.failure_count,
            "seconds_since_last_failure": (
                round(time.monotonic() - cb.last_failure_time, 1)
                if cb.last_failure_time > 0 else None
            ),
        }
        for name, cb in _breakers.items()
    }
