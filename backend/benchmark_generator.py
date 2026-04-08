"""benchmark_generator.py -- Generates objective benchmark test cases for StudyAgent certification.

Replaces the legacy stub with a real LLM-powered test case generator.
Each generated test is validated with ast.parse before being returned.
Malformed tests are silently discarded -- they never penalise the agent.

Network topics (#20): detected via is_network_topic() and routed to _USER_TEMPLATE_MOCK_NETWORK,
which uses unittest.mock monkeypatching so tests run inside Docker --network none without error.
"""
import ast
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional


DEFAULT_N_TESTS = 5

# ── Network topic detection ────────────────────────────────────────────────────

# Tight keyword set: only trigger on explicit networking terms.
# Deliberately excludes "network" alone to avoid matching "neural network".
_NETWORK_KEYWORDS = frozenset({
    "socket", "tcp", "udp", "http", "https", "websocket",
    "urllib", "requests", "aiohttp", "httpx", "http.client",
    "ftp", "smtp", "pop3", "imap", "dns",
})


def is_network_topic(topic: str) -> bool:
    """Return True if *topic* requires network I/O and should use mock-based benchmarks."""
    tokens = set(topic.lower().replace("-", " ").replace("_", " ").split())
    return bool(tokens & _NETWORK_KEYWORDS)


# ── Prompt templates ───────────────────────────────────────────────────────────

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
- 'input_data' must be a SINGLE value of a CONSISTENT type across ALL tests: int, float, str, list, or dict. NEVER a tuple unless every test uses a tuple.
- The scaffold's solve() function must accept the SAME type as input_data. If input_data is a list, solve() must expect a list. If input_data is a str, solve() must expect a str. They must match.
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

_USER_TEMPLATE_MOCK_NETWORK = """\
Generate exactly {n_tests} Python benchmark test cases for this NETWORK topic:

TOPIC: {topic}

The agent wrote this implementation (for reference -- do NOT copy it verbatim):
{code_snippet}

CRITICAL CONSTRAINT: The sandbox has NO real network access (Docker --network none).
All tests MUST use only unittest.mock from the Python standard library to simulate network I/O.
DO NOT use any external mock libraries (no pytest-mock, responses, httpretty, aioresponses, vcrpy, or any other third-party library).
unittest.mock is the ONLY allowed mocking tool.

Return a JSON object with EXACTLY this structure:
{{
  "scaffold": "import socket\\nimport unittest.mock\\n\\ndef solve(input_data):\\n    # implement network logic here\\n    pass",
  "tests": [
    {{
      "description": "what this test checks",
      "setup": "import socket\\nimport unittest.mock\\n_mock_sock = unittest.mock.MagicMock()\\n_mock_sock.recv.return_value = b'Hello'\\nsocket.socket = lambda *a, **kw: _mock_sock\\ninput_data = {{'host': 'localhost', 'port': 8080}}\\nexpected = b'Hello'",
      "assert_expr": "assert solve(input_data) == expected"
    }}
  ]
}}

Monkeypatching rules (choose the right pattern for the topic):
- socket topics:
    import socket, unittest.mock
    _mock_sock = unittest.mock.MagicMock()
    _mock_sock.recv.return_value = b"<response bytes>"
    socket.socket = lambda *a, **kw: _mock_sock
- requests topics:
    import requests, unittest.mock
    _mock_resp = unittest.mock.MagicMock()
    _mock_resp.status_code = 200
    _mock_resp.json.return_value = {{"key": "value"}}
    _mock_resp.text = '{{"key": "value"}}'
    requests.get = lambda *a, **kw: _mock_resp
- http.client topics:
    import http.client, unittest.mock
    _mock_conn = unittest.mock.MagicMock()
    _mock_resp = unittest.mock.MagicMock()
    _mock_resp.status = 200
    _mock_resp.read.return_value = b"<body>"
    _mock_conn.getresponse.return_value = _mock_resp
    http.client.HTTPConnection = lambda *a, **kw: _mock_conn

Additional rules:
- The function signature must ALWAYS be: def solve(input_data)
- solve() MUST use the real network API (socket.socket(), requests.get(), http.client.HTTPConnection(), etc.) -- the mock intercepts at runtime
- 'input_data' must be a dict with connection parameters (host, port, url, path, method, data, etc.)
- 'expected' must be a Python literal (bytes, str, int, dict, list, bool)
- 'assert_expr' must be a simple one-liner: assert solve(input_data) == expected
- Monkeypatching happens in 'setup', BEFORE solve() is called -- never inside assert_expr
- Do NOT use with-statement patches or decorators -- only direct attribute replacement
- Do NOT import anything outside of: socket, requests, http.client, urllib, urllib.request, urllib.parse, collections, unittest.mock
- solve() must be synchronous (def, not async def) -- use asyncio.run() internally if the topic requires it
- Tests must cover: basic success case, error/edge case, and a data variation
- All values must be valid Python literals (no placeholders like '...' or <value>)
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
        template = _USER_TEMPLATE_MOCK_NETWORK if is_network_topic(topic) else _USER_TEMPLATE
        if is_network_topic(topic):
            print(f"[BENCHMARK_GEN] Network topic detected -- using mock template for '{topic}'")
        prompt = template.format(
            topic=topic,
            code_snippet=code_snippet,
            n_tests=n_tests,
        )

        try:
            raw = await self._think(prompt, _SYSTEM_PROMPT, json_mode=True)
        except Exception as e:
            print(f"[BENCHMARK_GEN] FAIL LLM call failed: {e}")
            return _unavailable(topic, str(e))

        data = _parse_json(raw)
        if data is None:
            return _unavailable(topic, "JSON parse error")

        scaffold = str(data.get("scaffold") or "def solve(input_data):\n    pass")
        raw_tests = data.get("tests", [])

        if not isinstance(raw_tests, list):
            print("[BENCHMARK_GEN] [WARN] 'tests' is not a list -- discarding")
            return _unavailable(topic, "malformed 'tests' field")

        _is_net = is_network_topic(topic)
        valid_tests: List[Dict[str, Any]] = []
        for i, t in enumerate(raw_tests):
            verdict = _validate_test(t, i, is_net=_is_net)
            if verdict["ok"]:
                valid_tests.append({
                    "description": str(t.get("description", f"test_{i}")),
                    "setup":       t["setup"].strip(),
                    "assert_expr": t["assert_expr"].strip(),
                })
            else:
                print(f"[BENCHMARK_GEN] [WARN] Test {i} discarded: {verdict['reason']}")

        # ── Network topic guard: save/restore modules that setup code may monkeypatch ──
        # In Docker (production), each test runs in an isolated process so global
        # mutations are safe.  Here in the host process (validation), we must restore.
        _net_guards: List[tuple] = []
        if is_network_topic(topic):
            import importlib as _il
            for _mod_name in ("socket", "requests", "http.client", "urllib.request"):
                try:
                    _mod = _il.import_module(_mod_name)
                    _net_guards.append((_mod, dict(vars(_mod))))
                except Exception:
                    pass

        def _restore_net_guards() -> None:
            for _mod, _snapshot in _net_guards:
                for _k, _v in _snapshot.items():
                    try:
                        setattr(_mod, _k, _v)
                    except Exception:
                        pass

        # For network topics, skip exec-based runtime checks entirely.
        # Mock setup code does `socket.socket = lambda *a, **kw: _mock_sock` which monkeypatches
        # the global socket module. On Windows, the asyncio ProactorEventLoop asynchronously calls
        # isinstance(conn, socket.socket) in _loop_self_reading -- if socket.socket is a lambda,
        # this raises TypeError and crashes the event loop. Syntax validation from _validate_test()
        # is sufficient for network topics; exec-based checks run only for non-network topics.
        if is_network_topic(topic):
            consistent_tests = valid_tests
            dominant_type: type | None = dict  # network topics always use dict input_data
            print(f"[BENCHMARK_GEN] Network topic: skipping exec-based checks (mock safety)")
        else:
            # Runtime consistency check #1: run scaffold stub + each test.
            # Catches attribute/type errors that the stub exposes (e.g. input_data.split() on a list).
            consistent_tests = []
            for t in valid_tests:
                try:
                    ns: dict = {}
                    exec(compile(ast.parse(scaffold), "<scaffold>", "exec"), ns)
                    exec(compile(ast.parse(t["setup"]), "<setup>", "exec"), ns)
                    exec(compile(ast.parse("result = solve(input_data)"), "<run>", "exec"), ns)
                    consistent_tests.append(t)
                except (AttributeError, TypeError) as e:
                    print(f"[BENCHMARK_GEN] [WARN] Test '{t['description'][:40]}' discarded (stub type error): {e}")
                except Exception:
                    consistent_tests.append(t)  # other errors are OK (NotImplemented, etc.)
                finally:
                    _restore_net_guards()

            if len(consistent_tests) < len(valid_tests):
                print(f"[BENCHMARK_GEN] Runtime check: {len(valid_tests) - len(consistent_tests)} inconsistent tests dropped")

            # Runtime consistency check #2: enforce same input_data type across all tests.
            # The LLM sometimes generates mixed types (some tests pass str, others dict).
            # This causes TypeError in the real implementation even though the stub passes.
            type_checked: List[Dict[str, Any]] = []
            dominant_type = None
            for t in consistent_tests:
                try:
                    ns: dict = {}
                    exec(compile(ast.parse(t["setup"]), "<setup>", "exec"), ns)
                    val = ns.get("input_data")
                    t_type = type(val)
                    if dominant_type is None:
                        dominant_type = t_type
                        type_checked.append(t)
                    elif t_type == dominant_type:
                        type_checked.append(t)
                    else:
                        print(
                            f"[BENCHMARK_GEN] [WARN] Test '{t['description'][:40]}' discarded "
                            f"(type mismatch: {t_type.__name__} vs dominant {dominant_type.__name__})"
                        )
                except Exception:
                    type_checked.append(t)  # if we can't eval setup, keep it
                finally:
                    _restore_net_guards()

            if len(type_checked) < len(consistent_tests):
                print(f"[BENCHMARK_GEN] Type-homogeneity check: {len(consistent_tests) - len(type_checked)} tests dropped")
            consistent_tests = type_checked

        print(
            f"[BENCHMARK_GEN] OK {len(consistent_tests)}/{len(raw_tests)} tests "
            f"validated for '{topic}'"
        )
        return {
            "scaffold":           scaffold,
            "tests":              consistent_tests,
            "n_valid":            len(consistent_tests),
            "available":          len(consistent_tests) > 0,
            "topic":              topic,
            "dominant_input_type": dominant_type.__name__ if dominant_type is not None else None,
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
        "scaffold":           "",
        "tests":              [],
        "n_valid":            0,
        "available":          False,
        "topic":              topic,
        "reason":             reason,
        "dominant_input_type": None,
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
        print(f"[BENCHMARK_GEN] FAIL JSON parse failed. Raw (first 200): {raw[:200]}")
        return None


def _validate_test(test: Any, idx: int, is_net: bool = False) -> Dict[str, Any]:
    """Validate a single test-case dict.

    Checks performed:
      1. Is a dict with required keys ('setup', 'assert_expr').
      2. 'assert_expr' starts with the ``assert`` keyword.
      3. No dangerous builtins in setup or assert.
      4. Combined code (setup + assert_expr) is syntactically valid Python (ast.parse).
      5. (non-network only) Runtime type check: input_data must not be None/bool.

    Args:
        is_net: If True, skip the exec()-based runtime type check. Network test setups
                monkeypatch socket.socket = lambda..., which contaminates the global
                socket module in the host process and can crash the asyncio event loop
                on Windows (ProactorEventLoop isinstance check race condition).
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
    #
    # IMPORTANT: skip exec() entirely for network topics. Network test setups do:
    #   socket.socket = lambda *a, **kw: _mock_sock
    # This mutates the global socket module in the host process. On Windows the asyncio
    # ProactorEventLoop calls isinstance(conn, socket.socket) asynchronously; if
    # socket.socket is a lambda, isinstance() throws TypeError and crashes the event loop.
    if not is_net:
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
