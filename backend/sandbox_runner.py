"""sandbox_runner.py -- Hardened Docker sandbox execution for SHARD study experiments.

Extracted from study_agent.py as part of SSJ3 Phase 1: Core Hardening.
"""
import asyncio
import os
import pathlib
import re
import subprocess
import sys
import uuid
from typing import Dict, Optional, Callable

# ── Import name -> pip package name ────────────────────────────────────────────
# Add mappings here when import name differs from pip package name.
_IMPORT_TO_PIP: Dict[str, str] = {
    "bs4":        "beautifulsoup4",
    "sklearn":    "scikit-learn",
    "PIL":        "Pillow",
    "cv2":        "opencv-python-headless",
    "yaml":       "pyyaml",
    "dotenv":     "python-dotenv",
    "dateutil":   "python-dateutil",
    "jwt":        "PyJWT",
    "nacl":       "PyNaCl",
    "Crypto":     "pycryptodome",
    "attr":       "attrs",
    "pkg_resources": "setuptools",
}

# Packages already baked into the base Dockerfile layers -- skip auto-install.
_ALREADY_INSTALLED = frozenset({
    "requests", "beautifulsoup4", "numpy", "pandas", "matplotlib",
    "scikit-learn", "scipy", "flask", "fastapi", "sqlalchemy",
    "torch", "torchvision", "torchaudio",
})

from study_utils import ProgressTracker


class DockerSandboxRunner:
    """Executes LLM-generated code in a hardened Docker container.

    Extracted from StudyAgent to allow isolated testing and reuse.

    Args:
        sandbox_dir: Path to the sandbox directory for temp files.
        analysis_fn: Async callable (prompt: str) -> str for post-exec LLM analysis.
                     If None, analysis is skipped.
    """

    DOCKER_IMAGE = "shard-sandbox:latest"
    MAX_OUTPUT_CHARS = 50_000
    SANDBOX_TIMEOUT = 130

    SANDBOX_REQUIREMENTS = pathlib.Path(__file__).parent / "sandbox_requirements.txt"

    def __init__(self, sandbox_dir: str, analysis_fn: Optional[Callable] = None):
        self.sandbox_dir = sandbox_dir
        self.resolved_sandbox_dir = pathlib.Path(sandbox_dir).resolve()
        self.analysis_fn = analysis_fn
        self._image_checked = False
        self._image_lock = asyncio.Lock()
        self._auto_installed: set = set()  # modules installed this session

    # ── Auto-install: add missing module and rebuild image ────────────────────

    async def _auto_install_module(self, import_name: str) -> bool:
        """Add a missing module to sandbox_requirements.txt and rebuild the image.

        Returns True if rebuild succeeded, False otherwise.
        Only runs once per module per session to avoid rebuild storms.
        """
        if import_name in self._auto_installed:
            return False  # Already attempted this session

        pip_name = _IMPORT_TO_PIP.get(import_name, import_name)

        # Safety: only allow sane package names
        if not re.match(r'^[A-Za-z0-9_\-\.]+$', pip_name):
            print(f"[SANDBOX] [WARN]️ Auto-install rejected unsafe package name: {pip_name!r}")
            return False

        # Skip if already in base image
        if pip_name.lower() in _ALREADY_INSTALLED or import_name.lower() in _ALREADY_INSTALLED:
            print(f"[SANDBOX] ℹ️ '{pip_name}' should already be installed -- skipping auto-install.")
            return False

        print(f"[SANDBOX] 🔧 Auto-installing '{pip_name}' (import: '{import_name}')...")
        self._auto_installed.add(import_name)

        # Append to sandbox_requirements.txt if not already there
        current = self.SANDBOX_REQUIREMENTS.read_text(encoding="utf-8") if self.SANDBOX_REQUIREMENTS.exists() else ""
        if pip_name not in current:
            with self.SANDBOX_REQUIREMENTS.open("a", encoding="utf-8") as f:
                f.write(f"{pip_name}\n")
            print(f"[SANDBOX] ✅ Added '{pip_name}' to sandbox_requirements.txt")

        # Rebuild -- only the dynamic layer invalidates (fast, other layers cached)
        backend_dir = str(pathlib.Path(__file__).parent)
        build_cmd = [
            "docker", "build", "--no-cache=false",
            "-t", self.DOCKER_IMAGE,
            "-f", f"{backend_dir}/Dockerfile.sandbox",
            backend_dir,
        ]
        print(f"[SANDBOX] 🔨 Rebuilding image for '{pip_name}'...")
        try:
            await asyncio.to_thread(subprocess.run, build_cmd, check=True,
                                    capture_output=True)
            self._image_checked = True
            print(f"[SANDBOX] ✅ Image rebuilt with '{pip_name}'. Retrying sandbox...")
            return True
        except subprocess.CalledProcessError as e:
            print(f"[SANDBOX] ❌ Rebuild failed for '{pip_name}': {e}")
            return False

    def _validate_sandbox_path(self, sandbox_dir: str) -> pathlib.Path:
        """Validate and resolve sandbox directory path with security checks.

        Prevents symlink escape and directory traversal attacks.
        Returns the resolved absolute path as a pathlib.Path.
        Raises SecurityError (ValueError) on any violation.
        """
        sandbox_path = pathlib.Path(sandbox_dir).resolve()

        # 1. Must be absolute after resolution
        if not sandbox_path.is_absolute():
            raise ValueError(f"[SANDBOX SECURITY] Path is not absolute: {sandbox_path}")

        # 2. Walk every component -- reject if any segment is a symlink
        check = sandbox_path
        while check != check.parent:  # Walk up to root
            if check.exists() and check.is_symlink():
                raise ValueError(
                    f"[SANDBOX SECURITY] Symlink detected in sandbox path: {check}"
                )
            check = check.parent

        # 3. Verify the resolved path hasn't escaped the expected parent
        #    (prevents crafted paths like sandbox/../../etc)
        #    Uses Path.is_relative_to() -- correct path-aware check, not string startswith.
        expected_parent = self.resolved_sandbox_dir.parent
        try:
            sandbox_path.relative_to(expected_parent)
        except ValueError:
            raise ValueError(
                f"[SANDBOX SECURITY] Path traversal detected: {sandbox_path} "
                f"is outside {expected_parent}"
            )

        return sandbox_path

    def _build_docker_command(self, sandbox_posix: str, filename: str, container_name: str) -> list:
        """Build the hardened Docker run command with all security flags.

        Returns a list of arguments for subprocess.run().
        """
        return [
            "docker", "run",
            "--rm",                                          # Auto-destroy container
            "--network", "none",                              # No network access
            "-m", "256m",                                     # RAM limit
            "--cpus=0.5",                                     # CPU limit
            "--pids-limit", "64",                              # Fork bomb prevention
            "--read-only",                                    # Read-only filesystem
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",      # Controlled temp area
            "--security-opt", "no-new-privileges",            # Block privilege escalation
            "--cap-drop", "ALL",                              # Drop all Linux capabilities
            "--ulimit", "nofile=64:64",                       # File descriptor limit
            "--user", "1000:1000",                            # Non-root execution
            "-v", f"{sandbox_posix}:/app:rw",                 # Mount only sandbox dir
            "-w", "/app",                                     # Working directory
            "--name", container_name,                         # Unique name for kill
            self.DOCKER_IMAGE,                                # Custom hardened image
            "python", filename,                               # Execute the script
        ]

    async def _ensure_sandbox_image(self):
        """Ensure the sandbox docker image exists, building it if necessary. Runs once per session.

        Protected by asyncio.Lock so concurrent study calls never trigger a
        parallel docker build race condition.
        """
        if self._image_checked:
            return

        async with self._image_lock:
            # Re-check inside the lock: another coroutine may have built it while we waited
            if self._image_checked:
                return

            try:
                # Check if image exists
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "image", "inspect", self.DOCKER_IMAGE],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True
                )
                self._image_checked = True
            except subprocess.CalledProcessError:
                print(f"[SANDBOX] 🔨 Docker image '{self.DOCKER_IMAGE}' not found. Building it automatically...")
                build_cmd = [
                    "docker", "build", "-t", self.DOCKER_IMAGE,
                    "-f", "backend/Dockerfile.sandbox", "backend/"
                ]
                try:
                    await asyncio.to_thread(
                        subprocess.run, build_cmd, check=True
                    )
                    print(f"[SANDBOX] ✅ Docker image built successfully.")
                    self._image_checked = True
                except subprocess.CalledProcessError as e:
                    error_msg = f"Failed to automatically build docker image '{self.DOCKER_IMAGE}'."
                    print(f"[SANDBOX] ❌ {error_msg} ({e})")
                    raise RuntimeError(error_msg)

    async def run(self, topic: str, code: str, progress: ProgressTracker = None) -> Dict:
        """Execute LLM-generated code in a hardened Docker container.

        Security layers:
        - Docker container isolation (not host execution)
        - No network, no capabilities, no privilege escalation
        - Read-only filesystem with controlled /tmp
        - Resource limits (RAM, CPU, PIDs, file descriptors)
        - Non-root user (sandbox:1000)
        - Path validation (symlink + traversal prevention)
        - 30s timeout with explicit container kill
        - Output truncation (50k chars)
        """
        print(f"[SANDBOX] Executing code in Docker container for: {topic}")
        if progress:
            progress.set_phase("SANDBOX", 0.0)

        container_name = f"shard-sandbox-{uuid.uuid4().hex[:12]}"
        filename = f"study_{uuid.uuid4().hex[:8]}.py"

        try:
            # ── 1. Verify Docker image exists (once per session) ─────────
            try:
                await self._ensure_sandbox_image()
            except RuntimeError as e:
                error_msg = str(e)
                if progress:
                    progress.complete_phase("SANDBOX")
                return {
                    "success": False, "stdout": "",
                    "stderr": error_msg,
                    "analysis": f"Sandbox unavailable: {error_msg}",
                    "code": code,
                    "file_path": None
                }

            # ── 2. Path security ─────────────────────────────────────────
            sandbox_path = self._validate_sandbox_path(self.sandbox_dir)
            os.makedirs(sandbox_path, exist_ok=True)

            # Convert to POSIX format for Docker mount (Windows compat)
            sandbox_posix = sandbox_path.as_posix()

            # Write code to sandbox directory
            filepath = sandbox_path / filename
            # Verify the resolved file path stays inside sandbox
            resolved_filepath = filepath.resolve()
            if not str(resolved_filepath).startswith(str(sandbox_path)):
                raise ValueError(
                    f"[SANDBOX SECURITY] File path escapes sandbox: {resolved_filepath}"
                )

            # ── Safety filter: block persistent server patterns ──────────
            BANNED_PATTERNS = [
                "serve_forever",
                "HTTPServer(",
                "app.run(",
                "uvicorn.run(",
                "Flask(__name__)",
                ".listen(",
                "while True",
            ]
            for pattern in BANNED_PATTERNS:
                if pattern in code:
                    print(f"[SANDBOX] BLOCKED persistent server pattern: {pattern}")
                    if progress:
                        progress.complete_phase("SANDBOX")
                    return {
                        "success": False,
                        "error": "persistent_server_detected",
                        "pattern": pattern,
                        "file_path": None
                    }

            filepath.write_text(code, encoding="utf-8")
            print(f"[SANDBOX] Code saved to: {filepath}")
            print(f"[SANDBOX] Code ({len(code)} chars):\n{code[:300]}...")
            sys.stdout.flush()

            if progress:
                progress.set_phase("SANDBOX", 0.3)

            # ── 3. Build Docker command ──────────────────────────────────
            docker_cmd = self._build_docker_command(sandbox_posix, filename, container_name)
            print(f"[SANDBOX] Docker command: {' '.join(docker_cmd[:10])}...")

            # ── 4. Execute with timeout ──────────────────────────────────
            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.SANDBOX_TIMEOUT
                )
                stdout = (proc.stdout or "").strip()[:self.MAX_OUTPUT_CHARS]
                stderr = (proc.stderr or "").strip()[:self.MAX_OUTPUT_CHARS]
                success = proc.returncode == 0

                # ── Auto-install missing modules and retry once ───────────────
                if not success:
                    _mod_match = re.search(
                        r"ModuleNotFoundError: No module named '([A-Za-z0-9_]+)'",
                        stderr
                    )
                    if _mod_match:
                        _module = _mod_match.group(1)
                        rebuilt = await self._auto_install_module(_module)
                        if rebuilt:
                            # Retry with the freshly rebuilt image
                            try:
                                proc = await asyncio.to_thread(
                                    subprocess.run,
                                    docker_cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=self.SANDBOX_TIMEOUT
                                )
                                stdout = (proc.stdout or "").strip()[:self.MAX_OUTPUT_CHARS]
                                stderr = (proc.stderr or "").strip()[:self.MAX_OUTPUT_CHARS]
                                success = proc.returncode == 0
                                print(f"[SANDBOX] {'✅' if success else '❌'} Retry after auto-install: rc={proc.returncode}")
                            except Exception as retry_err:
                                print(f"[SANDBOX] [WARN]️ Retry failed: {retry_err}")
                        else:
                            print(f"[SANDBOX] [WARN]️ Missing module '{_module}' -- auto-install unavailable.")

            except subprocess.TimeoutExpired:
                # ── 5. Timeout -> explicit container kill ─────────────────
                print(f"[SANDBOX] [WARN]️ Timeout ({self.SANDBOX_TIMEOUT}s) -- killing container {container_name}")
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "kill", container_name],
                        capture_output=True, timeout=10
                    )
                    print(f"[SANDBOX] Container {container_name} killed successfully")
                except Exception as kill_err:
                    # Kill failure must never crash the agent
                    print(f"[SANDBOX] [WARN]️ docker kill failed (non-fatal): {kill_err}")

                if progress:
                    progress.complete_phase("SANDBOX")
                return {
                    "success": False, "stdout": "",
                    "stderr": f"Timeout ({self.SANDBOX_TIMEOUT}s)",
                    "analysis": f"Code execution exceeded {self.SANDBOX_TIMEOUT}-second timeout",
                    "code": code,
                    "file_path": str(filepath) if 'filepath' in locals() else None
                }

            if progress:
                progress.set_phase("SANDBOX", 0.7)

            print(f"[SANDBOX] {'✅' if success else '❌'} Exit code: {proc.returncode}")
            print(f"[SANDBOX] stdout: {stdout[:300]}")
            if stderr:
                print(f"[SANDBOX] stderr: {stderr[:300]}")

            # ── 6. Cleanup temp file ─────────────────────────────────────
            # (Skipped to allow SWEAgent to patch the file during auto-debug)
            # try:
            #     filepath.unlink(missing_ok=True)
            # except Exception:
            #     pass

            # ── 7. LLM analysis ──────────────────────────────────────────
            analysis_prompt = f"""
Code eseguito per "{topic}":
{code[:1500]}

Risultato:
STDOUT: {stdout[:500] or '(vuoto)'}
STDERR: {stderr[:500] or '(nessuno)'}
Return code: {proc.returncode}

Analizza brevemente: Il codice funziona? Dimostra comprensione reale di {topic}?
"""
            analysis = await self.analysis_fn(analysis_prompt) if self.analysis_fn else "Analysis skipped."

            if progress:
                progress.complete_phase("SANDBOX")
            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "analysis": analysis,
                "code": code,
                "file_path": str(filepath)
            }

        except Exception as e:
            print(f"[SANDBOX] ❌ Exception: {e}")
            import traceback; traceback.print_exc()
            # Cleanup on error
            # try:
            #     sandbox_path_cleanup = pathlib.Path(self.sandbox_dir).resolve() / filename
            #     sandbox_path_cleanup.unlink(missing_ok=True)
            # except Exception:
            #     pass
            if progress:
                progress.complete_phase("SANDBOX")
            return {
                "success": False, "stdout": "",
                "stderr": str(e), "analysis": f"Sandbox error: {e}",
                "code": code,
                "file_path": str(filepath) if 'filepath' in locals() else None
            }
