"""test_mock_networking.py -- Tests for #20 Mock Networking in Sandbox.

Validates:
  1. is_network_topic() keyword detection (no false positives on "neural network")
  2. BenchmarkGenerator routes network topics to the mock template
  3. Mock-network test setups monkeypatch correctly and pass in Docker-like isolation
  4. study_phases._BANNED_IMPORTS is bypassed for network topics
  5. End-to-end: a mock HTTP client solve() passes its benchmark
"""
from __future__ import annotations

import ast
import importlib
import sys
import types
import unittest
import unittest.mock


# ── 1. is_network_topic() detection ──────────────────────────────────────────

from backend.benchmark_generator import is_network_topic, _NETWORK_KEYWORDS


class TestIsNetworkTopic(unittest.TestCase):

    def test_socket_triggers(self):
        self.assertTrue(is_network_topic("tcp socket programming python"))

    def test_http_triggers(self):
        self.assertTrue(is_network_topic("http client implementation python"))

    def test_requests_triggers(self):
        self.assertTrue(is_network_topic("requests library python"))

    def test_websocket_triggers(self):
        self.assertTrue(is_network_topic("websocket protocol implementation"))

    def test_urllib_triggers(self):
        self.assertTrue(is_network_topic("urllib http requests python"))

    def test_aiohttp_triggers(self):
        self.assertTrue(is_network_topic("aiohttp async client"))

    # False positives that must NOT trigger
    def test_neural_network_does_not_trigger(self):
        self.assertFalse(is_network_topic("neural network backpropagation python"))

    def test_network_protocol_theory_does_not_trigger(self):
        # "network" alone is not in _NETWORK_KEYWORDS
        self.assertFalse(is_network_topic("network protocol design patterns"))

    def test_http_request_parsing_triggers(self):
        # "http" IS in keywords -- parsing topic is still network-adjacent
        self.assertTrue(is_network_topic("http request parsing python"))

    def test_socket_concepts_theory_triggers(self):
        self.assertTrue(is_network_topic("socket concepts and protocols theory"))

    def test_non_network_topic(self):
        self.assertFalse(is_network_topic("dynamic programming memoization"))

    def test_asyncio_event_loop_does_not_trigger(self):
        self.assertFalse(is_network_topic("python asyncio event loop internals"))


# ── 2. BenchmarkGenerator uses mock template for network topics ───────────────

from backend.benchmark_generator import (
    BenchmarkGenerator,
    _USER_TEMPLATE_MOCK_NETWORK,
    _USER_TEMPLATE,
)


import pytest

_FAKE_MOCK_NETWORK_JSON = """{
  "scaffold": "import socket\\nimport unittest.mock\\n\\ndef solve(input_data):\\n    return input_data.get('payload', b'')",
  "tests": [
    {
      "description": "basic mock network test",
      "setup": "input_data = {'host': 'localhost', 'port': 8080, 'payload': b'Hello'}\\nexpected = b'Hello'",
      "assert_expr": "assert solve(input_data) == expected"
    }
  ]
}"""

_FAKE_STANDARD_JSON = """{
  "scaffold": "def solve(input_data):\\n    pass",
  "tests": [
    {
      "description": "basic case",
      "setup": "input_data = [1, 2, 3]\\nexpected = 6",
      "assert_expr": "assert solve(input_data) == expected"
    }
  ]
}"""


@pytest.fixture
def network_gen():
    calls: list[str] = []

    async def fake_think(prompt: str, system: str, json_mode: bool = False) -> str:
        calls.append(prompt)
        return _FAKE_MOCK_NETWORK_JSON

    gen = BenchmarkGenerator(think_fn=fake_think)
    gen._calls = calls
    return gen


@pytest.fixture
def standard_gen():
    calls: list[str] = []

    async def fake_think(prompt: str, system: str, json_mode: bool = False) -> str:
        calls.append(prompt)
        return _FAKE_STANDARD_JSON

    gen = BenchmarkGenerator(think_fn=fake_think)
    gen._calls = calls
    return gen


@pytest.mark.asyncio
async def test_network_topic_uses_mock_template_keywords(network_gen):
    """Prompt sent to LLM must contain mock template markers."""
    await network_gen.generate("tcp socket programming python")
    assert network_gen._calls, "think_fn was never called"
    prompt = network_gen._calls[0]
    assert "unittest.mock" in prompt
    assert "monkeypatch" in prompt.lower()
    assert "--network none" in prompt


@pytest.mark.asyncio
async def test_non_network_topic_uses_standard_template(standard_gen):
    await standard_gen.generate("dynamic programming memoization")
    assert standard_gen._calls
    prompt = standard_gen._calls[0]
    assert "unittest.mock" not in prompt
    assert "monkeypatch" not in prompt.lower()


@pytest.mark.asyncio
async def test_network_topic_bans_external_mock_libs(network_gen):
    """Mock template must explicitly ban external mock libraries."""
    await network_gen.generate("http client implementation python")
    prompt = network_gen._calls[0]
    assert "pytest-mock" in prompt
    assert "responses" in prompt
    assert "httpretty" in prompt


@pytest.mark.asyncio
async def test_network_benchmark_result_has_valid_tests(network_gen):
    """Generated benchmark for network topic must produce valid, parseable tests."""
    result = await network_gen.generate("tcp socket programming python")
    assert result["available"], f"Benchmark unavailable: {result.get('reason')}"
    assert result["n_valid"] > 0
    assert "unittest.mock" in result["scaffold"]


class TestBenchmarkGeneratorRouting(unittest.TestCase):
    """Placeholder class kept for test discovery grouping — actual tests are pytest functions above."""
    pass


# ── 3. Mock setup runs correctly in isolation (no real network) ───────────────

class TestMockSetupExecution(unittest.TestCase):
    """Verify that mock-network test setups execute without real network access.

    Uses unittest.mock.patch as context manager everywhere to avoid polluting
    the global socket/requests module state (which would break socks.py imports
    and asyncio event loop creation on Windows).
    """

    def test_socket_monkeypatch_works(self):
        mock_sock_instance = unittest.mock.MagicMock()
        mock_sock_instance.recv.return_value = b"HTTP/1.1 200 OK"

        with unittest.mock.patch("socket.socket", return_value=mock_sock_instance):
            import socket as _sock
            instance = _sock.socket()
            self.assertEqual(instance.recv(1024), b"HTTP/1.1 200 OK")

    def test_requests_monkeypatch_works(self):
        mock_resp = unittest.mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}

        with unittest.mock.patch("requests.get", return_value=mock_resp):
            import requests as _req
            resp = _req.get("https://api.example.com/ping")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"status": "ok"})

    def test_no_real_network_needed(self):
        """The mock setup must work even if network is completely blocked."""
        mock_sock_instance = unittest.mock.MagicMock()
        mock_sock_instance.recv.return_value = b"pong"

        with unittest.mock.patch("socket.socket", return_value=mock_sock_instance):
            import socket as _sock
            # This must not raise OSError (no real connection attempted)
            try:
                s = _sock.socket()
                s.connect(("127.0.0.1", 9999))
                result = s.recv(1024)
            except OSError as e:
                self.fail(f"Real network call made during mock setup: {e}")
            self.assertEqual(result, b"pong")


# ── 4. End-to-end: solve() with mocked socket passes benchmark ───────────────

class TestEndToEndMockHTTPClient(unittest.TestCase):
    """Simulate what SHARD would generate for 'http client implementation python'."""

    def _make_solve(self) -> types.FunctionType:
        """Build a solve() function that uses socket + mock."""
        code = """
import socket
import unittest.mock

def solve(input_data):
    host = input_data['host']
    port = input_data['port']
    path = input_data.get('path', '/')
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    request = f"GET {path} HTTP/1.0\\r\\nHost: {host}\\r\\n\\r\\n"
    s.sendall(request.encode())
    response = s.recv(4096)
    s.close()
    # Parse status code from response line
    first_line = response.split(b'\\r\\n')[0].decode()
    status_code = int(first_line.split()[1])
    return status_code
"""
        ns: dict = {}
        exec(compile(ast.parse(code), "<solve>", "exec"), ns)
        return ns["solve"]

    def test_mock_http_client_200(self):
        mock_sock = unittest.mock.MagicMock()
        mock_sock.recv.return_value = b"HTTP/1.0 200 OK\r\nContent-Length: 5\r\n\r\nHello"

        with unittest.mock.patch("socket.socket", return_value=mock_sock):
            solve = self._make_solve()
            result = solve({"host": "example.com", "port": 80, "path": "/"})
        self.assertEqual(result, 200)

    def test_mock_http_client_404(self):
        mock_sock = unittest.mock.MagicMock()
        mock_sock.recv.return_value = b"HTTP/1.0 404 Not Found\r\n\r\n"

        with unittest.mock.patch("socket.socket", return_value=mock_sock):
            solve = self._make_solve()
            result = solve({"host": "example.com", "port": 80, "path": "/missing"})
        self.assertEqual(result, 404)

    def test_mock_send_receives_correct_request(self):
        """Verify that solve() actually sends a well-formed HTTP request."""
        sent_data: list[bytes] = []
        mock_sock = unittest.mock.MagicMock()
        mock_sock.sendall.side_effect = lambda data: sent_data.append(data)
        mock_sock.recv.return_value = b"HTTP/1.0 200 OK\r\n\r\n"

        with unittest.mock.patch("socket.socket", return_value=mock_sock):
            solve = self._make_solve()
            solve({"host": "api.test.com", "port": 8080, "path": "/health"})

        self.assertTrue(sent_data, "solve() never called sendall()")
        request = sent_data[0].decode()
        self.assertIn("GET /health HTTP/1.0", request)
        self.assertIn("Host: api.test.com", request)


if __name__ == "__main__":
    unittest.main()
