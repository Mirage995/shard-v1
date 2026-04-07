# SHARD — Claude Code Instructions

This file is loaded every session. Follow all rules below without exception.

## SHARD-specific rules

- **Read the source before patching.** Never modify a file without reading it first in the current session.
- **Diagnose before implementing.** For any bug: state the root cause explicitly before writing a single line of fix.
- **One commit per logical unit.** Don't batch unrelated changes.
- **Test suite must stay green.** Run `python -m pytest tests/` before declaring any session complete.
- **Budget awareness.** Token-heavy operations (swarm, benchmark runs) should be validated on small tasks first.
