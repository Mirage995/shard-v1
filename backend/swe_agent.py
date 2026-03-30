"""SWE Agent -- LLM-driven autonomous code repair with mandatory security validation.

Provider chain for repairs: Claude -> Groq LLaMA-70B -> Ollama (local).
Every patch MUST pass the AST security gate before touching disk.
Git integration: commits on success, rolls back on failure.
"""
import ast
import asyncio
import dataclasses
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("shard.swe_agent")

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

PYTEST_TIMEOUT_SECONDS = 60
MAX_REPAIR_ATTEMPTS = 3

# ── Security: heavy gate (sandbox / untrusted code) ────────────────────────────
FORBIDDEN_IMPORTS: frozenset[str] = frozenset({
    # OS / process control
    "os", "sys", "subprocess", "shutil", "signal", "resource", "fcntl",
    # Networking
    "socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp",
    "ftplib", "smtplib", "telnetlib", "xmlrpc",
    # Dangerous serialization / IPC
    "pickle", "marshal", "shelve", "mmap",
    # Reflection / dynamic loading
    "ctypes", "cffi", "importlib", "types", "gc",
    # Execution engines
    "code", "codeop", "compileall", "py_compile",
    # Parallel / inter-process
    "multiprocessing", "concurrent",
    # Terminal / PTY
    "pty", "tty", "termios",
    # Built-ins escape hatch
    "builtins",
    # Archive / filesystem ops
    "zipfile", "tarfile", "gzip", "bz2", "lzma",
    # Obfuscation
    "base64", "codecs",
})

FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "eval",        # arbitrary expression execution
    "exec",        # arbitrary statement execution
    "compile",     # produces code objects -> eval/exec bypass
    "__import__",  # dynamic import without 'import' statement
    "globals",     # full namespace exposure
    "locals",      # full namespace exposure
    "vars",        # full namespace exposure
    "breakpoint",  # drops into debugger -> interactive shell
    "memoryview",  # raw memory access
})

# ── Security: light gate (backend repair patches -- our own code) ───────────────
# Only blocks newly introduced eval/exec/compile -- doesn't restrict imports
# because backend code legitimately uses os, subprocess, etc.
PATCH_FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__",
})


# ── AST visitors ───────────────────────────────────────────────────────────────

class _SecurityVisitor(ast.NodeVisitor):
    """Heavy AST gate -- for untrusted/sandbox code."""

    def __init__(self):
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base in FORBIDDEN_IMPORTS:
                self.violations.append(
                    f"[line {node.lineno}] Forbidden import: '{alias.name}'"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            base = node.module.split(".")[0]
            if base in FORBIDDEN_IMPORTS:
                self.violations.append(
                    f"[line {node.lineno}] Forbidden from-import: 'from {node.module} import ...'"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                self.violations.append(
                    f"[line {node.lineno}] Forbidden call: '{node.func.id}()'"
                )
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in FORBIDDEN_CALLS:
                self.violations.append(
                    f"[line {node.lineno}] Forbidden attribute call: '.{node.func.attr}()'"
                )
        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if node.args and isinstance(node.args[-1], ast.Constant):
                if node.args[-1].value in FORBIDDEN_CALLS | FORBIDDEN_IMPORTS:
                    self.violations.append(
                        f"[line {node.lineno}] Forbidden dynamic getattr: "
                        f"getattr(..., '{node.args[-1].value}')"
                    )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        DANGEROUS_DUNDER = {
            "__class__", "__bases__", "__subclasses__", "__globals__",
            "__builtins__", "__code__", "__closure__",
        }
        if node.attr in DANGEROUS_DUNDER:
            self.violations.append(
                f"[line {node.lineno}] Suspicious dunder attribute access: '.{node.attr}'"
            )
        self.generic_visit(node)


class _PatchSecurityVisitor(ast.NodeVisitor):
    """Light AST gate -- for backend repair patches (our own code)."""

    def __init__(self):
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in PATCH_FORBIDDEN_CALLS:
            self.violations.append(
                f"[line {node.lineno}] Forbidden call in patch: '{node.func.id}()'"
            )
        self.generic_visit(node)


# ── Public security functions ──────────────────────────────────────────────────

def validate_code_safety(code: str) -> tuple[bool, list[str]]:
    """Heavy AST gate -- use for sandbox/untrusted code (student programs, experiments)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError at line {e.lineno}: {e.msg}"]
    visitor = _SecurityVisitor()
    visitor.visit(tree)
    return len(visitor.violations) == 0, visitor.violations


def validate_patch_safety(code: str) -> tuple[bool, list[str]]:
    """Light AST gate -- use for backend repair patches (our own code)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError at line {e.lineno}: {e.msg}"]
    visitor = _PatchSecurityVisitor()
    visitor.visit(tree)
    return len(visitor.violations) == 0, visitor.violations


# ── RepairResult ───────────────────────────────────────────────────────────────

@dataclasses.dataclass
class RepairResult:
    success: bool
    filepath: str
    patch_code: str = ""
    test_output: str = ""
    commit_hash: str = ""
    error: str = ""
    attempts: int = 0


# ── SWEAgent ───────────────────────────────────────────────────────────────────

class SWEAgent:
    """LLM-driven autonomous file repair agent.

    Main entrypoint: repair_backend_file()

    Repair flow (up to MAX_REPAIR_ATTEMPTS times):
      1. Read the file
      2. Build a repair prompt (file content + issue + error context + prev failure)
      3. Call LLM via llm_router (Claude -> Groq -> Ollama)
      4. Extract clean Python code from LLM response
      5. Validate patch safety (light AST gate -- blocks eval/exec only)
      6. Write patch atomically (tempfile + os.replace)
      7. Discover and run tests
      8. On pass  -> git commit, return RepairResult(success=True)
         On fail  -> git reset file, feed failure back into prompt, retry
    """

    def __init__(self, workspace_dir: str = "shard_workspace"):
        self.workspace_dir = Path(workspace_dir)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def repair_backend_file(
        self,
        filepath: str,
        issue_text: str,
        error_context: str = "",
        require_tests: bool = True,
    ) -> RepairResult:
        """Repair a backend file using the LLM, with git integration.

        Args:
            filepath: Absolute or repo-relative path to the Python file to repair.
            issue_text: Human-readable description of the bug / required fix.
            error_context: Traceback or test output that triggered this repair.
            require_tests: If True, tests must pass before the patch is committed.

        Returns:
            RepairResult with success, patch code, test output, and commit hash.
        """
        path = Path(filepath)
        if not path.is_absolute():
            path = REPO_ROOT / path

        # Safety: only operate inside the repo
        try:
            path.relative_to(REPO_ROOT)
        except ValueError:
            return RepairResult(
                success=False,
                filepath=str(path),
                error=f"[SWE] Path '{path}' is outside the repo root. Aborting.",
            )

        if not path.exists():
            return RepairResult(
                success=False,
                filepath=str(path),
                error=f"[SWE] File not found: {path}",
            )

        logger.info("[SWE] Starting repair: %s | issue: %.80s", path.name, issue_text)

        try:
            original_code = path.read_text(encoding="utf-8")
        except OSError as e:
            return RepairResult(success=False, filepath=str(path), error=f"Cannot read file: {e}")

        test_paths = self._discover_tests(path)
        previous_failure: Optional[str] = None

        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            logger.info("[SWE] Attempt %d/%d for %s", attempt, MAX_REPAIR_ATTEMPTS, path.name)

            # 1. Build prompt
            prompt = self._build_repair_prompt(
                filepath=path,
                code=original_code,
                issue_text=issue_text,
                error_context=error_context,
                previous_failure=previous_failure,
                attempt=attempt,
            )

            # 2. Generate patch via LLM
            try:
                raw_response = await self._generate_patch(prompt)
            except RuntimeError as e:
                return RepairResult(
                    success=False, filepath=str(path),
                    error=f"LLM unavailable: {e}", attempts=attempt,
                )

            # 3. Extract clean code from LLM response
            patch_code = self._extract_code(raw_response, original_code)

            # 4. Light security gate -- block eval/exec insertion
            ok, violations = validate_patch_safety(patch_code)
            if not ok:
                previous_failure = "SECURITY: " + "; ".join(violations)
                logger.warning("[SWE] Attempt %d rejected by security gate: %s", attempt, previous_failure)
                continue

            # 5. Write patch atomically
            write_ok, write_err = await self._apply_patch(path, patch_code)
            if not write_ok:
                return RepairResult(
                    success=False, filepath=str(path),
                    patch_code=patch_code, error=write_err, attempts=attempt,
                )

            # 6. Run tests
            if test_paths and require_tests:
                test_output, tests_passed = await self._run_tests(test_paths)
            else:
                test_output, tests_passed = "(no tests found -- patch written without test gate)", True

            if tests_passed:
                # 7. Commit
                commit_msg = f"fix({path.name}): autonomous repair -- {issue_text[:60]}"
                commit_ok, commit_hash = await self._git_commit(path, commit_msg)
                logger.info("[SWE] OK Repair committed: %s (%s)", path.name, commit_hash)
                return RepairResult(
                    success=True,
                    filepath=str(path),
                    patch_code=patch_code,
                    test_output=test_output,
                    commit_hash=commit_hash if commit_ok else "",
                    attempts=attempt,
                )
            else:
                # 8. Roll back and carry failure context into the next attempt
                await self._git_reset_file(path)
                previous_failure = f"Tests failed on attempt {attempt}:\n{test_output[-1500:]}"
                logger.warning("[SWE] Attempt %d: tests failed -- rolling back and retrying.", attempt)

        # All attempts exhausted
        await self._git_reset_file(path)
        return RepairResult(
            success=False,
            filepath=str(path),
            error=(
                f"All {MAX_REPAIR_ATTEMPTS} repair attempts exhausted. "
                f"Last failure: {previous_failure or 'unknown'}"
            ),
            attempts=MAX_REPAIR_ATTEMPTS,
        )

    async def run_task(
        self,
        repo_name: str,
        issue_text: str,
        base_commit: Optional[str] = None,
    ) -> dict:
        """Backward-compatible entrypoint. Wraps repair_backend_file().

        repo_name is used to locate the file:
          "rate_limiter"  -> shard_workspace/rate_limiter.py
          "study_agent"   -> backend/study_agent.py
        """
        # Prefer workspace dir, then backend dir
        candidate = self.workspace_dir / f"{repo_name.replace('-', '_')}.py"
        if not candidate.exists():
            candidate = BACKEND_DIR / f"{repo_name.replace('-', '_')}.py"

        result = await self.repair_backend_file(
            filepath=str(candidate),
            issue_text=issue_text,
            require_tests=True,
        )
        return {
            "patch_applied": bool(result.patch_code),
            "tests_passed": result.success,
            "test_output": result.test_output or result.error,
            "commit_hash": result.commit_hash,
            "attempts": result.attempts,
        }

    # ── Prompt builder ─────────────────────────────────────────────────────────

    def _build_repair_prompt(
        self,
        filepath: Path,
        code: str,
        issue_text: str,
        error_context: str,
        previous_failure: Optional[str],
        attempt: int,
    ) -> str:
        parts = [
            "You are a precise Python code repair agent.",
            "Output ONLY the corrected Python source code.",
            "No markdown fences, no explanation, no commentary.",
            "",
            f"=== FILE: {filepath.name} ===",
            code,
            "",
            "=== ISSUE ===",
            issue_text,
        ]
        if error_context:
            parts += ["", "=== ERROR CONTEXT ===", error_context]
        if previous_failure:
            parts += [
                "",
                f"=== PREVIOUS ATTEMPT {attempt - 1} FAILED ===",
                previous_failure,
                "Study the failure above carefully and fix your approach before trying again.",
            ]
        parts += [
            "",
            "=== INSTRUCTIONS ===",
            "1. Fix the issue described above.",
            "2. Do NOT remove existing imports unless they are causing the bug.",
            "3. Preserve all existing functionality.",
            "4. Return the COMPLETE corrected file -- not just the changed lines.",
            "5. Output raw Python only. No markdown. No code fences. No explanation.",
        ]
        return "\n".join(parts)

    # ── LLM call ───────────────────────────────────────────────────────────────

    async def _generate_patch(self, prompt: str) -> str:
        try:
            from llm_router import llm_complete
        except ImportError:
            from backend.llm_router import llm_complete
        return await llm_complete(
            prompt=prompt,
            system=(
                "You are a precise code repair assistant. "
                "Output only valid Python code, no markdown, no explanation."
            ),
            max_tokens=8192,
            temperature=0.05,
        )

    # ── Code extraction ────────────────────────────────────────────────────────

    def _extract_code(self, raw: str, fallback: str) -> str:
        """Strip markdown fences and return the Python code within."""
        raw = raw.strip()

        # Try ```python ... ``` then plain ``` ... ```
        for pattern in (r"```python\s*\n(.*?)```", r"```\s*\n(.*?)```"):
            m = re.search(pattern, raw, re.DOTALL)
            if m:
                return m.group(1).strip()

        # If the entire response parses as valid Python, use it directly
        try:
            ast.parse(raw)
            return raw
        except SyntaxError:
            pass

        # Last resort: return raw and let the safety gate catch any issues
        logger.warning("[SWE] Could not extract clean code -- returning raw LLM output.")
        return raw

    # ── Test discovery ─────────────────────────────────────────────────────────

    def _discover_tests(self, filepath: Path) -> List[str]:
        """Find test files for a given source file."""
        module = filepath.stem
        candidates = [
            REPO_ROOT / "tests" / f"test_{module}.py",
            REPO_ROOT / "backend" / "tests" / f"test_{module}.py",
            REPO_ROOT / f"test_{module}.py",
        ]
        found = [str(p) for p in candidates if p.exists()]
        if found:
            logger.info("[SWE] Tests for %s: %s", module, found)
        else:
            logger.info("[SWE] No tests found for %s.", module)
        return found

    # ── Test runner ────────────────────────────────────────────────────────────

    async def _run_tests(self, test_paths: List[str]) -> tuple[str, bool]:
        """Run pytest with a hard 60-second timeout."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pytest", *test_paths, "-q", "--tb=short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(REPO_ROOT),
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=PYTEST_TIMEOUT_SECONDS
                )
                output = stdout.decode("utf-8", errors="replace")
                passed = proc.returncode == 0
                logger.info("[SWE] Tests %s (rc=%d).", "PASSED" if passed else "FAILED", proc.returncode)
                return output, passed
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                msg = f"[SWE] TIMEOUT: pytest exceeded {PYTEST_TIMEOUT_SECONDS}s -- process killed."
                logger.error(msg)
                return msg, False
        except FileNotFoundError:
            msg = "[SWE] pytest not found in PATH -- cannot run tests."
            logger.error(msg)
            return msg, False

    # ── Git integration ────────────────────────────────────────────────────────

    async def _git_commit(self, filepath: Path, message: str) -> tuple[bool, str]:
        """Stage the file and create a commit. Returns (success, commit_hash)."""
        try:
            add = await asyncio.create_subprocess_exec(
                "git", "add", str(filepath),
                cwd=str(REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await add.communicate()

            commit = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", message,
                cwd=str(REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await commit.communicate()

            if commit.returncode != 0:
                err = stderr.decode("utf-8", errors="replace").strip()
                logger.warning("[SWE] git commit failed: %s", err)
                return False, ""

            out = stdout.decode("utf-8", errors="replace")
            m = re.search(r"\b([0-9a-f]{7,40})\b", out)
            commit_hash = m.group(1) if m else ""
            return True, commit_hash

        except Exception as e:
            logger.error("[SWE] git commit exception: %s", e)
            return False, ""

    async def _git_reset_file(self, filepath: Path) -> None:
        """Roll back uncommitted changes to a single file (git checkout --)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "checkout", "--", str(filepath),
                cwd=str(REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info("[SWE] Rolled back %s.", filepath.name)
        except Exception as e:
            logger.error("[SWE] git reset failed for %s: %s", filepath.name, e)

    # ── Atomic write ───────────────────────────────────────────────────────────

    async def _apply_patch(self, filepath: Path, code: str) -> tuple[bool, str]:
        """Write code atomically via tempfile + os.replace."""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=str(filepath.parent), suffix=".tmp", delete=False,
            ) as tf:
                tf.write(code)
                tmp_path = tf.name
            os.replace(tmp_path, str(filepath))
            logger.info("[SWE] Patch written atomically to '%s'.", filepath.name)
            return True, "patch applied"
        except OSError as e:
            logger.error("[SWE] Write error for '%s': %s", filepath.name, e)
            return False, f"Write error: {e}"

    # ── Legacy shim methods (kept for backward compatibility) ──────────────────

    async def repair_file(self, filepath: str) -> tuple[bool, str]:
        """Deprecated: use repair_backend_file() instead."""
        result = await self.repair_backend_file(
            filepath, issue_text="Fix any bugs found in this file."
        )
        return result.success, result.error or result.test_output

    async def repair_file_with_llm(self, filepath: str, issue_text: str) -> tuple[bool, str]:
        """Deprecated: use repair_backend_file() instead."""
        result = await self.repair_backend_file(filepath, issue_text=issue_text)
        return result.success, result.error or result.test_output
