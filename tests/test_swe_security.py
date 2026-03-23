"""Security gate tests for SWEAgent — comprehensive AST violation coverage.

These tests exist to ensure the security boundaries NEVER regress.
If any of these tests start failing, stop and investigate immediately.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from swe_agent import (
    FORBIDDEN_CALLS,
    FORBIDDEN_IMPORTS,
    PATCH_FORBIDDEN_CALLS,
    validate_code_safety,
    validate_patch_safety,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe(code: str) -> bool:
    ok, _ = validate_code_safety(code)
    return ok


def patch_safe(code: str) -> bool:
    ok, _ = validate_patch_safety(code)
    return ok


def violations(code: str) -> list[str]:
    _, v = validate_code_safety(code)
    return v


# ── Forbidden imports (heavy gate) ────────────────────────────────────────────

class TestForbiddenImports(unittest.TestCase):

    def _assert_blocked(self, code: str):
        self.assertFalse(safe(code), f"Expected rejection:\n{code}")

    def test_os_import(self):
        self._assert_blocked("import os")

    def test_sys_import(self):
        self._assert_blocked("import sys")

    def test_subprocess_import(self):
        self._assert_blocked("import subprocess")

    def test_socket_import(self):
        self._assert_blocked("import socket")

    def test_requests_import(self):
        self._assert_blocked("import requests")

    def test_pickle_import(self):
        self._assert_blocked("import pickle")

    def test_ctypes_import(self):
        self._assert_blocked("import ctypes")

    def test_importlib_import(self):
        self._assert_blocked("import importlib")

    def test_multiprocessing_import(self):
        self._assert_blocked("import multiprocessing")

    def test_builtins_import(self):
        self._assert_blocked("import builtins")

    def test_base64_import(self):
        self._assert_blocked("import base64")

    def test_zipfile_import(self):
        self._assert_blocked("import zipfile")

    def test_from_os_import(self):
        self._assert_blocked("from os import path")

    def test_from_os_path_import(self):
        self._assert_blocked("from os.path import join")

    def test_from_subprocess_import(self):
        self._assert_blocked("from subprocess import Popen")

    def test_from_socket_import(self):
        self._assert_blocked("from socket import socket")


# ── Forbidden calls (heavy gate) ──────────────────────────────────────────────

class TestForbiddenCalls(unittest.TestCase):

    def _assert_blocked(self, code: str):
        self.assertFalse(safe(code), f"Expected rejection:\n{code}")

    def test_eval_direct(self):
        self._assert_blocked("x = eval('1+1')")

    def test_exec_direct(self):
        self._assert_blocked("exec('print(1)')")

    def test_compile_direct(self):
        self._assert_blocked("c = compile('1', '<s>', 'eval')")

    def test_import_dunder(self):
        self._assert_blocked("m = __import__('os')")

    def test_globals_call(self):
        self._assert_blocked("g = globals()")

    def test_locals_call(self):
        self._assert_blocked("l = locals()")

    def test_vars_call(self):
        self._assert_blocked("v = vars()")

    def test_breakpoint_call(self):
        self._assert_blocked("breakpoint()")

    def test_memoryview_call(self):
        self._assert_blocked("mv = memoryview(b'data')")

    def test_attribute_eval(self):
        # obj.eval(...) must also be caught
        self._assert_blocked("x.eval('code')")

    def test_getattr_eval(self):
        self._assert_blocked("getattr(obj, 'eval')")

    def test_getattr_exec(self):
        self._assert_blocked("getattr(obj, 'exec')")


# ── Dangerous dunder attributes ───────────────────────────────────────────────

class TestDangerousDunders(unittest.TestCase):

    def _assert_blocked(self, code: str):
        self.assertFalse(safe(code), f"Expected rejection:\n{code}")

    def test_class_access(self):
        self._assert_blocked("t = ().__class__")

    def test_bases_access(self):
        self._assert_blocked("b = ().__class__.__bases__")

    def test_subclasses_access(self):
        self._assert_blocked("s = object.__subclasses__()")

    def test_globals_attr(self):
        self._assert_blocked("g = foo.__globals__")

    def test_builtins_attr(self):
        self._assert_blocked("b = foo.__builtins__")

    def test_code_attr(self):
        self._assert_blocked("c = foo.__code__")

    def test_closure_attr(self):
        self._assert_blocked("c = foo.__closure__")


# ── Classic sandbox-escape patterns ───────────────────────────────────────────

class TestSandboxEscapePatterns(unittest.TestCase):

    def _assert_blocked(self, code: str):
        self.assertFalse(safe(code), f"Expected rejection:\n{code}")

    def test_subclasses_escape(self):
        # ().__class__.__bases__[0].__subclasses__() — typical escape chain
        self._assert_blocked(
            "x = ().__class__.__bases__[0].__subclasses__()"
        )

    def test_exec_via_getattr(self):
        self._assert_blocked("getattr(__builtins__, 'exec')('import os')")

    def test_eval_in_nested_function(self):
        self._assert_blocked(
            "def foo():\n"
            "    def bar():\n"
            "        return eval('1+1')\n"
            "    return bar()\n"
        )

    def test_exec_in_class_body(self):
        self._assert_blocked(
            "class Foo:\n"
            "    exec('import os')\n"
        )

    def test_import_via_dunder(self):
        self._assert_blocked("os = __import__('os')")


# ── Safe code must NOT be blocked ─────────────────────────────────────────────

class TestSafeCodeAllowed(unittest.TestCase):

    def _assert_allowed(self, code: str):
        self.assertTrue(safe(code), f"Expected to be allowed:\n{code}\nViolations: {violations(code)}")

    def test_simple_function(self):
        self._assert_allowed("def add(a, b):\n    return a + b\n")

    def test_class_definition(self):
        self._assert_allowed(
            "class Stack:\n"
            "    def __init__(self):\n"
            "        self.items = []\n"
            "    def push(self, x):\n"
            "        self.items.append(x)\n"
        )

    def test_math_import(self):
        self._assert_allowed("import math\nx = math.sqrt(16)")

    def test_json_import(self):
        self._assert_allowed("import json\ndata = json.loads('{}')")

    def test_datetime_import(self):
        self._assert_allowed("from datetime import datetime\nnow = datetime.now()")

    def test_collections_import(self):
        self._assert_allowed("from collections import defaultdict, deque\nd = defaultdict(list)")

    def test_typing_import(self):
        self._assert_allowed("from typing import List, Dict, Optional\ndef f(x: Optional[int]) -> List[str]: ...")

    def test_async_function(self):
        self._assert_allowed("import asyncio\n\nasync def sleep():\n    await asyncio.sleep(1)\n")

    def test_list_comprehension(self):
        self._assert_allowed("result = [x ** 2 for x in range(10)]")

    def test_format_string(self):
        self._assert_allowed("name = 'world'\nprint(f'Hello, {name}!')")


# ── Light patch gate vs heavy gate ────────────────────────────────────────────

class TestPatchGateVsHeavyGate(unittest.TestCase):

    def test_os_blocked_by_heavy_but_allowed_by_patch(self):
        code = "import os\nos.makedirs('/tmp', exist_ok=True)\n"
        heavy_ok, _ = validate_code_safety(code)
        patch_ok, _ = validate_patch_safety(code)
        self.assertFalse(heavy_ok)
        self.assertTrue(patch_ok)

    def test_subprocess_blocked_by_heavy_allowed_by_patch(self):
        code = "import subprocess\nsubprocess.run(['ls'])\n"
        heavy_ok, _ = validate_code_safety(code)
        patch_ok, _ = validate_patch_safety(code)
        self.assertFalse(heavy_ok)
        self.assertTrue(patch_ok)

    def test_eval_blocked_by_both_gates(self):
        code = "x = eval('1+1')\n"
        heavy_ok, _ = validate_code_safety(code)
        patch_ok, _ = validate_patch_safety(code)
        self.assertFalse(heavy_ok)
        self.assertFalse(patch_ok)

    def test_exec_blocked_by_both_gates(self):
        code = "exec('pass')\n"
        heavy_ok, _ = validate_code_safety(code)
        patch_ok, _ = validate_patch_safety(code)
        self.assertFalse(heavy_ok)
        self.assertFalse(patch_ok)

    def test_compile_blocked_by_both_gates(self):
        code = "c = compile('1', '<s>', 'eval')\n"
        heavy_ok, _ = validate_code_safety(code)
        patch_ok, _ = validate_patch_safety(code)
        self.assertFalse(heavy_ok)
        self.assertFalse(patch_ok)

    def test_syntax_error_blocked_by_both(self):
        code = "def foo(\n    pass\n"
        heavy_ok, _ = validate_code_safety(code)
        patch_ok, _ = validate_patch_safety(code)
        self.assertFalse(heavy_ok)
        self.assertFalse(patch_ok)


# ── Forbidden sets completeness ────────────────────────────────────────────────

class TestForbiddenSetCompleteness(unittest.TestCase):
    """Ensure the forbidden sets contain the critical entries."""

    CRITICAL_FORBIDDEN_IMPORTS = {
        "os", "sys", "subprocess", "socket", "pickle",
        "ctypes", "importlib", "multiprocessing", "builtins",
    }

    CRITICAL_FORBIDDEN_CALLS = {
        "eval", "exec", "compile", "__import__",
    }

    def test_critical_imports_present(self):
        missing = self.CRITICAL_FORBIDDEN_IMPORTS - FORBIDDEN_IMPORTS
        self.assertEqual(missing, set(), f"Missing from FORBIDDEN_IMPORTS: {missing}")

    def test_critical_calls_present(self):
        missing = self.CRITICAL_FORBIDDEN_CALLS - FORBIDDEN_CALLS
        self.assertEqual(missing, set(), f"Missing from FORBIDDEN_CALLS: {missing}")

    def test_patch_forbidden_calls_subset(self):
        # Every call forbidden in the patch gate must also be in the heavy gate
        missing = PATCH_FORBIDDEN_CALLS - FORBIDDEN_CALLS
        self.assertEqual(missing, set(), f"PATCH_FORBIDDEN_CALLS has entries not in FORBIDDEN_CALLS: {missing}")


if __name__ == "__main__":
    unittest.main()
