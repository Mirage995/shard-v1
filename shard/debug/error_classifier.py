"""error_classifier.py -- Stub that delegates to the real classifier in critic_agent.

Loaded by study_phases.py via _load_mod() to classify sandbox stderr.
Previously always returned "generic" — now delegates to _classify_error()
in critic_agent.py which has full regex pattern coverage.
"""
import sys
import os

# Ensure backend is importable when loaded as a dynamic module
_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


class FailureType:
    GENERIC = "generic"


def classify_error(stderr: str) -> str:
    """Classify stderr text into a normalised error label.

    Delegates to critic_agent._classify_error() for full pattern coverage.
    Falls back to 'generic' if import fails.
    """
    try:
        from critic_agent import _classify_error
        label, _ = _classify_error(stderr or "")
        return label
    except Exception:
        return FailureType.GENERIC
