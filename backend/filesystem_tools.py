"""
SHARD Filesystem Tools — Sandboxed file operations for Function Calling.

All paths are resolved relative to a workspace directory.
Path traversal outside the workspace is blocked.
All exceptions are caught and returned as readable error strings.
"""

import os

# Max file read size to avoid sending huge payloads to Gemini
MAX_READ_BYTES = 50_000  # ~50KB


def _resolve_safe_path(path: str, workspace: str) -> str:
    """
    Resolve a path relative to workspace and validate it stays inside.
    Returns the resolved absolute path.
    Raises ValueError if the path escapes the workspace.
    """
    workspace = os.path.realpath(workspace)

    # If the path is absolute, try to make it relative to workspace
    if os.path.isabs(path):
        try:
            path = os.path.relpath(path, workspace)
        except ValueError:
            # Different drive on Windows
            raise ValueError(
                f"Access denied: absolute path '{path}' is outside the workspace."
            )

    resolved = os.path.realpath(os.path.join(workspace, path))

    # Security check: resolved path must start with workspace
    if not resolved.startswith(workspace + os.sep) and resolved != workspace:
        raise ValueError(
            f"Access denied: path '{path}' resolves outside the workspace."
        )

    return resolved


def list_directory(path: str, workspace: str) -> str:
    """
    Lists files and folders at a given path inside the workspace.

    Args:
        path: Relative path inside workspace. Use '.' for workspace root.
        workspace: Absolute path to the workspace root.

    Returns:
        A formatted string listing directory contents, or an error message.
    """
    try:
        resolved = _resolve_safe_path(path, workspace)

        if not os.path.exists(resolved):
            return f"Error: directory '{path}' does not exist."

        if not os.path.isdir(resolved):
            return f"Error: '{path}' is not a directory."

        items = os.listdir(resolved)
        if not items:
            return f"Directory '{path}' is empty."

        entries = []
        for item in sorted(items):
            full = os.path.join(resolved, item)
            if os.path.isdir(full):
                entries.append(f"  [DIR]  {item}/")
            else:
                size = os.path.getsize(full)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                entries.append(f"  [FILE] {item}  ({size_str})")

        return f"Contents of '{path}' ({len(items)} items):\n" + "\n".join(entries)

    except ValueError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: permission denied for '{path}'."
    except Exception as e:
        return f"Error listing directory '{path}': {type(e).__name__}: {e}"


def read_file(filepath: str, workspace: str) -> str:
    """
    Reads and returns the content of a text/code file from the workspace.

    Args:
        filepath: Relative path of the file inside workspace.
        workspace: Absolute path to the workspace root.

    Returns:
        The file contents (truncated if too large), or an error message.
    """
    try:
        resolved = _resolve_safe_path(filepath, workspace)

        if not os.path.exists(resolved):
            return f"Error: file '{filepath}' does not exist."

        if not os.path.isfile(resolved):
            return f"Error: '{filepath}' is not a file."

        file_size = os.path.getsize(resolved)

        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read(MAX_READ_BYTES)

        if file_size > MAX_READ_BYTES:
            content += f"\n\n... [TRUNCATED — file is {file_size / 1024:.1f} KB, showing first {MAX_READ_BYTES / 1024:.0f} KB]"

        return content

    except ValueError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: permission denied for '{filepath}'."
    except UnicodeDecodeError:
        return f"Error: '{filepath}' is a binary file and cannot be read as text."
    except Exception as e:
        return f"Error reading file '{filepath}': {type(e).__name__}: {e}"


def write_file(filepath: str, content: str, workspace: str) -> str:
    """
    Writes content to a file in the workspace, creating folders if needed.

    Args:
        filepath: Relative path for the file inside workspace.
        content: The text content to write.
        workspace: Absolute path to the workspace root.

    Returns:
        A success message, or an error message.
    """
    try:
        resolved = _resolve_safe_path(filepath, workspace)

        # Create parent directories
        parent = os.path.dirname(resolved)
        os.makedirs(parent, exist_ok=True)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        size = os.path.getsize(resolved)
        return f"Success: file '{filepath}' written ({size} bytes)."

    except ValueError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: permission denied for '{filepath}'."
    except Exception as e:
        return f"Error writing file '{filepath}': {type(e).__name__}: {e}"
