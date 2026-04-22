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

# ── Topic quarantine ───────────────────────────────────────────────────────────
MAX_TOPIC_ATTEMPTS = 20  # hard cap: after 20 total attempts the topic is permanently quarantined

# ── Weighted certification rate ────────────────────────────────────────────────
CERT_WEIGHT_EASY   = 0.5   # sig_difficulty < DIFFICULTY_EASY_THRESHOLD
CERT_WEIGHT_MEDIUM = 1.0   # medium range
CERT_WEIGHT_HARD   = 1.5   # sig_difficulty > DIFFICULTY_HARD_THRESHOLD
DIFFICULTY_EASY_THRESHOLD = 0.3
DIFFICULTY_HARD_THRESHOLD = 0.7

# ── Affective layer A/B gate ───────────────────────────────────────────────────
AFFECTIVE_LAYER_ENABLED = True  # if False, NightRunner skips MoodEngine + IdentityCore injection
