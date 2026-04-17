"""Code comment tag detector — extracted from pylint/checkers/misc.py"""
import re


def build_fixme_pattern(notes: list[str], notes_rgx: str = "") -> re.Pattern:
    """Build a regex pattern to detect fixme-style comment tags.

    Args:
        notes: list of tag strings (e.g. ["TODO", "FIXME", "???"])
        notes_rgx: optional additional regex pattern
    """
    escaped = "|".join(re.escape(note) for note in notes)
    if escaped or notes_rgx:
        if notes_rgx:
            if escaped:
                regex_string = rf"#\s*({escaped}|{notes_rgx})(?!\w)"
            else:
                regex_string = rf"#\s*({notes_rgx})(?!\w)"
        else:
            regex_string = rf"#\s*({escaped})(?!\w)"
    else:
        regex_string = r"#\s*(?!\w)"  # Match a comment with nothing after it
    return re.compile(regex_string, re.I)


def find_tags(source: str, notes: list[str], notes_rgx: str = "") -> list[str]:
    """Return list of matched tags found in source code comments."""
    if source is None:
        return []
    pattern = build_fixme_pattern(notes, notes_rgx)
    return [m.group(1) for m in pattern.finditer(source) if m.group(1)]