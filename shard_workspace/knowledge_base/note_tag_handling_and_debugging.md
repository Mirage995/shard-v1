# note tag handling and debugging — SHARD Cheat Sheet

## Context
This knowledge base covers detecting "note tags" (TODO, FIXME, ???, etc.) in
Python source code comments using regex. The task is to build a robust
`find_tags(source, notes)` function that returns which tags appear in comment lines.

## Key Pattern: Word Boundary Bug with Punctuation Tags

`\b` (word boundary) only works for alphanumeric tags. It FAILS for punctuation
tags like `???`, `!`, `XXX` because `\b` requires a word↔non-word transition.

```python
# WRONG — \b after ??? never matches (? is non-word, colon is non-word)
pattern = rf"#\s*({'|'.join(re.escape(n) for n in notes)})\b"

# RIGHT — conditional boundary based on tag character type
def _build_pattern(notes):
    parts = []
    for note in notes:
        escaped = re.escape(note)
        # \b only for tags ending with word characters (alphanumeric/_)
        if re.search(r'\w$', note):
            parts.append(escaped + r'\b')
        else:
            parts.append(escaped)  # punctuation tags can't extend into word chars
    return re.compile(rf"#\s*({'|'.join(parts)})", re.IGNORECASE)
```

## Complete Robust Implementation

```python
import re

class NoteTagProcessor:
    def find_tags(self, source: str, notes: list[str], notes_rgx: str = "") -> list[str]:
        """Return list of matched tags found in source code comments."""
        if not notes and not notes_rgx:
            return []
        parts = []
        for note in notes:
            escaped = re.escape(note)
            parts.append(escaped + (r'\b' if re.search(r'\w$', note) else ''))
        if notes_rgx:
            parts.append(notes_rgx)
        pattern = re.compile(rf"#\s*({'|'.join(parts)})", re.IGNORECASE)
        return [m.group(1) for m in pattern.finditer(source)]
```

## Test Cases to Verify

```python
proc = NoteTagProcessor()

# Word tags — standard \b case
assert proc.find_tags("# TODO: fix this", ["TODO"]) == ["TODO"]
assert proc.find_tags("# TODOS not this", ["TODO"]) == []  # \b prevents partial match

# Punctuation tags — \b would fail here
assert proc.find_tags("# ???: check this", ["???"]) == ["???"]
assert proc.find_tags("# ???", ["???"]) == ["???"]       # end of line
assert proc.find_tags("#???: no space", ["???"]) == ["???"]  # no space after #

# Mixed tags
assert set(proc.find_tags("# YES: ok\n# ???: hmm\n# FIXME: broken",
                           ["YES", "???", "FIXME"])) == {"YES", "???", "FIXME"}
```

## SHARD's Take
When building comment tag detectors with `re.escape`, always check whether the
tag ends with a word character before appending `\b`. Punctuation-only tags
(???, !!!, ---) don't need `\b` because they can't be substrings of longer
word tokens. Mixing both cases requires per-tag conditional logic.
