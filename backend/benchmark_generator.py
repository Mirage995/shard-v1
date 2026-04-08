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
from dataclasses import dataclass, field
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


# ── Output schema ─────────────────────────────────────────────────────────────

@dataclass
class _TestCase:
    description: str
    setup: str
    assert_expr: str


@dataclass
class _BenchmarkSpec:
    scaffold: str
    tests: list = field(default_factory=list)  # list[_TestCase]


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

SUCCESS CASE (normal response):
    import socket, unittest.mock
    _mock_sock = unittest.mock.MagicMock()
    _mock_sock.__enter__.return_value = _mock_sock  # required if solve() uses 'with socket.socket(...) as s:'
    _mock_sock.recv.return_value = b"HTTP/1.1 200 OK\r\n\r\nHello"
    socket.socket = lambda *a, **kw: _mock_sock
    input_data = {{"host": "localhost", "port": 8080}}
    expected = b"HTTP/1.1 200 OK\r\n\r\nHello"

ERROR CASE (exception raised by connect/send/recv):
    CRITICAL RULE: to make connect() raise an exception, set side_effect on the METHOD,
    NOT on the mock object. NEVER use MagicMock(side_effect=...) for this.
    CORRECT pattern:
        _mock_sock = unittest.mock.MagicMock()
        _mock_sock.__enter__.return_value = _mock_sock
        _mock_sock.connect.side_effect = ConnectionRefusedError  # on .connect, NOT on _mock_sock
        socket.socket = lambda *a, **kw: _mock_sock
        input_data = {{"host": "localhost", "port": 9999}}
        expected = None  # solve() must catch the exception and return None
    WRONG pattern (DO NOT USE):
        _mock_sock = unittest.mock.MagicMock(side_effect=ConnectionRefusedError)  # WRONG

requests topics:
    import requests, unittest.mock
    _mock_resp = unittest.mock.MagicMock()
    _mock_resp.status_code = 200
    _mock_resp.json.return_value = {{"key": "value"}}
    _mock_resp.text = '{{"key": "value"}}'
    requests.get = lambda *a, **kw: _mock_resp

http.client topics:
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
- 'expected' must be a Python literal (bytes, str, int, dict, list, bool, None)
- 'assert_expr' must be a simple one-liner. Use 'is' for None: assert solve(input_data) is expected
- Monkeypatching happens in 'setup', BEFORE solve() is called -- never inside assert_expr
- Do NOT use with-statement patches or decorators -- only direct attribute replacement
- Do NOT import anything outside of: socket, requests, http.client, urllib, urllib.request, urllib.parse, collections, unittest.mock
- solve() must be synchronous (def, not async def) -- use asyncio.run() internally if the topic requires it
- solve() MUST NOT use 'with socket.socket(...) as s:' context manager syntax. Use:
      sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      try:
          ...
      finally:
          sock.close()
  The 'with' pattern breaks monkeypatching because __enter__ returns a different object than the mock.
- Tests must cover: basic success case, error/edge case (ConnectionRefusedError or similar), and a data variation
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

        net = is_network_topic(topic)
        spec, schema_err = _validate_benchmark_json(data, is_network=net)
        if spec is None:
            print(f"[BENCHMARK_GEN] FAIL schema validation: {schema_err}")
            return _unavailable(topic, f"schema error: {schema_err}")

        scaffold = spec.scaffold or "def solve(input_data):\n    pass"
        # Convert _TestCase list to raw dicts for the per-test validator below
        raw_tests = [
            {"description": tc.description, "setup": tc.setup, "assert_expr": tc.assert_expr}
            for tc in spec.tests
        ]

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
                print(f"[BENCHMARK_GEN] [WARN] Test {i} discarded: {verdict['reason']}")

        # No exec-based consistency checks: the scaffold stub always returns None,
        # so running it catches nothing useful that AST + type-homogeneity check below
        # doesn't already catch. The Docker sandbox is the real execution gate.
        consistent_tests = valid_tests
        dominant_type: type | None = dict if is_network_topic(topic) else None

        # Type-homogeneity check: enforce same input_data type across all tests.
        # The LLM sometimes generates mixed types (some tests pass str, others dict).
        # Uses AST inference -- no exec(), no side effects.
        if not is_network_topic(topic):
            type_checked: List[Dict[str, Any]] = []
            for t in consistent_tests:
                t_type, _ = _ast_infer_assignment(t["setup"], "input_data")
                if t_type is None:
                    type_checked.append(t)  # can't infer statically → keep it
                    continue
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

# AST node → Python type mapping for literal values
_AST_TYPE_MAP = {
    ast.Dict:      dict,
    ast.List:      list,
    ast.Tuple:     tuple,
    ast.Set:       set,
    ast.JoinedStr: str,   # f-string
}


def _ast_infer_assignment(source: str, name: str) -> "tuple[type | None, Any]":
    """Parse *source* with AST and return (type, value) of the last assignment to *name*.

    Returns (None, None) if the assignment cannot be statically determined.
    Never executes any code -- pure AST walk, no side effects.

    Handles:
      - Literals: int, float, str, bytes, bool, None, list, dict, tuple, set
      - Negative numeric literals: -1, -3.14
    Does NOT handle:
      - Dynamic values: function calls, comprehensions, variables
      → returns (None, None) so callers fall through gracefully.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, None

    result_type: type | None = None
    result_val: Any = None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == name):
                continue
            val_node = node.value

            # Unwrap unary minus: -1, -3.14
            if (
                isinstance(val_node, ast.UnaryOp)
                and isinstance(val_node.op, ast.USub)
                and isinstance(val_node.operand, ast.Constant)
            ):
                raw = val_node.operand.value
                result_val = -raw
                result_type = type(result_val)
                continue

            # Simple constant (int, float, str, bytes, bool, None)
            if isinstance(val_node, ast.Constant):
                result_val = val_node.value
                result_type = type(result_val)
                continue

            # Compound literals: dict, list, tuple, set
            for ast_cls, py_type in _AST_TYPE_MAP.items():
                if isinstance(val_node, ast_cls):
                    result_type = py_type
                    result_val = None   # value not needed for type checks
                    break

    return result_type, result_val


# ── AST pattern detectors (network mock validation) ───────────────────────────

def _ast_has_with_socket(source: str) -> bool:
    """Return True if *source* contains 'with socket.socket(...) as ...' usage.

    This pattern breaks monkeypatching: __enter__() returns a different MagicMock
    than the one assigned to socket.socket, so recv/send return_values are lost.
    Detected via AST -- no execution, no side effects.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            expr = item.context_expr
            if (
                isinstance(expr, ast.Call)
                and isinstance(expr.func, ast.Attribute)
                and expr.func.attr == "socket"
                and isinstance(expr.func.value, ast.Name)
                and expr.func.value.id == "socket"
            ):
                return True
    return False


def _ast_has_magicmock_side_effect_on_root(source: str) -> bool:
    """Return True if *source* creates MagicMock(side_effect=...) as the root mock.

    The wrong pattern:  _mock = MagicMock(side_effect=ConnectionRefusedError)
    side_effect fires when the mock itself is CALLED (i.e. socket.socket()), not
    when its methods are called (.connect(), .recv(), ...).

    The correct pattern: _mock.connect.side_effect = ConnectionRefusedError
    Detected via AST: assignment whose RHS is a MagicMock call with 'side_effect' kwarg.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        is_magicmock = (
            (isinstance(func, ast.Name) and func.id == "MagicMock")
            or (isinstance(func, ast.Attribute) and func.attr == "MagicMock")
        )
        if not is_magicmock:
            continue
        for kw in call.keywords:
            if kw.arg == "side_effect":
                return True
    return False


def _validate_benchmark_json(
    data: dict,
    is_network: bool,
) -> "tuple[_BenchmarkSpec | None, str]":
    """Validate the LLM-generated benchmark JSON against the required schema.

    Returns ``(_BenchmarkSpec, "")`` on success.
    Returns ``(None, reason)`` on failure -- caller should discard the whole batch.

    Checks performed:
      1. Root is a dict with 'scaffold' (str) and 'tests' (list).
      2. scaffold is syntactically valid Python (ast.parse).
      3. [network only] scaffold must NOT use 'with socket.socket()' pattern.
      4. Each test is a dict with non-empty 'setup' and 'assert_expr' strings.
      5. [network only] setup must NOT use 'with socket.socket()' pattern (AST check).
      6. [network only] setup must NOT use MagicMock(side_effect=...) on root (AST check).

    No exec(), no side effects -- pure structural and AST analysis.
    """
    if not isinstance(data, dict):
        return None, "root is not a dict"

    scaffold = data.get("scaffold")
    if not isinstance(scaffold, str):
        return None, "missing or non-string 'scaffold'"

    raw_tests = data.get("tests")
    if not isinstance(raw_tests, list):
        return None, "missing or non-list 'tests'"

    # Scaffold syntax check
    if scaffold.strip():
        try:
            ast.parse(scaffold)
        except SyntaxError as e:
            return None, f"scaffold SyntaxError: {e}"

    # Network scaffold: ban 'with socket.socket()' context manager
    if is_network and _ast_has_with_socket(scaffold):
        return None, (
            "scaffold uses forbidden 'with socket.socket()' pattern -- "
            "use sock = socket.socket(...); try/finally/sock.close() instead"
        )

    test_cases: list = []
    for i, t in enumerate(raw_tests):
        if not isinstance(t, dict):
            return None, f"test[{i}] is not a dict"
        for key in ("setup", "assert_expr"):
            if not isinstance(t.get(key), str) or not t[key].strip():
                return None, f"test[{i}] missing or empty '{key}'"

        setup = t["setup"].strip()

        if is_network:
            # Red-card #1: with socket.socket() in setup
            if _ast_has_with_socket(setup):
                return None, (
                    f"test[{i}] setup uses forbidden 'with socket.socket()' pattern -- "
                    "use sock = socket.socket(...); try/finally instead"
                )
            # Red-card #2: MagicMock(side_effect=...) on root mock
            if _ast_has_magicmock_side_effect_on_root(setup):
                return None, (
                    f"test[{i}] setup uses MagicMock(side_effect=...) on root mock -- "
                    "use _mock_sock.connect.side_effect = Error instead"
                )

        test_cases.append(_TestCase(
            description=str(t.get("description", f"test_{i}")),
            setup=setup,
            assert_expr=t["assert_expr"].strip(),
        ))

    return _BenchmarkSpec(scaffold=scaffold, tests=test_cases), ""


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


def _validate_test(test: Any, idx: int) -> Dict[str, Any]:
    """Validate a single test-case dict.

    Checks performed:
      1. Is a dict with required keys ('setup', 'assert_expr').
      2. 'assert_expr' starts with the ``assert`` keyword.
      3. No dangerous builtins in setup or assert.
      4. Combined code (setup + assert_expr) is syntactically valid Python (ast.parse).
      5. Static type check via AST: input_data must not be None/bool.
      6. Auto-rewrite assert_expr for float expected values (numpy allclose guard).

    Uses only AST analysis -- no exec(), no side effects, safe for all topic types.
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

    # Static type check via AST -- no exec(), no side effects, works for all topics.
    # Rejects input_data=None and input_data=bool (generation mistakes).
    # Also auto-rewrites assert_expr for float expected values (numpy allclose guard).
    input_type, _ = _ast_infer_assignment(setup, "input_data")
    if input_type in (type(None), bool):
        return {"ok": False, "reason": f"input_data is {input_type.__name__} -- likely a generation mistake"}

    # Auto-rewrite assert for float/list-of-float expected values.
    # Prevents "ValueError: truth value of array ambiguous" when solve() returns numpy.
    boilerplate = "assert solve(input_data) == expected"
    if assert_expr == boilerplate:
        exp_type, exp_val = _ast_infer_assignment(setup, "expected")
        if exp_type is float:
            test["assert_expr"] = "assert abs(solve(input_data) - expected) < 1e-6"
        elif exp_type in (list, tuple) and exp_val is None:
            # Can't inspect list contents statically without eval; leave as-is.
            # The rare numpy array case is handled at runtime by Docker stderr.
            pass

    return {"ok": True}
