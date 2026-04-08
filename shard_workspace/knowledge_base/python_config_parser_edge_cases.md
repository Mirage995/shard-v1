# Python config parser edge cases -- SHARD Cheat Sheet

## Key Concepts
* Handling URL values with colons without splitting them
* Stripping whitespace from keys and values
* Ignoring empty lines and comment lines
* Using `get()` method to avoid `KeyError` when retrieving settings
* Merging config dictionaries with override values

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Robust config parsing with edge case handling | Increased code complexity |
| Flexible config loading from strings | Potential performance impact |
| Improved error handling with default values | Additional testing required |

## Practical Example
```python
def parse_line(line):
    parts = line.split(":", 1)
    key = parts[0].strip()
    value = parts[1].strip()
    return key, value

def load_config(text):
    config = {}
    for line in text.split("\n"):
        if not line.strip() or line.strip().startswith("#"):
            continue
        k, v = parse_line(line)
        config[k] = v
    return config

def get_setting(config, key, default=None):
    return config.get(key, default)

# Example usage:
config_text = "host:localhost\nport:8080\n# comment\nendpoint:http://api.example.com:8080"
config = load_config(config_text)
print(get_setting(config, "host"))  # Output: localhost
print(get_setting(config, "port"))  # Output: 8080
print(get_setting(config, "endpoint"))  # Output: http://api.example.com:8080
print(get_setting(config, "nonexistent", default="default_value"))  # Output: default_value
```

## SHARD's Take
The provided code snippet demonstrates a robust config parser that handles edge cases such as URL values with colons, whitespace stripping, and empty/comment line ignoring. By using the `get()` method, it also provides a safe way to retrieve settings with default values. Overall, this approach ensures a reliable and flexible config parsing mechanism.