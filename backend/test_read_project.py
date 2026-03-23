import os
import sys

# Add backend to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from filesystem_tools import read_project_file

def test_valid_file():
    path = os.path.abspath(__file__) # This file itself (.py)
    try:
        content = read_project_file(path)
        assert len(content) > 0
        print("test_valid_file PASSED")
    except Exception as e:
        print(f"test_valid_file FAILED: {e}")
        raise e

def test_dot_env():
    path = r"C:\Users\andre\desktop\shard_v1\.env"
    try:
        read_project_file(path)
        print("test_dot_env FAILED (allowed .env)")
        assert False
    except PermissionError as e:
        print("test_dot_env PASSED (blocked .env)")
        assert "is blacklisted" in str(e)

def test_blacklist_keyword():
    path = r"C:\Users\andre\desktop\shard_v1\passwords.txt"
    try:
        read_project_file(path)
        print("test_blacklist_keyword FAILED")
        assert False
    except PermissionError as e:
        print("test_blacklist_keyword PASSED")
        assert "blacklist keywords" in str(e)

def test_invalid_extension():
    path = r"C:\Users\andre\desktop\shard_v1\image.png"
    try:
        read_project_file(path)
        print("test_invalid_extension FAILED")
        assert False
    except PermissionError as e:
        print("test_invalid_extension PASSED")
        assert "is not allowed" in str(e)

def test_outside_path():
    path = r"C:\Users\andre\desktop\dummy.txt"
    try:
        read_project_file(path)
        print("test_outside_path FAILED")
        assert False
    except PermissionError as e:
        print("test_outside_path PASSED")
        assert "outside the allowed" in str(e)

def main():
    test_valid_file()
    test_dot_env()
    test_blacklist_keyword()
    test_invalid_extension()
    test_outside_path()
    print("All read_project_file tests PASSED")

if __name__ == "__main__":
    main()
