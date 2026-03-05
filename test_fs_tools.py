"""Standalone test for filesystem_tools.py — sandboxing and all 3 functions."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from filesystem_tools import list_directory, read_file, write_file

ws = tempfile.mkdtemp()
print(f"Workspace: {ws}\n")

# 1. write_file basic
r = write_file("test.txt", "ciao Boss!", ws)
assert "success" in r.lower(), f"FAIL write: {r}"
print(f"[OK] WRITE: {r}")

# 2. read_file basic
r = read_file("test.txt", ws)
assert "ciao Boss!" in r, f"FAIL read: {r}"
print(f"[OK] READ: {r}")

# 3. list_directory basic
r = list_directory(".", ws)
assert "test.txt" in r, f"FAIL list: {r}"
print(f"[OK] LIST:\n{r}")

# 4. Path traversal BLOCKED (write)
r = write_file("../evil.txt", "hack", ws)
assert "denied" in r.lower() or "error" in r.lower(), f"FAIL traversal write: {r}"
print(f"[OK] TRAVERSAL WRITE BLOCKED: {r}")

# 5. Path traversal BLOCKED (read)
r = read_file("../../etc/passwd", ws)
assert "denied" in r.lower() or "error" in r.lower(), f"FAIL traversal read: {r}"
print(f"[OK] TRAVERSAL READ BLOCKED: {r}")

# 6. Missing file
r = read_file("nonexistent.txt", ws)
assert "error" in r.lower(), f"FAIL missing file: {r}"
print(f"[OK] MISSING FILE: {r}")

# 7. Missing directory
r = list_directory("nonexistent_dir", ws)
assert "error" in r.lower(), f"FAIL missing dir: {r}"
print(f"[OK] MISSING DIR: {r}")

# 8. Deep nested write (auto-create dirs)
r = write_file("sub/deep/file.json", '{"level": 1}', ws)
assert "success" in r.lower(), f"FAIL deep write: {r}"
print(f"[OK] DEEP WRITE: {r}")

# 9. Deep nested list
r = list_directory("sub/deep", ws)
assert "file.json" in r, f"FAIL deep list: {r}"
print(f"[OK] DEEP LIST:\n{r}")

print("\n=== ALL 9 TESTS PASSED ===")
