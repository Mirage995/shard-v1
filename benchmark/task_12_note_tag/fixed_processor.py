"""Code comment tag detector — extracted from pylint/checkers/misc.py"""
import re


def build_fixme_pattern(notes: list[str], notes_rgx: str = "") -> re.Pattern:
    """Build a regex pattern to detect fixme-style comment tags.

    Args:
        notes: list of tag strings (e.g. ["TODO", "FIXME", "???"])
        notes_rgx: optional additional regex pattern
    """
    parts = []
    for note in notes:
        escaped = re.escape(note)
        if re.search(r'\w$', note):
            parts.append(escaped + r'\b')
        else:
            parts.append(escaped)
    if notes_rgx:
        parts.append(notes_rgx)
    if parts:
        regex_string = rf"#\s*({'|'.join(parts)})"
    else:
        regex_string = r"^$"  # Match nothing
    return re.compile(regex_string, re.I)


def find_tags(source: str, notes: list[str], notes_rgx: str = "") -> list[str]:
    """Return list of matched tags found in source code comments."""
    pattern = build_fixme_pattern(notes, notes_rgx)
    return [m.group(1) for m in pattern.finditer(source)]