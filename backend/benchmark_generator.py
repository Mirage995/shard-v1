"""benchmark_generator.py -- Generates objective benchmark test cases for StudyAgent certification.

Replaces the legacy stub with a real LLM-powered test case generator.
Each generated test is validated with ast.parse before being returned.
Malformed tests are silently discarded -- they never penalise the agent.
"""
import ast
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional


DEFAULT_N_TESTS = 5

_SYSTEM_PROMPT = (
    "You are a senior Python test engineer. "
    "Generate concise, self-contained benchmark test cases. "
    "OUTPUT ONLY VALID JSON. No markdown, no backticks, no explanations."
)

_USER_TEMPLATE = """\
Generate exactly {n_tests} Python benchmark test cases for this topic:

TOPIC: {topic}

The agent wrote this implementation (for reference -- do NOT copy it verbatim):
{code_snippet}

Return a JSON object with EXACTLY this structure:
{{
  "scaffold": "def solve(input_data):\\n    # implement here\\n    pass",
  "tests": [
    {{
      "description": "what this test checks",
      "setup": "input_data = <value>\\nexpected = <value>",
      "assert_expr": "assert solve(input_data) == expected"
    }}
  ]
}}

Rules:
- The function signature must ALWAYS be: def solve(input_data)
- Each test must use ONLY Python builtins (no imports in setup or assert_expr)
- 'setup' must define exactly the variables 'input_data' and 'expected'
- 'expected' must ALWAYS be a plain Python literal (int, float, str, bool, list, tuple) -- NEVER a numpy array or other non-builtin object
- Choose 'assert_expr' based on the output type:
    * exact match (int, bool, str, list of int/str, tuple): assert solve(input_data) == expected
    * single float (approximate): assert abs(solve(input_data) - expected) < 1e-6
    * list of floats (approximate): assert all(abs(a - b) < 1e-6 for a, b in zip(solve(input_data), expected))
- If solve() returns a numpy array, convert to list in assert_expr: assert list(solve(input_data)) == expected
- Tests must cover: basic case, edge case, and a larger/harder input
- All values must be valid Python literals (no placeholders like '...')
- If the topic cannot be expressed as a callable function, return {{"scaffold": "", "tests": []}}\
"""


class BenchmarkGenerator:
    """Generates objective test cases for StudyAgent benchmark certification.

    Args:
        think_fn: Async callable ``(prompt, system, json_mode) -> str``.
                  Typically ``StudyAgent._think_fast``.
                  If None, ``generate()`` always returns unavailable.
    """

    def __init__(self, think_fn: Optional[Callable[..., Awaitable[str]]] = None):
        self._think = think_fn

    # ── Main async API ─────────────────────────────────────────────────────────

    async def generate(
        self,
        topic: str,
        synthesized_code: str = "",
        difficulty: int = 1,
        n_tests: int = DEFAULT_N_TESTS,
    ) -> Dict[str, Any]:
        """Generate and validate benchmark test cases for a topic.

        Returns:
            {
              "scaffold":  str,       # function stub the agent must implement
              "tests":     List[Dict],# validated test cases only
              "n_valid":   int,       # tests that passed syntax validation
              "available": bool,      # False if generation/parsing failed entirely
              "topic":     str,
            }
        """
        if not self._think:
            return _unavailable(topic, "no LLM callable configured")

        code_snippet = synthesized_code[:600].strip() or "(no implementation provided)"
        prompt = _USER_TEMPLATE.format(
            topic=topic,
            code_snippet=code_snippet,
            n_tests=n_tests,
        )

        try:
            raw = await self._think(prompt, _SYSTEM_PROMPT, json_mode=True)
        except Exception as e:
            print(f"[BENCHMARK_GEN] ❌ LLM call failed: {e}")
            return _unavailable(topic, str(e))

        data = _parse_json(raw)
        if data is None:
            return _unavailable(topic, "JSON parse error")

        scaffold = str(data.get("scaffold") or "def solve(input_data):\n    pass")
        raw_tests = data.get("tests", [])

        if not isinstance(raw_tests, list):
            print("[BENCHMARK_GEN] [WARN]️ 'tests' is not a list -- discarding")
            return _unavailable(topic, "malformed 'tests' field")

        valid_tests: List[Dict[str, Any]] = []
        for i, t in enumerate(raw_tests):
            verdict = _validate_test(t, i)
            if verdict["ok"]:
                valid_tests.append({
                    "description": str(t.get("description", f"test_{i}")),
                    "setup":       t["setup"].strip(),
                    "assert_expr": t["assert_expr"].strip(),
                })
            else:
                print(f"[BENCHMARK_GEN] [WARN]️ Test {i} discarded: {verdict['reason']}")

        print(
            f"[BENCHMARK_GEN] ✅ {len(valid_tests)}/{len(raw_tests)} tests "
            f"validated for '{topic}'"
        )
        return {
            "scaffold":  scaffold,
            "tests":     valid_tests,
            "n_valid":   len(valid_tests),
            "available": len(valid_tests) > 0,
            "topic":     topic,
        }

    # ── Legacy stub API (keeps existing study_agent.py call sites working) ─────

    def generate_for_capability(self, capability_name: str, difficulty: int = 1):
        """Legacy sync stub -- kept for backward compatibility with existing call sites.
        Real generation is done via the async ``generate()`` method.
        """
        return {
            "capability": capability_name,
            "difficulty": difficulty,
        }


# ── Module-level helpers ───────────────────────────────────────────────────────

def _unavailable(topic: str, reason: str) -> Dict[str, Any]:
    return {
        "scaffold":  "",
        "tests":     [],
        "n_valid":   0,
        "available": False,
        "topic":     topic,
        "reason":    reason,
    }


def _parse_json(raw: Any) -> Optional[Dict]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences and retry
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"[BENCHMARK_GEN] ❌ JSON parse failed. Raw (first 200): {raw[:200]}")
        return None


def _validate_test(test: Any, idx: int) -> Dict[str, Any]:
    """Validate a single test-case dict.

    Checks performed:
      1. Is a dict with required keys ('setup', 'assert_expr').
      2. 'assert_expr' starts with the ``assert`` keyword.
      3. No dangerous builtins in setup or assert.
      4. Combined code (setup + assert_expr) is syntactically valid Python (ast.parse).
    """
    if not isinstance(test, dict):
        return {"ok": False, "reason": "not a dict"}

    for key in ("setup", "assert_expr"):
        if not isinstance(test.get(key), str) or not test[key].strip():
            return {"ok": False, "reason": f"missing or empty '{key}'"}

    setup       = test["setup"].strip()
    assert_expr = test["assert_expr"].strip()

    if not assert_expr.startswith("assert "):
        return {"ok": False, "reason": "assert_expr must start with 'assert '"}

    _DANGEROUS = ("__import__", "exec(", "eval(", "open(", "os.", "sys.", "subprocess")
    for bad in _DANGEROUS:
        if bad in setup or bad in assert_expr:
            return {"ok": False, "reason": f"dangerous pattern: {bad}"}

    # AST validation -- catches any remaining syntax issues
    try:
        ast.parse(f"{setup}\n{assert_expr}")
    except SyntaxError as e:
        return {"ok": False, "reason": f"SyntaxError: {e}"}

    # Runtime type check -- reject only None and bare bool (almost always a generation mistake).
    # int, float, dict, str, list, tuple, set are all valid input_data types depending on
    # the function under test (e.g. profiling takes int size, json parsing takes dict).
    # Also: auto-rewrite assert_expr for float/list-of-float expected values so that
    # numpy outputs don't cause "ValueError: truth value of array is ambiguous".
    try:
        ns: dict = {}
        exec(compile(ast.parse(setup), "<setup>", "exec"), ns)
        val = ns.get("input_data")
        if val is None or isinstance(val, bool):
            return {"ok": False, "reason": f"input_data is {type(val).__name__} -- likely a generation mistake"}

        # Auto-rewrite assert for float/list-of-float expected values.
        # This guards against "ValueError: truth value of array ambiguous" when
        # solve() returns a numpy array and the LLM used == instead of allclose.
        expected_val = ns.get("expected")
        boilerplate = "assert solve(input_data) == expected"
        if assert_expr == boilerplate:
            if isinstance(expected_val, float):
                test["assert_expr"] = "assert abs(solve(input_data) - expected) < 1e-6"
            elif (
                isinstance(expected_val, (list, tuple))
                and expected_val
                and all(isinstance(v, float) for v in expected_val)
            ):
                test["assert_expr"] = (
                    "assert all(abs(a - b) < 1e-6 for a, b in zip(solve(input_data), expected))"
                )
    except Exception:
        pass  # if eval fails for any reason, let AST validation stand

    return {"ok": True}
