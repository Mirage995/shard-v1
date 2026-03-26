"""Template argument parser — extracted from pylint/reporters/text.py"""
import re
import warnings

MESSAGE_FIELDS = {"category", "symbol", "msg", "C", "module", "obj", "line", "col_offset", "path", "abspath"}


def parse_template(template: str) -> list[str]:
    """Parse a message template and return list of field names used.

    Warns if an unknown field is referenced.
    Returns the list of valid argument names found.

    Note: {{ and }} are escaped braces — must NOT be parsed as fields.
    """
    # Replace escaped braces with placeholders before field extraction
    normalized = template.replace("{{", "\x00").replace("}}", "\x01")

    arguments = re.findall(r"\{([^{}]+?)(?::.*?)?\}", normalized)
    valid = []
    for argument in arguments:
        argument = argument.strip()
        if argument not in MESSAGE_FIELDS:
            warnings.warn(
                f"Don't recognize the argument {argument!r} in the --msg-template. "
                "Are you sure it's supported on the current version of pylint?"
            )
        else:
            valid.append(argument)
    return valid