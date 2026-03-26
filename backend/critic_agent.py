import re
from typing import Optional


# ── Error pattern → remediation topic mapping ─────────────────────────────────
# Each entry: (regex_on_stderr, error_label, remediation_topic_template)
# {capability} is replaced with the failing topic name at runtime.

_ERROR_PATTERNS = [
    # NumPy shape / broadcasting
    (r"non-broadcastable|broadcast shape|could not broadcast|shape mismatch",
     "numpy_broadcast_error",
     "numpy array broadcasting rules and shape manipulation"),

    (r"IndexError.*tuple index out of range|IndexError.*list index out of range",
     "index_error_dimensions",
     "python array dimensionality and index bounds"),

    # General numpy shape
    (r"operands could not be broadcast|shapes.*cannot be broadcast",
     "numpy_shape_mismatch",
     "numpy array shapes and matrix operations"),

    # Type errors
    (r"TypeError.*unsupported operand|TypeError.*can only|TypeError.*must be",
     "type_error",
     "python type coercion and operator overloading"),

    (r"TypeError.*object is not (callable|iterable|subscriptable)",
     "type_error_callable",
     "python object model and callable interfaces"),

    # Attribute errors
    (r"AttributeError.*has no attribute",
     "attribute_error",
     "python object attributes and method resolution"),

    # Import errors
    (r"ImportError|ModuleNotFoundError",
     "import_error",
     "python module system and dependency management"),

    # Division / math
    (r"ZeroDivisionError",
     "zero_division",
     "python defensive arithmetic and numerical stability"),

    # Recursion
    (r"RecursionError|maximum recursion depth",
     "recursion_error",
     "python recursion limits and iterative alternatives"),

    # Memory
    (r"MemoryError|cannot allocate|out of memory",
     "memory_error",
     "python memory management and efficient data structures"),

    # Timeout (custom sandbox signal)
    (r"TimeoutExpired|sandbox.*timeout|timed out",
     "timeout",
     "python algorithm complexity and time-efficient implementations"),

    # Value errors (generic)
    (r"ValueError",
     "value_error",
     "python input validation and defensive programming"),

    # Syntax
    (r"SyntaxError|IndentationError",
     "syntax_error",
     "python syntax rules and code structure"),
]


def _classify_error(stderr: str) -> tuple[str, Optional[str]]:
    """Return (error_label, remediation_topic) from stderr text."""
    if not stderr:
        return "unknown", None
    for pattern, label, remedy in _ERROR_PATTERNS:
        if re.search(pattern, stderr, re.IGNORECASE):
            return label, remedy
    # Fallback: extract the exception class from the last traceback line
    match = re.search(r"^(\w+Error|\w+Exception)[:.]", stderr, re.MULTILINE)
    if match:
        exc_name = match.group(1)
        return exc_name.lower(), f"python {exc_name} handling and prevention"
    return "generic_error", None


def _extract_error_line(stderr: str) -> str:
    """Extract the last meaningful line from a traceback."""
    lines = [l.strip() for l in stderr.splitlines() if l.strip()]
    # Last non-empty line is usually the error message
    return lines[-1] if lines else "unknown error"


class CriticAgent:
    """
    Analyzes sandbox and benchmark failures.

    Two modes:
    - analyze_failure(): fast regex-based, synchronous, for immediate feedback
    - analyze_with_llm(): LLM-powered meta-critique, async, for stuck topics
      Reads episodic history and asks: "what is SHARD doing wrong systematically?"
    """

    def __init__(self, capability_graph=None, strategy_memory=None):
        self.capability_graph = capability_graph
        self.strategy_memory = strategy_memory

    def analyze_failure(self, data: dict) -> dict:
        """
        Analyze a sandbox failure.

        Input keys: stderr, stdout, failure_type, capability
        Returns: analysis, error_type, error_summary, remediation_topic, confidence
        """
        stderr = data.get("stderr", "")
        capability = data.get("capability", "unknown topic")
        failure_type = data.get("failure_type", "generic")

        error_type, remediation_topic = _classify_error(stderr)
        error_summary = _extract_error_line(stderr)

        # Confidence: high if we matched a specific pattern, low for generic
        confidence = 0.85 if error_type not in ("unknown", "generic_error") else 0.4

        # If no specific remedy found, suggest revisiting the base topic
        if not remediation_topic:
            remediation_topic = f"fundamentals of {capability}"

        analysis_text = (
            f"Sandbox failure on '{capability}'. "
            f"Error type: {error_type}. "
            f"Error: {error_summary}. "
            f"Suggested remediation: study '{remediation_topic}'."
        )

        print(f"[CRITIC] {analysis_text}")

        return {
            "analysis": analysis_text,
            "error_type": error_type,
            "error_summary": error_summary,
            "remediation_topic": remediation_topic,
            "confidence": confidence,
            "capability": capability,
            "data": data,
        }

    async def analyze_with_llm(self, topic: str, current_score: float,
                                current_gaps: list, attempt: int,
                                identity_context: dict = None) -> str:
        """
        LLM-powered meta-critique for stuck topics.

        Called when attempt >= 2 — SHARD is not converging.
        Reads episodic history for this topic and asks Gemini:
        "What is SHARD doing wrong systematically? What should it try differently?"

        Vettore 2: if identity_context shows a critical gap in this category,
        CriticAgent becomes a skeptical examiner — suspects luck or flawed tests,
        not genuine mastery.

        Returns a critique string ready to inject into the retry prompt.
        Returns empty string on any error (non-fatal).
        """
        try:
            from llm_router import llm_complete
            from episodic_memory import get_episodic_memory

            # Load past episodes for this topic
            memory = get_episodic_memory()
            episodes = memory.retrieve_context(topic, k=5)

            history_lines = []
            for ep in episodes:
                score = ep.get("score", 0)
                success = ep.get("success", False)
                reason = ep.get("failure_reason", "")
                date = ep.get("timestamp", "")[:10]
                status = "CERTIFIED" if success else f"FAILED (score {score})"
                line = f"- {date}: {status}"
                if reason:
                    line += f" — reason: {reason}"
                history_lines.append(line)

            history_text = "\n".join(history_lines) if history_lines else "No prior history."

            gaps_text = ", ".join(str(g) for g in current_gaps[:5]) if current_gaps else "none identified"

            # Vettore 2 — Identity context: skeptical mode if critical gap
            identity_block = ""
            skeptical_mode = False
            if identity_context and "error" not in identity_context:
                gap_severity  = identity_context.get("gap_severity", "none")
                cert_rate     = identity_context.get("certification_rate", 1.0)
                critical_gaps = identity_context.get("critical_gaps", [])
                frustration   = identity_context.get("frustration_hits", 0)
                if gap_severity in ("critical", "medium") or cert_rate < 0.4:
                    skeptical_mode = True
                    identity_block = (
                        f"\nIDENTITY CHECK (from SelfModel):\n"
                        f"  Overall cert_rate={cert_rate:.0%} | gap_severity={gap_severity} | "
                        f"critical_categories={critical_gaps[:3]}\n"
                        f"  SHARD has a documented weakness in this area. "
                        f"Be extra skeptical — past 'passes' in weak categories are often luck or poorly written tests, not genuine mastery.\n"
                    )
                if frustration >= 2:
                    identity_block += (
                        f"  FRUSTRATION: {frustration} session(s) failed on this topic across history — "
                        f"this is a persistent block, not a one-off. "
                        f"Diagnose the *pattern*, not just the last error.\n"
                    )

            prompt = f"""You are SHARD's critical self-evaluator. Your job is to identify *systematic* mistakes in SHARD's learning approach — not just what went wrong, but WHY the current strategy keeps failing.
{identity_block}
Topic: "{topic}"
Current attempt: {attempt}
Current score: {current_score}/10
Current gaps identified: {gaps_text}

Past study history for this topic:
{history_text}

Analyze this pattern critically:
1. What is SHARD consistently getting wrong across attempts?
2. Is the approach to this topic fundamentally flawed (e.g. too abstract, wrong implementation focus, missing prerequisite)?
3. What ONE specific change in approach would most likely break the failure pattern?
{"4. Given the identity weakness above — is SHARD's self-assessment accurate, or is it overconfident in a weak area?" if skeptical_mode else ""}

Be direct and concrete. Output 3-4 sentences maximum. This will be injected directly into the next attempt prompt."""

            critique = await llm_complete(
                prompt=prompt,
                system=(
                    "You are a sharp, skeptical examiner. No flattery. "
                    "Identify the root cause of repeated failure. "
                    + ("The student has documented weaknesses here — be rigorous." if skeptical_mode else "")
                ),
                max_tokens=300,
                temperature=0.4,
                providers=["Gemini", "Groq", "Claude"],
            )

            mode_tag = "[SKEPTICAL]" if skeptical_mode else ""
            print(f"[CRITIC-LLM]{mode_tag} Meta-critique for '{topic}' (attempt {attempt}): {critique[:120]}...")
            return critique.strip()

        except Exception as e:
            print(f"[CRITIC-LLM] Non-fatal error: {e}")
            return ""
