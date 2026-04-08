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
        return source  # unparseable — leave as-is, sandbox will report the error

    rewriter = _SocketWithRewriter()
    new_tree = rewriter.visit(tree)
    ast.fix_missing_locations(new_tree)

    try:
        return ast.unparse(new_tree)
    except Exception:
        return source  # unparse failed — leave as-is
