# Task 10 — Template Parser

A message template parser extracts field names from format strings like `{category}` or `{line:03d}`.

Users report that templates with custom JSON-style braces — like `{{ "Category": "{category}" }}` — trigger spurious warnings about unknown fields.

**Write:** `fixed_processor.py`

---
*Derived from: pylint-dev/pylint#7993*
