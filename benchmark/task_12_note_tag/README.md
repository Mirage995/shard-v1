# Task 12 — Note Tag Matcher

A comment tag detector scans source code for fixme-style tags like `# TODO:` or `# FIXME:`.

Users report that tags made entirely of punctuation (e.g. `???`) are never detected, even when explicitly configured. Alphanumeric tags work correctly.

**Write:** `fixed_processor.py`

---
*Derived from: pylint-dev/pylint#5859*
