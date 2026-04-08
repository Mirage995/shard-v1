"""Tests for backend/code_cleaner.py -- AST-based socket rewriter."""
import textwrap

import pytest

from backend.code_cleaner import clean_network_code


def _d(code: str) -> str:
    """Dedent helper."""
    return textwrap.dedent(code).strip() + "\n"


TCP_WITH = _d("""
    import socket

    def solve(input_data):
        host, port = input_data['host'], input_data['port']
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            return s.recv(1024)
""")

UDP_WITH = _d("""
    import socket, struct

    def solve(input_data):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.sendto(b'ping', (input_data['host'], input_data['port']))
            data, addr = sock.recvfrom(1024)
            return data
""")

ALREADY_CLEAN = _d("""
    import socket

    def solve(input_data):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(('h', 80))
            return s.recv(1024)
        finally:
            s.close()
""")

FILE_OPEN = _d("""
    def solve(input_data):
        with open(input_data['path']) as f:
            return f.read()
""")

PURE = "def solve(x):\n    return x * 2\n"

SYNTAX_ERROR = "def solve(x\n    return x"


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestCleanNetworkCode:

    def test_tcp_with_socket_rewritten(self):
        result = clean_network_code(TCP_WITH)
        assert "with socket.socket" not in result
        assert "s = socket.socket" in result
        assert "try:" in result
        assert "s.close()" in result

    def test_udp_with_socket_rewritten(self):
        result = clean_network_code(UDP_WITH)
        assert "with socket.socket" not in result
        assert "sock = socket.socket" in result
        assert "sock.close()" in result

    def test_already_clean_unchanged(self):
        """Code without 'with socket.socket' should not be modified."""
        result = clean_network_code(ALREADY_CLEAN)
        assert "with socket.socket" not in result
        assert "try:" in result
        assert "s.close()" in result

    def test_non_socket_with_untouched(self):
        """'with open(...)' must never be rewritten."""
        result = clean_network_code(FILE_OPEN)
        assert "with open" in result

    def test_no_socket_fast_exit(self):
        """Code without any 'socket' string is returned unchanged immediately."""
        result = clean_network_code(PURE)
        assert result == PURE

    def test_syntax_error_safe_fallback(self):
        """Unparseable code is returned as-is without raising."""
        result = clean_network_code(SYNTAX_ERROR)
        assert result == SYNTAX_ERROR

    def test_idempotent(self):
        """Applying clean_network_code twice gives the same result."""
        once = clean_network_code(TCP_WITH)
        twice = clean_network_code(once)
        assert once == twice

    def test_markdown_fences_stripped(self):
        """Source with markdown code fences is cleaned correctly."""
        fenced = "```python\n" + TCP_WITH + "```\n"
        result = clean_network_code(fenced)
        assert "with socket.socket" not in result
        assert "s = socket.socket" in result

    def test_nested_with_preserved(self):
        """'with socket.socket() as s: with something_else as t:' -- inner with untouched."""
        code = _d("""
            import socket

            def solve(d):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    with open('log.txt', 'w') as f:
                        f.write('connected')
                    return s.recv(1024)
        """)
        result = clean_network_code(code)
        assert "with socket.socket" not in result
        assert "s = socket.socket" in result
        # Inner 'with open' should remain as-is
        assert "with open" in result
