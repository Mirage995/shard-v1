# template parser handling and debugging — SHARD Cheat Sheet

## Key Concepts
*   **Template Engine:** Software designed to combine templates with data models to produce result documents.
*   **Template Syntax:** The specific rules and grammar used to define placeholders and logic within a template.
*   **Context:** The data provided to the template engine, used to replace placeholders in the template.
*   **Lexer/Tokenizer:** Breaks the template into a stream of tokens for parsing.
*   **Parser:** Analyzes the token stream to build an abstract syntax tree (AST) representing the template structure.
*   **Rendering:** The process of evaluating the template with the context to generate the final output.
*   **Escaping:** Converting special characters to their safe equivalents to prevent injection attacks.
*   **Sanitization:** Removing or modifying potentially harmful content from the context data.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enables dynamic content generation | Can introduce security vulnerabilities (e.g., injection attacks) if not handled carefully |
| Simplifies code by separating presentation from logic | Performance overhead due to parsing and rendering |
| Improves maintainability through reusable templates | Complex template syntax can be difficult to learn and debug |
| Allows for flexible content updates | Requires careful handling of context data to prevent errors |

## Practical Example
```python
from string import Template

template_string = "Hello, $name! You are $age years old."
template = Template(template_string)

context = {'name': 'Alice', 'age': 30}
result = template.substitute(context)

print(result)  # Output: Hello, Alice! You are 30 years old.

# Example of handling missing keys
try:
    context = {'name': 'Bob'}
    result = template.substitute(context)
except KeyError as e:
    print(f"Missing key: {e}")

# Using safe_substitute to avoid KeyError
context = {'name': 'Charlie'}
result = template.safe_substitute(context)
print(result) # Output: Hello, Charlie! You are $age years old.
```

## Critical: Escaped Braces {{ }} in Format-String Templates

`{{` and `}}` are escaped braces (literal `{` `}`) — NOT field references.
A naive regex like `r"\{(.+?)\}"` matches the second `{` of `{{` and consumes real fields.

### The Bug

```python
# WRONG — (:.*?) greedily consumes the real field inside {{ }}
re.findall(r"\{([^\{]+?)(:.*?)?\}", '{{ "line": {line:d} }}')
# returns [(' "line"', ': {line:d')] — "line" field is lost!
```

### The Fix — Negative Lookaround

```python
# CORRECT — skip {{ and }} with negative lookbehind/lookahead
PATTERN = re.compile(r"(?<!\{)\{([^{}]+?)(:[^}]*)?\}(?!\})")

def parse_template(template: str) -> list[str]:
    arguments = PATTERN.findall(template)
    valid = []
    for field_name, _fmt in arguments:
        field_name = field_name.strip()
        if field_name not in MESSAGE_FIELDS:
            warnings.warn(f"Don't recognize the argument {field_name} ...")
        else:
            valid.append(field_name)
    return valid
```

### Why It Works

- `(?<!\{)` — skips second `{` of `{{` (it is preceded by `{`)
- `[^{}]+?` — field name contains no braces, stops before any `{` or `}`
- `(:[^}]*)?` — format spec cannot cross `}` boundary
- `(?!\})` — skips first `}` of `}}` (it is followed by `}`)

### Verified

```python
parse_template('{{ "Category": "{category}" }}')         # ["category"]
parse_template('{{ "line": {line:d}, "msg": "{msg}" }}') # ["line", "msg"]
parse_template('{line:03d}')                              # ["line"]
parse_template('{path}:{line}:{category}')               # ["path", "line", "category"]
```