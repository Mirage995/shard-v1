"""validate_ticket20.py -- Validation run for Ticket #20: Mock Networking in Sandbox.

Forces a single study cycle on a specific HTTP/requests topic and prints
a filtered report showing only the tags relevant to #20:
  [BENCHMARK_GEN]  -- mock template detection and test generation
  [SANDBOX]        -- import ban bypass + mock prompt injection
  [BENCHMARK_RUN]  -- per-test pass/fail inside Docker --network none
  [CERTIFY]        -- final certification verdict
"""
import asyncio
import logging
import re
import sys
import os

# Force UTF-8 on Windows console (handles ✅ ❌ ✓ ⚠️ from study_phases logs)
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Working directory ──────────────────────────────────────────────────────────
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "backend")

TOPIC = "Custom HTTP 1.1 Web Server with keep-alive implementation using raw sockets (AF_INET, SOCK_STREAM)"

TAGS_OF_INTEREST = re.compile(
    r"\[(BENCHMARK_GEN|SANDBOX|BENCHMARK_RUN|CERTIFY|CERT|AFFORD|PREREQ|MOCK|MUTATE|EVO|STRATEGY|PIVOT)\]"
)

# ── Custom handler: print only lines with our tags ─────────────────────────────

class FilteredHandler(logging.StreamHandler):
    def emit(self, record):
        msg = self.format(record)
        if TAGS_OF_INTEREST.search(msg) or record.levelno >= logging.WARNING:
            print(msg)

# Quiet everything except our tags + WARNING+
root = logging.getLogger()
root.setLevel(logging.DEBUG)
root.handlers.clear()
h = FilteredHandler(sys.stdout)
h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S"))
root.addHandler(h)

# Also capture print() calls from benchmark_generator / study_phases
import builtins
_orig_print = builtins.print
def _filtered_print(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    if TAGS_OF_INTEREST.search(msg) or any(
        tag in msg for tag in (
            "[SANDBOX]", "[CERTIFY]", "[CERT]", "[AFFORD]", "[PREREQ]",
            "[MUTATE]", "[EVO]", "[STRATEGY]", "[PIVOT]",
            "Network topic", "mock template", "import ban", "bypass",
            "certified", "CERTIFIED", "FAILED", "score",
            "decompos", "feasib", "mutation", "pivot", "strategy",
            "out of reach", "Affordance",
        )
    ):
        _orig_print(*args, **kwargs)
builtins.print = _filtered_print


async def main():
    _orig_print(f"\n{'='*70}")
    _orig_print(f"  BOSS FIGHT VALIDATION RUN")
    _orig_print(f"  Topic: {TOPIC}")
    _orig_print(f"{'='*70}\n")

    # ── Pre-flight checks ─────────────────────────────────────────────────────
    from backend.benchmark_generator import is_network_topic
    from backend.affordance_filter import check_affordance, FEASIBILITY_THRESHOLD
    from backend.capability_graph import CapabilityGraph

    _orig_print("── PRE-FLIGHT CHECKS ──────────────────────────────────────────")

    # 1. Network topic detection
    detected = is_network_topic(TOPIC)
    _orig_print(f"[PRE-CHECK] is_network_topic = {detected} → {'mock template' if detected else 'STANDARD template'}")

    # 2. Affordance check against current capability graph
    cap_graph = CapabilityGraph()
    aff = check_affordance(TOPIC, cap_graph)
    _orig_print(f"[PRE-CHECK] affordance.feasibility = {aff.feasibility:.3f}  (threshold={FEASIBILITY_THRESHOLD})")
    _orig_print(f"[PRE-CHECK] affordance.feasible    = {aff.feasible}")
    if not aff.feasible:
        _orig_print(f"[PRE-CHECK] → Affordance filter would decompose into: {aff.sub_topics}")
        _orig_print(f"[PRE-CHECK] NOTE: affordance gate only runs inside NightRunner loop, not in direct study_topic() call")
    else:
        _orig_print(f"[PRE-CHECK] → Topic passes affordance gate — proceeding directly")

    _orig_print(f"[PRE-CHECK] capabilities in graph: {len(cap_graph.capabilities)}")
    _orig_print("──────────────────────────────────────────────────────────────\n")

    # ── Bootstrap StudyAgent (same as NightRunner) ────────────────────────────
    from backend.study_agent import StudyAgent
    agent = StudyAgent()

    certified = False
    score = 0.0
    certification_verdict = "UNKNOWN"

    async def on_certify(topic, s, **kw):
        nonlocal certified, score, certification_verdict
        certified = s >= 7.0
        score = s
        certification_verdict = "CERTIFIED" if certified else "FAILED"

    async def on_progress(phase, topic, score, msg="", pct=0):
        # Only print phase transitions, not every progress tick
        if pct in (0, 100) or any(t in (phase or "") for t in
                                   ("SANDBOX", "BENCHMARK", "CERTIFY", "EVALUATE")):
            _orig_print(f"  [{phase}] {pct}% {msg[:80] if msg else ''}")

    _orig_print("[RUN] Starting study_topic()...\n")
    try:
        result = await agent.study_topic(
            topic=TOPIC,
            tier=1,
            on_certify=on_certify,
            on_progress=on_progress,
        )
    except Exception as e:
        _orig_print(f"\n[RUN] Exception during study: {e}")
        import traceback
        traceback.print_exc()
        result = None

    # ── Final report ──────────────────────────────────────────────────────────
    _orig_print(f"\n{'='*70}")
    _orig_print(f"  TICKET #20 VALIDATION REPORT")
    _orig_print(f"{'='*70}")
    _orig_print(f"  Topic:       {TOPIC[:70]}")
    _orig_print(f"  Verdict:     {certification_verdict}")
    _orig_print(f"  Score:       {score:.1f}/10")
    _orig_print(f"  Certified:   {'YES ✓' if certified else 'NO ✗'}")
    if result and isinstance(result, dict):
        bm = result.get("benchmark_result") or {}
        if bm:
            _orig_print(f"  Benchmark:   pass_rate={bm.get('pass_rate', 'N/A')}  "
                        f"passed={bm.get('passed', '?')}/{bm.get('total', '?')}")
    _orig_print(f"{'='*70}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as _top_err:
        import traceback
        _orig_print(f"\n[FATAL] Top-level exception: {_top_err}")
        traceback.print_exc()
        sys.exit(1)
