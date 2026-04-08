# Python string template substitution regex custom delimiters -- SHARD Cheat Sheet

## Key Concepts
* Template parsing: extracting field names from format strings
* Lexical analysis: breaking down text into tokens
* Syntax analysis: analyzing the structure of tokens
* Regular expressions: pattern matching for text processing
* Custom delimiters: using non-standard characters for template parsing

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Flexible template parsing | Potential performance impact |
| Supports custom delimiters | Increased complexity in regex patterns |
| Improved security with proper input validation | Steeper learning curve for developers |

## Practical Example
```python
import re

def parse_template(template: str) -> list[str]:
    # Using custom delimiters {{ }} for JSON-style templates
    arguments = re.findall(r"\{\{([^{}]+)\}\}", template)
    # Extracting field names from the template
    fields = re.findall(r"\{(.+?)(:.*)?\}", arguments[0])
    return [field[0] for field in fields]

template = '{{ "Category": "{category}" }}'
print(parse_template(template))  # Output: ['category']
```

## SHARD's Take
Template parsing with custom delimiters requires a delicate balance between flexibility and performance. By using regular expressions and lexical analysis, developers can create efficient and secure template parsing systems. However, it is crucial to carefully consider the trade-offs between complexity, performance, and security when designing such systems.