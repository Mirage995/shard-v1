"""
kaggle_runner.py — Push, poll, and fetch Kaggle kernel runs for SHARD TRACK B experiments.

Uses the new KAGGLE_API_TOKEN env var (token format KGAT_...).
Credentials are loaded from SHARD config or ~/.kaggle/kaggle.json as fallback.
"""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

KAGGLE_TOKEN_ENV = "KAGGLE_API_TOKEN"
PENDING_FILE = Path(__file__).parent.parent / "shard_memory" / "pending_kaggle.json"

# Load .env from project root if token not already in environment
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists() and KAGGLE_TOKEN_ENV not in os.environ:
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        pass
POLL_INTERVAL_SEC = 120   # 2 minutes between status checks
MAX_POLL_HOURS = 3        # give up after 3 hours


def _get_env() -> dict:
    env = os.environ.copy()
    # Load token from shard config if not already set
    if KAGGLE_TOKEN_ENV not in env:
        cfg_path = Path(__file__).parent / "config.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                token = cfg.get("kaggle_api_token") or cfg.get("KAGGLE_API_TOKEN")
                if token:
                    env[KAGGLE_TOKEN_ENV] = token
            except Exception:
                pass
    return env


def push_kernel(code: str, slug: str, title: str, username: str = "andreabonizz") -> str:
    """Push a Python script as a Kaggle kernel. Returns the full kernel ref (username/slug)."""
    env = _get_env()
    if KAGGLE_TOKEN_ENV not in env:
        raise RuntimeError(f"Kaggle token not set. Set {KAGGLE_TOKEN_ENV} env var.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Write the Python script
        script_path = tmp / "experiment.py"
        script_path.write_text(code, encoding="utf-8")

        # Kernel metadata
        meta = {
            "id": f"{username}/{slug}",
            "title": title,
            "code_file": "experiment.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": True,
            "accelerator": "NvidiaTeslaT4",
            "enable_internet": True,
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
        }
        (tmp / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))

        result = subprocess.run(
            ["kaggle", "kernels", "push", "-p", str(tmp)],
            capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            raise RuntimeError(f"kaggle kernels push failed: {result.stderr.strip()}")

    kernel_ref = f"{username}/{slug}"
    print(f"[KAGGLE] Pushed kernel: {kernel_ref}")
    return kernel_ref


def poll_kernel(kernel_ref: str, timeout_hours: float = MAX_POLL_HOURS) -> str:
    """
    Block until the kernel finishes (or times out).
    Returns final status string: 'complete', 'error', 'cancelAcknowledged', or 'timeout'.
    """
    env = _get_env()
    deadline = time.time() + timeout_hours * 3600
    print(f"[KAGGLE] Polling {kernel_ref} (timeout {timeout_hours}h)...")

    while time.time() < deadline:
        result = subprocess.run(
            ["kaggle", "kernels", "status", kernel_ref],
            capture_output=True, text=True, env=env
        )
        output = result.stdout.strip() + result.stderr.strip()
        print(f"[KAGGLE] Status: {output}")

        if "complete" in output.lower():
            return "complete"
        if "error" in output.lower():
            return "error"
        if "cancelacknowledged" in output.lower() or "cancelled" in output.lower():
            return "cancelAcknowledged"

        time.sleep(POLL_INTERVAL_SEC)

    return "timeout"


def fetch_result(kernel_ref: str, out_dir: Optional[str] = None) -> Optional[float]:
    """
    Download kernel output and extract the RESULT: score.
    Returns float score (0.0-1.0) or None if not found.
    """
    env = _get_env()
    with tempfile.TemporaryDirectory() as tmpdir:
        target = out_dir or tmpdir
        result = subprocess.run(
            ["kaggle", "kernels", "output", kernel_ref, "-p", target],
            capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            print(f"[KAGGLE] Output fetch failed: {result.stderr.strip()}")
            return None

        # Search all downloaded files for RESULT: line
        for f in Path(target).rglob("*.txt"):
            text = f.read_text(errors="ignore")
            m = re.search(r"RESULT:\s*([\d.]+)", text)
            if m:
                score = float(m.group(1))
                print(f"[KAGGLE] RESULT found in {f.name}: {score}")
                return score

        print("[KAGGLE] RESULT line not found in output files")
        return None


# ── Pending queue (fire-and-forget pattern) ────────────────────────────────

def queue_pending(kernel_ref: str, hypothesis: dict, slug: str) -> None:
    """Save a pending kernel run to shard_memory for later polling."""
    pending = []
    if PENDING_FILE.exists():
        try:
            pending = json.loads(PENDING_FILE.read_text())
        except Exception:
            pending = []
    pending.append({
        "kernel_ref": kernel_ref,
        "slug": slug,
        "hypothesis_statement": hypothesis.get("statement", ""),
        "domain_from": hypothesis.get("domain_from", ""),
        "domain_to": hypothesis.get("domain_to", ""),
        "queued_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "running",
        "score": None,
    })
    PENDING_FILE.write_text(json.dumps(pending, indent=2))
    print(f"[KAGGLE] Queued in pending_kaggle.json: {kernel_ref}")


def check_pending() -> list:
    """
    Check all pending kernels. Updates their status in pending_kaggle.json.
    Returns list of completed entries with score filled in.
    """
    if not PENDING_FILE.exists():
        return []

    env = _get_env()
    pending = json.loads(PENDING_FILE.read_text())
    completed = []

    for entry in pending:
        if entry["status"] != "running":
            continue

        result = subprocess.run(
            ["kaggle", "kernels", "status", entry["kernel_ref"]],
            capture_output=True, text=True, env=env
        )
        output = (result.stdout + result.stderr).lower()

        if "complete" in output:
            score = fetch_result(entry["kernel_ref"])
            entry["status"] = "complete"
            entry["score"] = score
            entry["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            completed.append(entry)
            print(f"[KAGGLE] {entry['kernel_ref']} complete — score={score}")
        elif "error" in output:
            entry["status"] = "error"
            entry["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    PENDING_FILE.write_text(json.dumps(pending, indent=2))
    return completed


def make_slug(hypothesis: dict) -> str:
    """Generate a short valid Kaggle kernel slug from hypothesis fields."""
    raw = f"shard-{hypothesis.get('domain_from','x')[:12]}-{hypothesis.get('domain_to','y')[:12]}"
    slug = re.sub(r"[^a-z0-9-]", "-", raw.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    # Kaggle slugs max 50 chars, must be unique — append timestamp
    ts = time.strftime("%m%d%H%M")
    return f"{slug[:38]}-{ts}"
