"""
run_sandbox_17.py — Execute all 17 hypotheses from N=17 calibration run in Docker sandbox.

Logs per hypothesis:
  - pass/fail (based on SUCCESS CRITERION)
  - metric_value (V as extracted from stdout)
  - effect_size (metric_value vs baseline_value, relative delta)
  - runtime_s
  - error_type (if failed)
  - signal_class: strong_signal | weak_signal | no_signal | broken_experiment

Aggregate metrics:
  - EXPERIMENT_SUCCESS_RATE (% producing significant signal)
  - EFFECT_SIZE_DISTRIBUTION (per-hypothesis effect sizes)

Output: shard_workspace/experiments/sandbox_run_17_<timestamp>.json

Usage:
    cd backend
    python ../shard_workspace/experiments/run_sandbox_17.py
"""

import asyncio
import json
import os
import re
import sys
import time

_root = os.path.dirname(os.path.abspath(__file__)) + "/../.."
_backend = _root + "/backend"
sys.path.insert(0, _backend)
sys.path.insert(0, _root)
os.chdir(_backend)

from study_agent import StudyAgent
from study_utils import ProgressTracker
from sandbox_runner import DockerSandboxRunner

CALIB_LOG = os.path.join(_root, "shard_workspace", "experiments",
                         "alignment_log_20260418_145930.jsonl")
OUTPUT_DIR = os.path.join(_root, "shard_workspace", "experiments")
SANDBOX_DIR = os.path.join(_backend, "sandbox")


def parse_success_criterion(min_exp: str):
    """Extract numeric threshold from SUCCESS CRITERION line."""
    m = re.search(r'SUCCESS CRITERION:\s*(.+)', min_exp, re.IGNORECASE)
    if not m:
        return None, None
    sc = m.group(1).strip()
    # Try to extract: "exceeds baseline by > X%" or "> X" or ">= X" patterns
    pct = re.search(r'>\s*(\d+\.?\d*)\s*%', sc)
    if pct:
        return float(pct.group(1)) / 100.0, "pct_delta"
    abs_thresh = re.search(r'[>≥]=?\s*(\d+\.?\d*)', sc)
    if abs_thresh:
        return float(abs_thresh.group(1)), "abs"
    return None, None


def parse_metric_from_stdout(stdout: str, var_name: str = "V"):
    """
    Extract numeric metric value from sandbox stdout.
    Looks for patterns like:
      V = 0.823
      metric_value: 0.823
      result: 0.823
      0.823  (last float on a line)
    Returns (value: float | None, raw_line: str)
    """
    lines = stdout.strip().splitlines()

    # Priority 1: explicit variable assignment print
    for line in reversed(lines):
        m = re.search(rf'\b{re.escape(var_name)}\s*[=:]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)', line, re.IGNORECASE)
        if m:
            return float(m.group(1)), line.strip()

    # Priority 2: key=value patterns
    for line in reversed(lines):
        m = re.search(r'(?:metric|result|value|score|rate|ratio|accuracy|efficiency|improvement)\s*[=:]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)', line, re.IGNORECASE)
        if m:
            return float(m.group(1)), line.strip()

    # Priority 3: last numeric line
    for line in reversed(lines):
        m = re.match(r'^\s*([+-]?\d+\.?\d+)\s*$', line.strip())
        if m:
            return float(m.group(1)), line.strip()

    return None, ""


def classify_signal(metric_value, threshold, threshold_type, pass_flag):
    """
    strong_signal:    passes criterion with margin >= 20% of threshold
    weak_signal:      passes criterion but barely (< 20% margin) OR metric computable but fails
    no_signal:        metric is 0 or near 0
    broken_experiment: metric not parseable
    """
    if metric_value is None:
        return "broken_experiment"
    if abs(metric_value) < 1e-9:
        return "no_signal"
    if not pass_flag:
        return "weak_signal"  # metric computable but below threshold
    if threshold is not None and threshold > 0:
        if threshold_type == "pct_delta":
            margin = (metric_value - threshold) / threshold if threshold > 0 else 0
        else:
            margin = (metric_value - threshold) / threshold if threshold > 0 else 0
        return "strong_signal" if margin >= 0.2 else "weak_signal"
    return "weak_signal"  # passes but no threshold to compute margin


def compute_effect_size(metric_value, baseline_value, threshold, threshold_type):
    """Relative delta from baseline or threshold."""
    if metric_value is None:
        return None
    ref = baseline_value if baseline_value is not None else threshold
    if ref is None or ref == 0:
        return None
    return round((metric_value - ref) / abs(ref), 3)


async def run_one(agent: StudyAgent, runner: DockerSandboxRunner,
                  hypothesis_record: dict, idx: int) -> dict:
    hyp = {
        "statement":          hypothesis_record["hypothesis"],
        "domain_from":        hypothesis_record["domain_from"],
        "domain_to":          hypothesis_record["domain_to"],
        "minimum_experiment": hypothesis_record["minimum_experiment"],
        "confidence":         0.8,
        "falsifiable":        True,
    }
    min_exp = hyp["minimum_experiment"]

    # Extract V name from MEASUREMENT section
    var_name = "V"
    vm = re.search(r'VARIABLE:\s*([A-Za-z_][A-Za-z0-9_]*)\s*=', min_exp)
    if vm:
        var_name = vm.group(1)
    mm = re.search(r'MEASUREMENT:.*?Metric:\s*([A-Za-z_][A-Za-z0-9_]*)', min_exp, re.IGNORECASE)
    if mm:
        var_name = mm.group(1)

    threshold, threshold_type = parse_success_criterion(min_exp)

    print(f"\n{'='*60}")
    print(f"[RUN] H{idx+1}/17: {hyp['statement'][:70]}...")
    print(f"  domain: {hyp['domain_from']} → {hyp['domain_to']}")
    print(f"  var={var_name} | threshold={threshold} ({threshold_type})")

    # Generate experiment code
    t0 = time.time()
    try:
        code = await agent._generate_experiment_code(hyp, kaggle_mode=False)
        if not code or not code.strip():
            return {
                "h_idx": idx + 1,
                "hypothesis": hyp["statement"][:100],
                "domain": f"{hyp['domain_from']} → {hyp['domain_to']}",
                "signal_class": "broken_experiment",
                "error_type": "empty_code",
                "pass": False,
                "metric_value": None,
                "effect_size": None,
                "runtime_s": round(time.time() - t0, 1),
            }
    except Exception as exc:
        return {
            "h_idx": idx + 1,
            "hypothesis": hyp["statement"][:100],
            "domain": f"{hyp['domain_from']} → {hyp['domain_to']}",
            "signal_class": "broken_experiment",
            "error_type": f"codegen_error: {exc}",
            "pass": False,
            "metric_value": None,
            "effect_size": None,
            "runtime_s": round(time.time() - t0, 1),
        }

    # Run in sandbox
    try:
        result = await runner.run(
            topic=f"[H{idx+1}] {hyp['statement'][:50]}",
            code=code,
            progress=ProgressTracker(),
        )
        runtime_s = round(time.time() - t0, 1)
        success = result.get("success", False)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")

        print(f"  sandbox: {'OK' if success else 'FAIL'} | runtime={runtime_s}s")
        print(f"  stdout[:200]: {stdout[:200]}")
        if stderr and not success:
            print(f"  stderr[:150]: {stderr[:150]}")

    except Exception as exc:
        return {
            "h_idx": idx + 1,
            "hypothesis": hyp["statement"][:100],
            "domain": f"{hyp['domain_from']} → {hyp['domain_to']}",
            "signal_class": "broken_experiment",
            "error_type": f"sandbox_error: {exc}",
            "pass": False,
            "metric_value": None,
            "effect_size": None,
            "runtime_s": round(time.time() - t0, 1),
        }

    if not success:
        # Try to classify error type
        err_type = "runtime_error"
        if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
            err_type = "import_error"
        elif "AssertionError" in stderr:
            err_type = "assertion_error"
        elif "TimeoutError" in stderr or "timeout" in stderr.lower():
            err_type = "timeout"
        elif "MemoryError" in stderr:
            err_type = "memory_error"
        elif stderr.strip() == "" and stdout.strip() == "":
            err_type = "no_output"
        return {
            "h_idx": idx + 1,
            "hypothesis": hyp["statement"][:100],
            "domain": f"{hyp['domain_from']} → {hyp['domain_to']}",
            "signal_class": "broken_experiment",
            "error_type": err_type,
            "pass": False,
            "metric_value": None,
            "effect_size": None,
            "runtime_s": runtime_s,
            "stdout": stdout[:500],
            "stderr": stderr[:500],
        }

    # Parse metric from stdout
    metric_value, raw_line = parse_metric_from_stdout(stdout, var_name)
    print(f"  parsed: {var_name}={metric_value} (from: '{raw_line}')")

    # Determine pass/fail against SUCCESS CRITERION
    pass_flag = False
    if metric_value is not None and threshold is not None:
        if threshold_type == "pct_delta":
            pass_flag = metric_value >= threshold
        else:
            pass_flag = metric_value >= threshold
    elif metric_value is not None:
        pass_flag = metric_value > 0  # no threshold → any positive signal counts

    signal_class = classify_signal(metric_value, threshold, threshold_type, pass_flag)
    effect_size = compute_effect_size(metric_value, None, threshold, threshold_type)

    print(f"  signal={signal_class} | pass={pass_flag} | effect_size={effect_size}")

    return {
        "h_idx":       idx + 1,
        "hypothesis":  hyp["statement"][:100],
        "domain":      f"{hyp['domain_from']} → {hyp['domain_to']}",
        "signal_class": signal_class,
        "error_type":  None,
        "pass":        pass_flag,
        "metric_value": metric_value,
        "metric_raw_line": raw_line,
        "threshold":   threshold,
        "threshold_type": threshold_type,
        "effect_size": effect_size,
        "runtime_s":   runtime_s,
        "stdout":      stdout[:800],
    }


async def main():
    print("[RUN_17] Loading hypotheses from calibration log...")
    data = [json.loads(l) for l in
            open(CALIB_LOG, encoding="utf-8") if l.strip()]
    print(f"[RUN_17] {len(data)} hypotheses loaded")

    agent  = StudyAgent()
    runner = DockerSandboxRunner(sandbox_dir=SANDBOX_DIR, analysis_fn=None)

    results = []
    for i, h in enumerate(data):
        if not h.get("minimum_experiment"):
            print(f"[RUN_17] H{i+1}: SKIP — no minimum_experiment in log")
            results.append({
                "h_idx": i+1, "hypothesis": h["hypothesis"][:100],
                "signal_class": "broken_experiment",
                "error_type": "no_min_exp_in_log",
                "pass": False, "metric_value": None, "effect_size": None,
            })
            continue
        r = await run_one(agent, runner, h, i)
        results.append(r)

    # ── Aggregate metrics ──────────────────────────────────────────────────────
    n = len(results)
    n_strong = sum(1 for r in results if r["signal_class"] == "strong_signal")
    n_weak   = sum(1 for r in results if r["signal_class"] == "weak_signal")
    n_none   = sum(1 for r in results if r["signal_class"] == "no_signal")
    n_broken = sum(1 for r in results if r["signal_class"] == "broken_experiment")
    n_pass   = sum(1 for r in results if r.get("pass"))

    experiment_success_rate = round((n_strong + n_weak) / n * 100, 1) if n else 0

    effect_sizes = [r["effect_size"] for r in results
                    if r["effect_size"] is not None]
    effect_size_distribution = {
        "n": len(effect_sizes),
        "values": effect_sizes,
        "mean": round(sum(effect_sizes) / len(effect_sizes), 3) if effect_sizes else None,
        "max": round(max(effect_sizes), 3) if effect_sizes else None,
        "min": round(min(effect_sizes), 3) if effect_sizes else None,
    }

    print(f"\n{'='*60}")
    print("[RUN_17] SUMMARY")
    print(f"  N={n} | PASS={n_pass} | strong={n_strong} | weak={n_weak} | no_signal={n_none} | broken={n_broken}")
    print(f"  EXPERIMENT_SUCCESS_RATE = {experiment_success_rate}%")
    if effect_sizes:
        print(f"  EFFECT_SIZE mean={effect_size_distribution['mean']} max={effect_size_distribution['max']} min={effect_size_distribution['min']}")

    # Signal classification table
    print(f"\n  {'H':>3} {'Signal':>18} {'Value':>8} {'EffSz':>7}  Domain")
    for r in results:
        print(f"  H{r['h_idx']:<2} {r['signal_class']:>18} {str(r.get('metric_value') or 'n/a'):>8} "
              f"{str(r.get('effect_size') or 'n/a'):>7}  {r.get('domain','')[:45]}")

    # Save
    run_id = time.strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"sandbox_run_17_{run_id}.json")
    output = {
        "run_id": run_id,
        "calib_log": CALIB_LOG,
        "n_hypotheses": n,
        "aggregate": {
            "EXPERIMENT_SUCCESS_RATE_pct": experiment_success_rate,
            "n_strong_signal": n_strong,
            "n_weak_signal":   n_weak,
            "n_no_signal":     n_none,
            "n_broken":        n_broken,
            "n_pass":          n_pass,
            "EFFECT_SIZE_DISTRIBUTION": effect_size_distribution,
        },
        "results": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n[RUN_17] Output: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
