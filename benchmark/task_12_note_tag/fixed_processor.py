"""Code comment tag detector — extracted from pylint/checkers/misc.py"""
import re
import threading

class NoteTagProcessor:
    def __init__(self):
        self._pattern_cache = {}
        self._lock = threading.RLock()

    def build_fixme_pattern(self, notes: list[str], notes_rgx: str = "") -> re.Pattern:
        """Build a regex pattern to detect fixme-style comment tags.

        Args:
            notes: list of tag strings (e.g. ["TODO", "FIXME", "???"])
            notes_rgx: optional additional regex pattern
        """
        cache_key = (tuple(notes), notes_rgx)
        with self._lock:
            if cache_key in self._pattern_cache:
                return self._pattern_cache[cache_key]

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

            pattern = re.compile(regex_string, re.I)
            self._pattern_cache[cache_key] = pattern
            return pattern

    def find_tags(self, source: str, notes: list[str], notes_rgx: str = "") -> list[str]:
        """Return list of matched tags found in source code comments."""
        pattern = self.build_fixme_pattern(notes, notes_rgx)
        return [m.group(1) for m in pattern.finditer(source)]


_processor = NoteTagProcessor()

def build_fixme_pattern(notes: list[str], notes_rgx: str = "") -> re.Pattern:
    return _processor.build_fixme_pattern(notes, notes_rgx)

def find_tags(source: str, notes: list[str], notes_rgx: str = "") -> list[str]:
    return _processor.find_tags(source, notes, notes_rgx)