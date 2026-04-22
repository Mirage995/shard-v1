"""
smoke_test_codegen_fix.py — Verify codegen prompt fixes on 3 hypotheses.

Tests:
  H1 (broken_experiment / runtime_error) — should become working after fix
  H2 (weak_signal)                       — should stay runnable, may stay weak
  H3 (strong_signal)                     — control, must stay strong_signal

Usage:
    cd backend
    python ../shard_workspace/experiments/smoke_test_codegen_fix.py
"""

import asyncio
import json
import os
import re
import sys
import time

_root = os.path.dirname(os.path.abspath(__file__)) + "/../.."
_backend = _root + "/backend"
sys.path.insert(0, _root)
sys.path.insert(0, _backend)
os.chdir(_backend)

from study_agent import StudyAgent
from study_utils import ProgressTracker
from sandbox_runner import DockerSandboxRunner

CALIB_LOG = os.path.join(_root, "shard_workspace", "experiments",
                         "alignment_log_20260418_145930.jsonl")
OUTPUT_DIR = os.path.join(_root, "shard_workspace", "experiments")
SANDBOX_DIR = os.path.join(_backend, "sandbox")

SMOKE_INDICES = [0, 1, 2]  # H1, H2, H3 (0-based)


def parse_metric_from_stdout(stdout: str, var_name: str = "V"):
    lines = stdout.strip().splitlines()
    for line in reversed(lines):
        m = re.search(rf'\b{re.escape(var_name)}\s*[=:]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)', line, re.IGNORECASE)
        if m:
            return float(m.group(1)), line.strip()
    for line in reversed(lines):
        m = re.search(r'(?:metric|result|value|score|rate|ratio|accuracy|efficiency|improvement)\s*[=:]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)', line, re.IGNORECASE)
        if m:
            return float(m.group(1)), line.strip()
    for line in reversed(lines):
        m = re.match(r'^\s*([+-]?\d+\.?\d+)\s*$', line.strip())
        if m:
            return float(m.group(1)), line.strip()
    return None, ""


async def run_one(agent, runner, h_record, idx):
    hyp = {
        "statement":          h_record["hypothesis"],
        "domain_from":        h_record["domain_from"],
        "domain_to":          h_record["domain_to"],
        "minimum_experiment": h_record["minimum_experiment"],
        "confidence":         0.8,
        "falsifiable":        True,
    }
    min_exp = hyp["minimum_experiment"]
    var_name = "V"
    mm = re.search(r'MEASUREMENT:.*?Metric:\s*([A-Za-z_][A-Za-z0-9_]*)', min_exp, re.IGNORECASE)
    if mm:
        var_name = mm.group(1)

    print(f"\n{'='*60}")
    print(f"[SMOKE] H{idx+1}: {hyp['statement'][:75]}...")

    t0 = time.time()
    try:
        code = await agent._generate_experiment_code(hyp, kaggle_mode=False)
    except Exception as exc:
        print(f"  CODEGEN FAILED: {exc}")
        return {"h_idx": idx+1, "result": "codegen_error", "error": str(exc)}

    if not code or not code.strip():
        print("  CODEGEN RETURNED EMPTY CODE")
        return {"h_idx": idx+1, "result": "empty_code"}

    print(f"  codegen OK ({len(code)} chars) — first 300:")
    print("  " + code[:300].replace("\n", "\n  "))

    try:
        result = await runner.run(
            topic=f"[smoke H{idx+1}] {hyp['statement'][:40]}",
            code=code,
            progress=ProgressTracker(),
        )
    except Exception as exc:
        print(f"  SANDBOX ERROR: {exc}")
        return {"h_idx": idx+1, "result": "sandbox_error", "error": str(exc)}

    runtime_s = round(time.time() - t0, 1)
    success = result.get("success", False)
    stdout  = result.get("stdout", "")
    stderr  = result.get("stderr", "")

    print(f"  sandbox: {'OK' if success else 'FAIL'} | runtime={runtime_s}s")
    if stdout:
        print(f"  stdout:\n  " + stdout[:600].replace("\n", "\n  "))
    if stderr and not success:
        print(f"  stderr[:300]:\n  " + stderr[:300].replace("\n", "\n  "))

    metric_value, raw_line = parse_metric_from_stdout(stdout, var_name)
    print(f"  parsed: {var_name}={metric_value}  (from: '{raw_line}')")

    signal = "broken_experiment"
    if success and metric_value is not None:
        if abs(metric_value) < 1e-9:
            signal = "no_signal"
        elif metric_value > 0:
            signal = "strong_signal" if metric_value >= 0.5 else "weak_signal"
        else:
            signal = "weak_signal"

    err_type = None
    if not success:
        if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
            err_type = "import_error"
        elif "AssertionError" in stderr:
            err_type = "assertion_error"
        elif "timeout" in stderr.lower():
            err_type = "timeout"
        elif "AttributeError" in stderr or "has no attribute" in stderr:
            err_type = "hallucinated_api"
        elif "operands could not be broadcast" in stderr or "shapes" in stderr.lower():
            err_type = "shape_mismatch"
        else:
            err_type = "runtime_error"

    print(f"  => signal={signal} | error={err_type}")
    return {
        "h_idx":        idx + 1,
        "result":       "success" if success else "failure",
        "signal_class": signal,
        "error_type":   err_type,
        "metric_value": metric_value,
        "runtime_s":    runtime_s,
        "stdout":       stdout[:600],
        "stderr":       stderr[:400] if not success else "",
    }


async def main():
    data = [json.loads(l) for l in open(CALIB_LOG, encoding="utf-8") if l.strip()]

    agent  = StudyAgent()
    runner = DockerSandboxRunner(sandbox_dir=SANDBOX_DIR, analysis_fn=None)

    smoke_records = [data[i] for i in SMOKE_INDICES]
    results = []
    for i, h in zip(SMOKE_INDICES, smoke_records):
        r = await run_one(agent, runner, h, i)
        results.append(r)

    print(f"\n{'='*60}")
    print("[SMOKE TEST] RESULTS")
    labels = {0: "H1 (broken target)", 1: "H2 (weak)", 2: "H3 (control)"}
    ok = True
    for r in results:
        label = labels.get(r["h_idx"]-1, f"H{r['h_idx']}")
        signal = r.get("signal_class", r.get("result", "?"))
        val    = r.get("metric_value", "n/a")
        err    = r.get("error_type", "")
        print(f"  {label:25s} => {signal:20s}  val={val}  {err}")
        if r["h_idx"] == 3 and signal != "strong_signal":
            print("  [REGRESSION] H3 control is no longer strong_signal!")
            ok = False

    print(f"\n  Overall: {'PASS' if ok else 'FAIL — H3 regression detected'}")

    run_id = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_DIR, f"smoke_test_codegen_{run_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "results": results}, f, indent=2, ensure_ascii=False)
    print(f"  Output: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
