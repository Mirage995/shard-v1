"""mood_workspace_coupling.py -- GWT Phase 5: Bidirectional Mood Coupling.

Closes the feedback loop:
  Mood → ValenceField → Workspace Arbiter (Phases 1-4)
  Workspace Winner → MoodWorkspaceCoupling → MoodEngine bias (Phase 5)

After each study cycle, the workspace winner is fed back as a decaying
valence bias that nudges the next MoodEngine.compute() call.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# Winner module → (valence_delta, arousal_delta)
# Keys are the module_name values passed to propose_to_workspace() in relational_context().
# Only valence_delta is consumed by MoodEngine (get_bias()), but arousal_delta
# is stored for future extensions (e.g. arousal-threshold coupling).
_WINNER_BIAS: Dict[str, Tuple[float, float]] = {
    "experience":    (+0.10, +0.05),  # "I learned something" → confident
    "identity":      (+0.05, -0.10),  # "I know who I am" → grounded, calm
    "real_identity": (+0.05, -0.10),  # same semantic as identity
    "goal":          (+0.05, +0.15),  # "I have purpose" → motivated
    "desire":        (+0.03, +0.10),  # desire activated → mild uplift
    "tensions":      (-0.05, +0.15),  # D2.1D hypothesis: stress directive -> frustration/urgency
    "knowledge":     (+0.08, +0.05),  # knowledge surfaced → mildly confident
    "strategy":      (+0.08, +0.05),  # strategy recalled → mildly confident
    "world":         ( 0.00, -0.05),  # world model grounding → calming
    "empirical":     (+0.06, +0.03),  # empirical result → slight uplift
}
_IGNITION_FAILURE_BIAS: Tuple[float, float] = (-0.15, +0.10)  # frustrated, anxious


class MoodWorkspaceCoupling:
    """Accumulates workspace winner events as decaying mood biases.

    Usage per cycle (NightRunner):
      1. on_workspace_result(winner, ignition_failed) — after relational_context()
      2. get_bias() → float — passed as workspace_bias to MoodEngine.compute()

    Decay rule: every on_workspace_result() call multiplies existing biases
    by self.decay (0.9) before applying the new event delta. A single event
    has negligible effect after ~10 cycles (0.9^10 ≈ 0.35), preventing
    permanent emotional scarring from isolated incidents.
    """

    def __init__(self, decay: float = 0.9):
        self.decay = decay
        self._valence_bias: float = 0.0
        self._arousal_bias: float = 0.0
        self._last_momentum: str = "neutral"

    # ── Core interface ────────────────────────────────────────────────────────

    def on_workspace_result(
        self,
        winner_module: Optional[str],
        ignition_failed: bool,
    ) -> None:
        """Record a workspace result and update internal biases.

        Args:
            winner_module:  module_name of the workspace winner (or None).
            ignition_failed: True if no proposal passed ignition threshold.
        """
        # Decay first — represents one cycle passing
        self._valence_bias *= self.decay
        self._arousal_bias *= self.decay

        if ignition_failed:
            v_delta, a_delta = _IGNITION_FAILURE_BIAS
        else:
            v_delta, a_delta = _WINNER_BIAS.get(winner_module or "", (0.0, 0.0))

        self._valence_bias += v_delta
        self._arousal_bias += a_delta

        # Hard clamp to avoid runaway accumulation
        self._valence_bias = max(-1.0, min(1.0, self._valence_bias))
        self._arousal_bias = max(-1.0, min(1.0, self._arousal_bias))

        if self._arousal_bias > 0.20:
            self._last_momentum = "active"
        elif self._arousal_bias < -0.20:
            self._last_momentum = "stagnating"
        else:
            self._last_momentum = "neutral"

    @property
    def last_momentum(self) -> str:
        """Current momentum label derived from arousal_bias: 'active' | 'neutral' | 'stagnating'."""
        return self._last_momentum

    def propagate_to_desire(self, topic: str, desire_engine) -> None:
        """Push current valence/arousal biases into DesireEngine for the given topic."""
        desire_engine.apply_workspace_bias(topic, self._valence_bias, self._arousal_bias)

    def get_bias(self) -> float:
        """Return net valence bias for the next MoodEngine.compute() call.

        NOTE -- natural/easy regime:
        workspace_bias may remain 0.0 during easy benchmark runs where topics
        certify without post-failure workspace cycles. This is expected:
        MoodWorkspaceCoupling only accumulates bias after workspace winner
        events are propagated through on_workspace_result(). A zero
        workspace_bias in natural runs is therefore not evidence that the GWT
        layer is broken; it usually means the benchmark did not enter the
        stress/retry regime where the coupling is designed to activate.
        See backend/mood_histogram.py for distribution diagnostics.
        """
        return self._valence_bias

    def get_arousal_bias(self) -> float:
        """Return net arousal bias (for future use / telemetry)."""
        return self._arousal_bias

    def reset(self) -> None:
        """Hard reset — use between sessions if needed."""
        self._valence_bias = 0.0
        self._arousal_bias = 0.0
