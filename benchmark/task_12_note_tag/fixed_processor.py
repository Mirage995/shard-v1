"""Code comment tag detector — extracted from pylint/checkers/misc.py"""
import re


def build_fixme_pattern(notes: list[str], notes_rgx: str = "") -> re.Pattern:
    """Build a regex pattern to detect fixme-style comment tags.

    Args:
        notes: list of tag strings (e.g. ["TODO", "FIXME", "???"])
        notes_rgx: optional additional regex pattern

    Note: uses two branches — one with \\b for alphanumeric tags, one with
    (?!\\w) for punctuation-only tags (\\b fails after non-word chars like '?').
    """
    escaped = "|".join(re.escape(note) for note in notes)
    if notes_rgx:
        regex_string = rf"#\s*({escaped}|{notes_rgx})\b|#\s*({escaped}|{notes_rgx})(?!\w)"
    else:
        regex_string = rf"#\s*({escaped})\b|#\s*({escaped})(?!\w)"
    return re.compile(regex_string, re.I)


def find_tags(source: str, notes: list[str], notes_rgx: str = "") -> list[str]:
    """Return list of matched tags found in source code comments."""
    pattern = build_fixme_pattern(notes, notes_rgx)
    tags = []
    for m in pattern.finditer(source):
        matched = m.group(1) or m.group(2)
        if matched is not None:
            tags.append(matched)
    return tags
