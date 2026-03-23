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
    Analyzes sandbox failures and produces structured feedback with a
    remediation topic that can be injected into the research agenda.
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
