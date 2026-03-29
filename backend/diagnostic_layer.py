"""diagnostic_layer.py — Named failure mode classifier for SHARD.

Takes stuck tests + attempt history + current code → targeted diagnostic hint.

Three classifiers:
  1. IDEMPOTENCY  — test calls function twice, offset applied twice
  2. OSCILLATION  — score alternates A/B, model never combines both fixes
  3. (DEADLOCK handled inline in benchmark_loop.py — timeout + 0/0 tests)
"""
import re


def classify_failure(
    stuck_tests: list,
    attempts: list,      # AttemptRecord objects with .tests_passed / .tests_failed
    current_code: str,
) -> str:
    """Return a named diagnostic hint string, or '' if no pattern matched."""
    hints = []

    h = _check_idempotency(stuck_tests, current_code)
    if h:
        hints.append(h)

    h = _check_oscillation(attempts)
    if h:
        hints.append(h)

    return "\n\n".join(hints)


# ── 1. IDEMPOTENCY ────────────────────────────────────────────────────────────

def _check_idempotency(stuck_tests: list, current_code: str) -> str:
    """Detect: function called twice → transformation applied twice."""
    triggers = [t for t in stuck_tests
                if any(kw in t.lower() for kw in ("idempotent", "twice", "double", "repeat"))]
    if not triggers:
        return ""

    has_offset = bool(re.search(r'offset', current_code, re.IGNORECASE))
    has_guard  = bool(re.search(r'_calibrated|_processed|_applied|already_', current_code))

    hint = (
        "!! IDEMPOTENCY DIAGNOSTIC !!\n"
        f"Stuck test: {', '.join(triggers)}\n"
        "This test calls your function TWICE on the same data.\n"
        "The second call must return the same result as the first.\n"
    )

    if has_offset and not has_guard:
        hint += (
            "\nDETECTED: Your function applies an offset/transformation but has NO guard\n"
            "to prevent applying it a second time.\n"
            "\nREQUIRED FIX — add a '_calibrated' flag:\n"
            "    r = dict(reading)          # copy — never mutate input\n"
            "    if r.get('valid') and sid in config and not r.get('_calibrated'):\n"
            "        r['value'] = round(r['value'] + config[sid]['offset'], 2)\n"
            "        r['_calibrated'] = True   # ← marks as already processed\n"
            "    result.append(r)\n"
            "\nWith this flag: calling the function again on the output is a no-op.\n"
        )
    else:
        hint += (
            "\nREQUIRED: Add a boolean flag to each record (e.g. '_calibrated': True)\n"
            "and skip the transformation if the flag is already set.\n"
        )

    return hint


# ── 2. OSCILLATION ────────────────────────────────────────────────────────────

def _check_oscillation(attempts: list) -> str:
    """Detect: model alternates between two partial solutions, never combines them."""
    if len(attempts) < 4:
        return ""

    scores = [len(a.tests_passed) for a in attempts]
    last   = scores[-4:]
    unique = set(last)

    # Must oscillate: exactly 2 values, alternating A B A B
    if len(unique) != 2:
        return ""
    if not (last[0] == last[2] and last[1] == last[3] and last[0] != last[1]):
        return ""

    score_lo, score_hi = sorted(unique)
    group_lo = next((a for a in reversed(attempts) if len(a.tests_passed) == score_lo), None)
    group_hi = next((a for a in reversed(attempts) if len(a.tests_passed) == score_hi), None)

    fails_lo = set(group_lo.tests_failed) if group_lo else set()
    fails_hi = set(group_hi.tests_failed) if group_hi else set()

    only_in_lo = sorted(fails_lo - fails_hi)[:3]
    only_in_hi = sorted(fails_hi - fails_lo)[:3]

    hint = (
        "!! OSCILLATION DIAGNOSTIC !!\n"
        f"You have been alternating between two partial solutions for {len(attempts)} attempts:\n"
        f"  Solution A ({score_lo} pass): fails {only_in_lo or list(fails_lo)[:3]}\n"
        f"  Solution B ({score_hi} pass): fails {only_in_hi or list(fails_hi)[:3]}\n"
        "\nCRITICAL INSTRUCTION: You must COMBINE both solutions into one.\n"
        "Solution A fixes one set of tests. Solution B fixes a different set.\n"
        "Do NOT pick one or the other. Apply ALL fixes simultaneously in the same code.\n"
        "Review your last two attempts and merge every fix from both into a single solution.\n"
    )
    return hint
