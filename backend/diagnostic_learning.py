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

Rollback gate (#26): before writing new weights, _validate_weight_update() checks:
  - cert_rate has not dropped more than 10% vs previous snapshot
  - no single weight has shifted more than 0.5 in one update
  If either gate fails, old weights are preserved (with rejection metadata).
"""
import copy
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("shard.diagnostic_learning")

LR_SUCCESS = 0.05
LR_FAIL    = 0.03
W_MIN, W_MAX   = 0.5, 2.0
DEFAULT_WEIGHT = 1.0

_WEIGHTS_FILE = Path(__file__).resolve().parent.parent / "shard_memory" / "diagnostic_weights.json"


def _get_current_cert_rate() -> float:
    """Read cert_rate from experiments table. Returns 0.0 on any error."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from shard_db import query
        rows = query("SELECT COUNT(*) AS total, SUM(certified) AS cert FROM experiments")
        if rows:
            total = int(rows[0]["total"] or 0)
            cert  = int(rows[0]["cert"]  or 0)
            return round(cert / total, 4) if total else 0.0
    except Exception as e:
        logger.debug("[LEARNING] cert_rate fetch failed: %s", e)
    return 0.0


def _validate_weight_update(
    old_data: dict, new_data: dict, cert_rate: float
) -> tuple[bool, str]:
    """Rollback gate: returns (True, "") if update is safe, (False, reason) otherwise."""
    # Gate 1: cert_rate must not drop more than 10% vs previous snapshot
    old_cert = old_data.get("_meta", {}).get("cert_rate", cert_rate)
    if old_cert > 0 and cert_rate < old_cert * 0.9:
        return False, f"cert_rate drop {old_cert:.1%} -> {cert_rate:.1%} exceeds 10% threshold"

    # Gate 2: no single weight may shift more than 0.5 in one update
    max_delta = 0.0
    for key in set(old_data.keys()) | set(new_data.keys()):
        if key.startswith("_"):
            continue
        old_w = old_data.get(key, {}).get("weight", DEFAULT_WEIGHT) if isinstance(old_data.get(key), dict) else DEFAULT_WEIGHT
        new_w = new_data.get(key, {}).get("weight", DEFAULT_WEIGHT) if isinstance(new_data.get(key), dict) else DEFAULT_WEIGHT
        delta = abs(new_w - old_w)
        if delta > max_delta:
            max_delta = delta

    if max_delta > 0.5:
        return False, f"max weight delta {max_delta:.3f} exceeds threshold 0.5"

    return True, f"delta_max={max_delta:.3f} cert_rate={cert_rate:.1%}"


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
    old_data = copy.deepcopy(data)

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

    # Rollback gate — validate before committing new weights
    now = datetime.now().isoformat()
    cert_rate = _get_current_cert_rate()
    data["_meta"] = {
        "cert_rate":  cert_rate,
        "updated_at": now,
    }

    ok, detail = _validate_weight_update(old_data, data, cert_rate)
    if not ok:
        logger.warning("[DIAGNOSTIC] Weights REJECTED: %s. Keeping previous.", detail)
        print(f"  [diagnostic] Weights: REJECTED ({detail}). Keeping previous.")
        old_data.setdefault("_meta", {})
        old_data["_meta"]["last_rejected_reason"] = detail
        old_data["_meta"]["last_rejected_at"] = now
        try:
            _atomic_write(old_data)
        except Exception as e:
            logger.warning("[LEARNING] atomic write (reject path) failed: %s", e)
        return

    logger.info("[DIAGNOSTIC] Weights ACCEPTED. %s", detail)
    print(f"  [diagnostic] Weights: ACCEPTED ({detail})")
    try:
        _atomic_write(data)
    except Exception as e:
        logger.warning("[LEARNING] atomic write failed: %s", e)
