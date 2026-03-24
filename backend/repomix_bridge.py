"""
repomix_bridge.py — SHARD integration layer for Repomix.

Packs any GitHub repo (or local path) into a single AI-friendly string
using `npx repomix`, ready to be injected into SHARD's context.
"""

import subprocess
import tempfile
import os
import shutil
from pathlib import Path


class RepomixError(Exception):
    pass


def ingest_repo(url_or_path: str, output_format: str = "xml", timeout: int = 120) -> str:
    """
    Pack a GitHub repo or local path into a single AI-friendly string via Repomix.

    Args:
        url_or_path: GitHub URL (https://github.com/...) or local filesystem path.
        output_format: "xml" | "markdown" | "plain" (default: "xml")
        timeout: Max seconds to wait for repomix (default: 120)

    Returns:
        The packed repo content as a string.

    Raises:
        RepomixError: If npx is not installed, repo not found, or repomix fails.
    """
    # On Windows, npx is npx.cmd — check both
    npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
    if npx_cmd is None:
        raise RepomixError(
            "npx not found. Install Node.js: https://nodejs.org/"
        )

    is_remote = url_or_path.startswith("http://") or url_or_path.startswith("https://")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = os.path.join(tmpdir, "repomix-output.xml")

        cmd = [
            npx_cmd, "--yes", "repomix",
            "--output", output_file,
            "--style", output_format,
        ]

        if is_remote:
            cmd += ["--remote", url_or_path]
        else:
            local_path = Path(url_or_path).resolve()
            if not local_path.exists():
                raise RepomixError(f"Local path not found: {url_or_path}")
            cmd.append(str(local_path))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RepomixError(
                f"Repomix timed out after {timeout}s. Repo too large or network too slow."
            )
        except FileNotFoundError:
            raise RepomixError("npx not found. Install Node.js: https://nodejs.org/")

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RepomixError(f"Repomix failed (exit {result.returncode}): {stderr}")

        if not os.path.exists(output_file):
            raise RepomixError(
                "Repomix ran but produced no output file. "
                f"stdout: {result.stdout[:500]}"
            )

        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
