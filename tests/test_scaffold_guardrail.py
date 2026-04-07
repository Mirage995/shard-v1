"""Tests for scaffold_guardrail.py — L1 (syntax), L2 (security), L3 (principles)."""
import pytest
from backend.scaffold_guardrail import GuardrailGate, GuardrailResult, GuardrailHardBlock


# ── L1: Syntax ─────────────────────────────────────────────────────────────────

def test_l1_valid_code_passes():
    result = GuardrailGate().check("x = 1 + 2\nprint(x)")
    assert result.ok

def test_l1_syntax_error_blocked():
    result = GuardrailGate().check("def foo(:\n    pass")
    assert not result.ok
    assert result.level == "L1"
    assert any("syntax" in v.lower() or "L1" in v for v in result.violations)

def test_l1_rejection_reason_is_actionable():
    result = GuardrailGate().check("class Bad(\n    pass")
    assert result.rejection_reason is not None
    assert len(result.rejection_reason) > 10


# ── L2: Security ───────────────────────────────────────────────────────────────

def test_l2_os_system_blocked():
    result = GuardrailGate().check("import os\nos.system('rm -rf /')")
    assert not result.ok
    assert result.level == "L2"

def test_l2_os_popen_blocked():
    result = GuardrailGate().check("import os\nos.popen('cat /etc/passwd')")
    assert not result.ok
    assert result.level == "L2"

def test_l2_subprocess_shell_true_blocked():
    result = GuardrailGate().check("import subprocess\nsubprocess.run('ls', shell=True)")
    assert not result.ok
    assert result.level == "L2"

def test_l2_subprocess_shell_false_passes():
    result = GuardrailGate().check("import subprocess\nsubprocess.run(['ls', '-la'], shell=False)")
    assert result.ok

def test_l2_eval_dynamic_blocked():
    result = GuardrailGate().check("data = get_data()\neval(data)")
    assert not result.ok
    assert result.level == "L2"

def test_l2_eval_literal_passes():
    result = GuardrailGate().check("x = eval('1 + 2')")
    assert result.ok

def test_l2_exec_dynamic_blocked():
    result = GuardrailGate().check("code = build_code()\nexec(code)")
    assert not result.ok
    assert result.level == "L2"

def test_l2_socket_import_blocked():
    result = GuardrailGate().check("import socket\ns = socket.socket()")
    assert not result.ok
    assert result.level == "L2"

def test_l2_requests_import_blocked():
    result = GuardrailGate().check("import requests\nrequests.get('http://example.com')")
    assert not result.ok
    assert result.level == "L2"

def test_l2_shutil_rmtree_blocked():
    result = GuardrailGate().check("import shutil\nshutil.rmtree('shard_memory/')")
    assert not result.ok
    assert result.level == "L2"

def test_l2_write_to_shard_memory_blocked():
    result = GuardrailGate().check(
        "with open('shard_memory/identity.json', 'w') as f:\n    f.write('{}')"
    )
    assert not result.ok
    assert result.level == "L2"

def test_l2_write_to_backend_blocked():
    result = GuardrailGate().check("open('backend/capability_graph.py', 'w').write('')")
    assert not result.ok
    assert result.level == "L2"

def test_l2_write_to_tmp_passes():
    result = GuardrailGate().check(
        "with open('/tmp/output.txt', 'w') as f:\n    f.write('hello')"
    )
    assert result.ok

def test_l2_read_from_shard_memory_passes():
    result = GuardrailGate().check(
        "with open('shard_memory/identity.json', 'r') as f:\n    data = f.read()"
    )
    assert result.ok

def test_l2_violation_includes_actionable_reason():
    result = GuardrailGate().check("import os\nos.system('echo hello')")
    assert result.rejection_reason is not None
    assert "os.system" in result.rejection_reason or "security" in result.rejection_reason.lower()


# ── L3: Principles / SHARD invariants ──────────────────────────────────────────

def test_l3_write_principles_json_blocked():
    result = GuardrailGate().check("with open('principles.json', 'w') as f:\n    f.write('[]')")
    assert not result.ok
    assert result.level in ("L2", "L3")

def test_l3_override_builtins_blocked():
    result = GuardrailGate().check("__builtins__ = {}\nprint('hello')")
    assert not result.ok
    assert result.level == "L3"

def test_l3_write_claude_md_blocked():
    result = GuardrailGate().check("open('CLAUDE.md', 'w').write('# hacked')")
    assert not result.ok

def test_l3_safe_algorithm_passes():
    result = GuardrailGate().check("""
def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
""")
    assert result.ok


# ── GuardrailResult fields ──────────────────────────────────────────────────────

def test_result_ok_has_no_violations():
    result = GuardrailGate().check("x = 42")
    assert result.ok
    assert result.violations == []
    assert result.rejection_reason is None
    assert result.level is None

def test_result_blocked_has_all_fields():
    result = GuardrailGate().check("import socket")
    assert not result.ok
    assert len(result.violations) > 0
    assert result.rejection_reason is not None
    assert result.level is not None
