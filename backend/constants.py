SUCCESS_SCORE_THRESHOLD = 7.5

# ── Provider chains ────────────────────────────────────────────────────────────
# Single source of truth for LLM provider priority.
# Edit here to change the global provider order.
PROVIDERS_PRIMARY   = ["Groq", "Gemini"]          # fast + cheap
PROVIDERS_FULL      = ["Groq", "OpenAI", "Gemini", "Claude"]   # full fallback chain
PROVIDERS_WITH_OAI  = ["Groq", "OpenAI", "Gemini"]  # mid-tier chain

# ── Benchmark certification settings ──────────────────────────────────────────
# Set BENCHMARK_ENABLED = False to fall back to LLM-only scoring (e.g. if Docker is unavailable).
BENCHMARK_ENABLED        = True
BENCHMARK_PASS_THRESHOLD = 0.6   # min pass_rate required for certification (0.0–1.0)
BENCHMARK_WEIGHT         = 0.6   # weight of benchmark score in blended final_score
