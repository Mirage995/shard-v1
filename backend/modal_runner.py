"""
modal_runner.py — Run SHARD experiments on Modal GPU infrastructure.

Usage:
    from modal_runner import run_experiment
    score = run_experiment(code, gpu="T4", timeout_min=60)

Requires: modal SDK installed + MODAL_TOKEN_ID / MODAL_TOKEN_SECRET in .env
or authenticated via `modal token new` (interactive, run once manually).
"""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

PENDING_FILE = Path(__file__).parent.parent / "shard_memory" / "pending_modal.json"

_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        pass

GPU_MAP = {
    "T4":      "t4",
    "L4":      "l4",
    "A10":     "a10g",
    "A100-40": "a100-40gb",
    "A100-80": "a100-80gb",
    "H100":    "h100",
}

_RUNNER_TEMPLATE = '''
import modal, sys, re, os

app = modal.App("shard-experiment")
image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "torch", "torchvision", "numpy", "scikit-learn", "scipy", "pandas", "matplotlib"
)

@app.function(gpu="{gpu}", image=image, timeout={timeout_sec})
def run_code():
    import sys, io, contextlib
    code = {code_repr}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<experiment>", "exec"), {{}})
    output = buf.getvalue()
    print(output)
    return output

@app.local_entrypoint()
def main():
    result = run_code.remote()
    print(result)
'''


def run_experiment(
    code: str,
    gpu: str = "T4",
    timeout_min: int = 60,
    label: str = "experiment",
) -> Optional[float]:
    """
    Run experiment code on Modal GPU. Returns RESULT score or None.
    Blocks until completion (or timeout).
    """
    gpu_slug = GPU_MAP.get(gpu, "t4")
    timeout_sec = timeout_min * 60

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Write experiment code
        (tmp / "experiment.py").write_text(code, encoding="utf-8")
        # Save a debug copy so we can inspect what was sent
        debug_path = Path(__file__).parent.parent / "shard_workspace" / "experiments" / f"modal_debug_{label}.py"
        debug_path.write_text(code, encoding="utf-8")
        print(f"[MODAL] Code saved to {debug_path.name}")

        # Write modal app wrapper
        runner = _RUNNER_TEMPLATE.format(
            gpu=gpu_slug,
            timeout_sec=timeout_sec,
            code_repr=repr(code),
        )
        runner_path = tmp / "modal_app.py"
        runner_path.write_text(runner, encoding="utf-8")

        print(f"[MODAL] Running on {gpu} ({gpu_slug}), timeout={timeout_min}min...")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            ["modal", "run", str(runner_path)],
            capture_output=True, env=env, timeout=timeout_sec + 120,
        )
        output = result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")
        safe_output = output.encode("ascii", errors="replace").decode("ascii")
        print(f"[MODAL] Output:\n{safe_output[-3000:]}")

        if result.returncode != 0:
            print(f"[MODAL] Run failed (rc={result.returncode})")
            return None

        m = re.search(r"RESULT:\s*([\d.]+)", output)
        if m:
            score = float(m.group(1))
            print(f"[MODAL] RESULT: {score}")
            return score

        print("[MODAL] RESULT line not found")
        return None


def queue_pending(label: str, hypothesis: dict, gpu: str, score: Optional[float] = None) -> None:
    pending = []
    if PENDING_FILE.exists():
        try:
            pending = json.loads(PENDING_FILE.read_text())
        except Exception:
            pending = []
    pending.append({
        "label": label,
        "hypothesis_statement": hypothesis.get("statement", ""),
        "domain_from": hypothesis.get("domain_from", ""),
        "domain_to": hypothesis.get("domain_to", ""),
        "gpu": gpu,
        "queued_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "complete" if score is not None else "running",
        "score": score,
    })
    PENDING_FILE.write_text(json.dumps(pending, indent=2))
    print(f"[MODAL] Queued: {label} | score={score}")


def run_and_save(code: str, hypothesis: dict, gpu: str = "T4", timeout_min: int = 60) -> Optional[float]:
    """Convenience: run experiment + save result to pending_modal.json."""
    label = f"modal-{hypothesis.get('domain_from','x')[:10]}-{hypothesis.get('domain_to','y')[:10]}-{time.strftime('%m%d%H%M')}"
    score = run_experiment(code, gpu=gpu, timeout_min=timeout_min, label=label)
    queue_pending(label, hypothesis, gpu, score)
    return score
