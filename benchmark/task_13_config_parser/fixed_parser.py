"""Config parser — parses multi-line key:value configuration text.

Each line is a key:value pair. Supports:
- Simple values: "host:localhost"
- Nested values: "endpoint:http://api.example.com:8080"  (value contains colons)
- Inline comments: "#" at start of line marks a comment
- Blank lines are ignored

Usage:
    config = load_config(text)
    host = get_setting(config, "host", default="localhost")
"""


def parse_line(line):
    """Parse a single 'key:value' line into (key, value) tuple."""
    parts = line.split(":", 1)
    key = parts[0].strip()
    value = parts[1].strip()
    return key, value


def load_config(text):
    """Parse multi-line config text into a dict.

    Args:
        text: string with one key:value pair per line.

    Returns:
        dict of {key: value}
    """
    config = {}
    for line in text.split("\n"):
        if not line.strip() or line.strip().startswith("#"):
            continue
        k, v = parse_line(line)
        config[k] = v
    return config


def get_setting(config, key, default=None):
    """Retrieve a setting by key. Returns default if key not present."""
    return config.get(key, default)


def merge_configs(base, override):
    """Merge two config dicts. Override values take precedence."""
    result = {}
    for k in base:
        result[k] = base[k]
    for k in override:
        result[k] = override[k]
    return result