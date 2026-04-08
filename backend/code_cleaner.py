"""code_cleaner.py -- AST-based rewriter for LLM-generated network code.

Transforms patterns that break unittest.mock monkeypatching into equivalent
patterns that are mock-safe.  Applied silently before sandbox execution so
that broken mock interactions never cause spurious test failures.

Currently handled:
  - 'with socket.socket(...) as s:' → assignment + try/finally + s.close()
    Reason: __enter__() returns a fresh MagicMock that ignores recv.return_value.

Usage:
    from backend.code_cleaner import clean_network_code
    fixed = clean_network_code(source)   # idempotent, returns source on error
"""
from __future__ import annotations

import ast
import textwrap


# ── AST helper ────────────────────────────────────────────────────────────────

def _is_socket_ctor(expr: ast.expr) -> bool:
    """Return True if *expr* is a call to socket.socket(...) or socket.SOCK_*."""
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    # socket.socket(...)
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "socket"
        and isinstance(func.value, ast.Name)
        and func.value.id == "socket"
    )


# ── NodeTransformer ───────────────────────────────────────────────────────────

class _SocketWithRewriter(ast.NodeTransformer):
    """Rewrites 'with socket.socket(...) as s:' to the try/finally pattern.

    Before:
        with socket.socket(AF, TYPE) as s:
            s.sendto(data, addr)
            result = s.recv(1024)

    After:
        s = socket.socket(AF, TYPE)
        try:
            s.sendto(data, addr)
            result = s.recv(1024)
        finally:
            s.close()

    Only rewrites single-item With statements to avoid breaking unrelated
    context managers (e.g. 'with open(...) as f:').
    """

    def visit_With(self, node: ast.With):
        # Recurse into children first (handles nested with statements)
        self.generic_visit(node)

        # Only rewrite single-item with statements
        if len(node.items) != 1:
            return node

        item = node.items[0]
        ctx_expr = item.context_expr
        var = item.optional_vars  # ast.Name for 'as s', or None

        if not _is_socket_ctor(ctx_expr):
            return node

        # No 'as' clause — wrap body in try/finally without a close call
        # (rare, but handle gracefully)
        if var is None:
            return ast.Try(
                body=node.body,
                handlers=[],
                orelse=[],
                finalbody=[ast.Expr(value=ast.Constant(value=None))],
                lineno=node.lineno,
                col_offset=node.col_offset,
            )

        # Build:  var = socket.socket(...)
        assign = ast.Assign(
            targets=[ast.Name(id=var.id, ctx=ast.Store())],
            value=ctx_expr,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )

        # Build:  finally: var.close()
        close_stmt = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=var.id, ctx=ast.Load()),
                    attr="close",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
        )

        # Build:  try: [body] finally: var.close()
        try_node = ast.Try(
            body=node.body,
            handlers=[],
            orelse=[],
            finalbody=[close_stmt],
            lineno=node.lineno,
            col_offset=node.col_offset,
        )

        # NodeTransformer supports returning a list to replace one node with many
        return [assign, try_node]


# ── RecvfromMockPatcher ───────────────────────────────────────────────────────

class _RecvfromMockPatcher(ast.NodeTransformer):
    """AST patcher that injects missing ``recvfrom.return_value`` into test harnesses.

    Problem: LLMs generating UDP benchmark tests typically write:
        _mock_sock.recv.return_value = b'data'
    …but the solve() function calls ``sock.recvfrom(1024)`` which returns a
    MagicMock (not a tuple), causing ``ValueError: not enough values to unpack``.

    This patcher detects:
      1. Any ``recvfrom(`` call anywhere in the file (inside solve or test)
      2. A module-level ``<var>.recv.return_value = <expr>`` assignment
      3. Absence of ``<var>.recvfrom.return_value`` assignment

    When all three conditions hold it inserts:
      ``<var>.recvfrom.return_value = (b'response_data', ('127.0.0.1', 12345))``
    immediately after the ``recv.return_value`` assignment.
    """

    def __init__(self) -> None:
        self.has_recvfrom_call: bool = False
        self.has_recvfrom_mock: bool = False

    # ── Pass 1: collect facts ──────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> ast.Call:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "recvfrom":
            self.has_recvfrom_call = True
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> ast.Assign:
        t = node.targets[0] if node.targets else None
        if (
            isinstance(t, ast.Attribute)
            and t.attr == "return_value"
            and isinstance(t.value, ast.Attribute)
            and t.value.attr == "recvfrom"
        ):
            self.has_recvfrom_mock = True
        return self.generic_visit(node)

    # ── Pass 2: inject (module-level scan only) ────────────────────────────────

    def finalize(self, tree: ast.Module) -> ast.Module:
        """Insert recvfrom mock right after recv.return_value assignment if needed."""
        if not self.has_recvfrom_call or self.has_recvfrom_mock:
            return tree  # nothing to do

        # Find the recv.return_value assignment at module level
        insert_after: int = -1
        mock_var: str = "_mock_sock"
        for i, node in enumerate(tree.body):
            if not isinstance(node, ast.Assign):
                continue
            t = node.targets[0] if node.targets else None
            if (
                isinstance(t, ast.Attribute)
                and t.attr == "return_value"
                and isinstance(t.value, ast.Attribute)
                and t.value.attr == "recv"
                and isinstance(t.value.value, ast.Name)
            ):
                insert_after = i
                mock_var = t.value.value.id
                break

        if insert_after < 0:
            return tree  # no recv.return_value at module level — leave as-is

        inject_src = (
            f"{mock_var}.recvfrom.return_value = "
            f"(b'response_data', ('127.0.0.1', 12345))"
        )
        inject_node = ast.parse(inject_src).body[0]
        ast.fix_missing_locations(inject_node)
        tree.body.insert(insert_after + 1, inject_node)
        return tree


def patch_recvfrom_mock(source: str) -> str:
    """Inject ``<mock>.recvfrom.return_value`` if recvfrom is called but not mocked.

    Idempotent and fail-safe: returns original source on any parse/unparse error.

    Args:
        source: Python source code for a benchmark test harness.

    Returns:
        Patched source (or original if no patch needed / error).
    """
    if "recvfrom" not in source:
        return source  # fast exit

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source  # unparseable — leave as-is

    patcher = _RecvfromMockPatcher()
    patcher.visit(tree)
    tree = patcher.finalize(tree)
    ast.fix_missing_locations(tree)

    try:
        return ast.unparse(tree)
    except Exception:
        return source


# ── Session metrics ───────────────────────────────────────────────────────────

_SESSION_METRICS: dict = {
    "rewrites_applied": 0,   # times clean_network_code actually rewrote code
    "fast_exits":       0,   # times source had no 'with socket.socket' → skipped
    "parse_errors":     0,   # times ast.parse failed → returned original
}


def get_session_metrics() -> dict:
    """Return a copy of the current session metrics."""
    return dict(_SESSION_METRICS)


def reset_session_metrics() -> None:
    """Reset all counters to zero (call at session start)."""
    for k in _SESSION_METRICS:
        _SESSION_METRICS[k] = 0


# ── Public API ────────────────────────────────────────────────────────────────

def clean_network_code(source: str) -> str:
    """Rewrite *source* so that 'with socket.socket()' uses try/finally instead.

    Idempotent: if no rewrite is needed the original source is returned unchanged.
    Returns the original source on any parse/unparse error (fail-safe).

    Args:
        source: Python source code string (may contain markdown fences — stripped
                automatically if present).

    Returns:
        Cleaned Python source string.
    """
    # Quick exit: no 'with socket.socket' in source → nothing to do (preserves original)
    if "with socket.socket" not in source:
        _SESSION_METRICS["fast_exits"] += 1
        return source

    # Strip markdown fences if present (only when rewrite is needed)
    lines = source.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    source = "\n".join(lines)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        _SESSION_METRICS["parse_errors"] += 1
        return source  # unparseable — leave as-is, sandbox will report the error

    rewriter = _SocketWithRewriter()
    new_tree = rewriter.visit(tree)
    ast.fix_missing_locations(new_tree)

    try:
        result = ast.unparse(new_tree)
        if result != source:
            _SESSION_METRICS["rewrites_applied"] += 1
        return result
    except Exception:
        return source  # unparse failed — leave as-is
