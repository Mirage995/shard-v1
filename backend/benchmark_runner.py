"""benchmark_runner.py -- Executes benchmark test cases in the Docker sandbox.

Replaces the legacy stub with real isolated test execution.

Key design:
  - Each test is validated independently (ast.parse) BEFORE execution.
  - "Test is malformed" and "agent's implementation failed" are two distinct outcomes.
    Only the latter counts as a failure. Malformed tests are discarded silently.
  - pass_rate = passed / (passed + failed)  -- discarded tests are excluded from the denominator.
"""
import ast
import re
from typing import Any, Dict, List, Optional


class BenchmarkRunner:
    """Runs generated benchmark test cases against an agent implementation.

    Args:
        sandbox_runner: ``DockerSandboxRunner`` instance for isolated execution.
                        If None, all runs return unavailable.
    """

    def __init__(self, sandbox_runner=None):
        self._sandbox = sandbox_runner

    # ── Main async API ─────────────────────────────────────────────────────────

    async def run_benchmark(
        self,
        benchmark: Dict[str, Any],
        implementation_code: str = "",
        topic: str = "",
    ) -> Dict[str, Any]:
        """Run all benchmark tests against the given implementation.

        Args:
            benchmark:           dict from ``BenchmarkGenerator.generate()``.
            implementation_code: Python source containing a ``solve(input_data)`` function.
            topic:               used for sandbox logging only.

        Returns:
            {
              "pass_rate":  float,      # 0.0–1.0 (discarded tests excluded)
              "passed":     int,
              "failed":     int,
              "discarded":  int,        # malformed tests, NOT penalised
              "total":      int,        # passed + failed
              "details":    List[Dict],
              "available":  bool,
              "success":    bool,       # True if at least one test ran
            }
        """
        if not self._sandbox:
            return _unavailable("no sandbox runner configured")
        if not benchmark.get("available"):
            return _unavailable("benchmark not available")

        tests = benchmark.get("tests", [])
        if not tests:
            return _unavailable("no tests in benchmark")

        # Carry forward the dominant input_data type from the generator (or re-derive it).
        dominant_input_type: str | None = benchmark.get("dominant_input_type")
        if not dominant_input_type:
            dominant_input_type = _infer_dominant_type(tests)

        if not implementation_code.strip():
            return _unavailable("no implementation code provided")

        if "def solve(" not in implementation_code:
            return _unavailable("implementation missing 'def solve(' function")

        details: List[Dict[str, Any]] = []
        passed = failed = discarded = 0

        for i, test in enumerate(tests):
            result = await self._run_single_test(
                test=test,
                implementation=implementation_code,
                test_idx=i,
                topic=topic,
            )
            details.append(result)
            status = result["status"]
            if status == "pass":
                passed += 1
            elif status == "fail":
                failed += 1
            else:
                discarded += 1

        total     = passed + failed
        pass_rate = round(passed / total, 3) if total > 0 else 0.0

        print(
            f"[BENCHMARK_RUN] '{topic}': "
            f"{passed}/{total} passed "
            f"(+{discarded} discarded) "
            f"-> pass_rate={pass_rate:.0%}"
        )

        return {
            "pass_rate":           pass_rate,
            "passed":              passed,
            "failed":              failed,
            "discarded":           discarded,
            "total":               total,
            "details":             details,
            "available":           True,
            "success":             total > 0,
            "dominant_input_type": dominant_input_type,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _run_single_test(
        self,
        test: Dict[str, Any],
        implementation: str,
        test_idx: int,
        topic: str,
    ) -> Dict[str, Any]:
        """Execute one test case. Returns ``status``: 'pass' | 'fail' | 'discarded'."""
        setup       = (test.get("setup") or "").strip()
        assert_expr = (test.get("assert_expr") or "").strip()
        description = str(test.get("description") or f"test_{test_idx}")

        # ── Step 1: pre-flight syntax check (no sandbox, instant) ─────────────
        # Parse setup + assert WITHOUT the implementation.
        # A SyntaxError here means the TEST is broken, not the agent.
        try:
            ast.parse(f"{setup}\n{assert_expr}")
        except SyntaxError as e:
            print(
                f"[BENCHMARK_RUN] [WARN]️  Test {test_idx} discarded "
                f"(SyntaxError in test itself): {e}"
            )
            return {
                "test_idx":    test_idx,
                "description": description,
                "status":      "discarded",
                "reason":      f"test SyntaxError: {e}",
            }

        # ── Step 2: assemble full script ────────────────────────────────────────
        # Layout: implementation first, then a labelled test block.
        # The blank line + comment separator makes line-number attribution reliable.
        impl_line_count = implementation.count("\n") + 1
        full_code = (
            f"{implementation.rstrip()}\n\n"
            f"# --- benchmark test {test_idx} ---\n"
            f"{setup}\n"
            f"{assert_expr}\n"
        )

        # ── Step 3: execute in sandbox ─────────────────────────────────────────
        try:
            sandbox_result = await self._sandbox.run(
                topic=f"benchmark:{topic}",
                code=full_code,
            )
        except Exception as e:
            print(f"[BENCHMARK_RUN] ❌ Sandbox exception on test {test_idx}: {e}")
            return {
                "test_idx":    test_idx,
                "description": description,
                "status":      "fail",
                "reason":      f"sandbox exception: {e}",
            }

        success = sandbox_result.get("success", False)
        stderr  = sandbox_result.get("stderr", "")
        stdout  = sandbox_result.get("stdout", "")

        if success:
            return {
                "test_idx":    test_idx,
                "description": description,
                "status":      "pass",
                "stdout":      stdout[:200],
            }

        # ── Step 4: classify the failure ───────────────────────────────────────

        # Infrastructure error (Docker not running, image build failed, etc.)
        # -> discard the test entirely, do not penalise the agent.
        if _is_infrastructure_error(stderr):
            print(
                f"[BENCHMARK_RUN] [WARN]️  Test {test_idx} discarded "
                f"(infrastructure error -- Docker unavailable)"
            )
            return {
                "test_idx":    test_idx,
                "description": description,
                "status":      "discarded",
                "reason":      f"infrastructure: {stderr[:120]}",
            }

        # Test is syntactically broken (SyntaxError in test block lines)
        # -> discard, not the agent's fault.
        if _is_test_fault(stderr, impl_line_count):
            print(
                f"[BENCHMARK_RUN] [WARN]️  Test {test_idx} discarded "
                f"(runtime fault in test block, not in implementation)"
            )
            return {
                "test_idx":    test_idx,
                "description": description,
                "status":      "discarded",
                "reason":      f"test runtime error: {stderr[:200]}",
            }

        # Legitimate failure -- implementation did not satisfy the assert
        return {
            "test_idx":    test_idx,
            "description": description,
            "status":      "fail",
            "stderr":      stderr[:300],
            "stdout":      stdout[:200],
        }

    # ── Legacy stub API (keeps existing study_agent.py call sites working) ─────

    def run(self, benchmark: Dict[str, Any]) -> Dict[str, Any]:
        """Legacy sync stub -- kept for backward compatibility with existing call sites.
        Real execution is done via the async ``run_benchmark()`` method.
        """
        return {"success": True, "benchmark": benchmark}


# ── Module-level helpers ───────────────────────────────────────────────────────

def _unavailable(reason: str) -> Dict[str, Any]:
    return {
        "pass_rate":  0.0,
        "passed":     0,
        "failed":     0,
        "discarded":  0,
        "total":      0,
        "details":    [],
        "available":  False,
        "success":    False,
        "reason":     reason,
    }


_INFRASTRUCTURE_PATTERNS = (
    "docker",
    "sandbox unavailable",
    "failed to automatically build",
    "dockerdesktoplinuxengine",
    "cannot find the file specified",
    "is the daemon running",
    "pipe/docker",
)


def _is_infrastructure_error(stderr: str) -> bool:
    """Return True if stderr indicates a Docker/infra failure rather than a code error."""
    low = stderr.lower()
    return any(pat in low for pat in _INFRASTRUCTURE_PATTERNS)


def _infer_dominant_type(tests: list) -> str | None:
    """Best-effort: execute each test's setup and return the type name of input_data."""
    import ast as _ast
    counts: dict = {}
    for t in tests:
        setup = (t.get("setup") or "").strip()
        if not setup:
            continue
        try:
            ns: dict = {}
            exec(compile(_ast.parse(setup), "<setup>", "exec"), ns)
            t_name = type(ns.get("input_data")).__name__
            counts[t_name] = counts.get(t_name, 0) + 1
        except Exception:
            pass
    if not counts:
        return None
    return max(counts, key=counts.__getitem__)


def _is_test_fault(stderr: str, impl_line_count: int) -> bool:
    """Return True if stderr suggests a SyntaxError originating in the test block.

    We add a 3-line buffer (blank line + comment separator + first test line)
    on top of impl_line_count to avoid false positives from multi-line
    function definitions or decorators at the end of the implementation.
    """
    if "SyntaxError" not in stderr:
        return False

    matches = re.findall(r"line (\d+)", stderr)
    if not matches:
        return False

    # The last line number in the traceback is usually the most precise.
    error_line = int(matches[-1])
    return error_line > impl_line_count + 3
