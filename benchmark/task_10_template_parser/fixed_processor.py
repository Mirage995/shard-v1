"""Template argument parser — extracted from pylint/reporters/text.py"""
import re
import warnings
import copy

MESSAGE_FIELDS = {"category", "symbol", "msg", "C", "module", "obj", "line", "col_offset", "path", "abspath"}

PATTERN = re.compile(r"(?<!\{)\{([^{}]+?)(:[^}]*)?\}(?!\})")


def parse_template(template: str) -> list[str]:
    """Parse a message template and return list of field names used.

    Warns if an unknown field is referenced.
    Returns the list of valid argument names found.
    """
    template = copy.copy(template)
    arguments = PATTERN.findall(template)
    valid = []
    for field_name, _fmt in arguments:
        field_name = field_name.strip()
        if field_name not in MESSAGE_FIELDS:
            warnings.warn(
                f"Don't recognize the argument {field_name} in the --msg-template. "
                "Are you sure it's supported on the current version of pylint?"
            )
        else:
            valid.append(field_name)
    return valid