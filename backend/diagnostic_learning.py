"""diagnostic_learning.py -- Sole writer of diagnostic weights for SHARD.

Separation of concerns:
  diagnostic_layer.py    -> classifies failure type
  diagnostic_learning.py -> learns which classifiers are effective  <- HERE
  signal_gate.py         -> reads weights + filters signals
  benchmark_loop.py      -> orchestrates, delegates

Update rule (fixed LR, no confidence scaling for now):
  success -> weight += 0.05
  failure -> weight -= 0.03   (softer penalty)
  clamp:    weight in [0.5, 2.0]

One update per run at end-of-run. Duplicates are deduplicated before update.
Atomic write (temp + rename) prevents file corruption.
"""
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("shard.diagnostic_learning")

LR_SUCCESS = 0.05
LR_FAIL    = 0.03
W_MIN, W_MAX   = 0.5, 2.0
DEFAULT_WEIGHT = 1.0

_WEIGHTS_FILE = Path(__file__).resolve().parent.parent / "shard_memory" / "diagnostic_weights.json"


def _load() -> dict:
    """Load weights file, returning empty dict on any error."""
    try:
        if _WEIGHTS_FILE.exists():
            return json.loads(_WEIGHTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[LEARNING] load failed, using defaults: %s", e)
    return {}


def _atomic_write(data: dict) -> None:
    """Write via temp file + rename to prevent corruption."""
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_WEIGHTS_FILE.parent, suffix=".tmp", prefix="diag_w_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, _WEIGHTS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def update_weights(diagnostics_triggered: list[dict], success: bool) -> None:
    """Update per-diagnostic weights based on end-of-run outcome.

    Called ONCE per run after final result is known.

    Args:
        diagnostics_triggered: list of dicts with key "type" (e.g. "DEADLOCK").
            Duplicates are deduplicated -- each type counted once per run.
        success: True if VICTORY, False if FAILED.
    """
    if not diagnostics_triggered:
        return

    # Dedup -- each diagnostic type counts once per run
    seen = {}
    for entry in diagnostics_triggered:
        name = entry.get("type", "").strip().upper()
        if name and name not in seen:
            seen[name] = entry

    data = _load()

    for name in seen:
        if name not in data:
            data[name] = {"weight": DEFAULT_WEIGHT, "success": 0, "fail": 0}

        rec = data[name]
        old_w = rec.get("weight", DEFAULT_WEIGHT)

        if success:
            new_w = round(max(W_MIN, min(W_MAX, old_w + LR_SUCCESS)), 3)
            rec["success"] = rec.get("success", 0) + 1
            outcome_str = "success"
        else:
            new_w = round(max(W_MIN, min(W_MAX, old_w - LR_FAIL)), 3)
            rec["fail"] = rec.get("fail", 0) + 1
            outcome_str = "fail"

        rec["weight"] = new_w

        logger.info(
            "[LEARNING] %s: %.3f -> %.3f (%s) [success=%d fail=%d]",
            name, old_w, new_w, outcome_str, rec["success"], rec["fail"],
        )
        try:
            arrow = "+" if success else "-"
            print(f"  [learning] {name}: {old_w:.3f} {arrow}> {new_w:.3f} ({outcome_str})")
        except Exception:
            pass

    try:
        _atomic_write(data)
    except Exception as e:
        logger.warning("[LEARNING] atomic write failed: %s", e)
