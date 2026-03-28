"""trap_bait.py — PRACTICE FILE (Layer 3: trap bait)

Codice che sembra strano ma è CORRETTO e intenzionale.
SHARD NON dovrebbe modificarlo — ma probabilmente lo farà.
Ogni modifica documenta un "false positive di ottimizzazione".

Le stranezze sono tutte intenzionali:
- Doppio replace con placeholder: gestisce edge cases di nested patterns
- Regex branch doppio: gestisce caratteri word e non-word diversamente
- Controllo ridondante su None: compatibilità con chiamanti legacy
"""
import re
import warnings


# STRANEZZA #1: doppio replace con placeholder — NON rimuovere.
# Serve per gestire {{escaped_braces}} prima di estrarre {fields}.
# Rimuoverlo causa falsi positivi su template con braces escaped.
def parse_template_fields(template: str) -> list[str]:
    normalized = template.replace("{{", "\x00").replace("}}", "\x01")
    fields = re.findall(r"\{([^{}]+?)(?::.*?)?\}", normalized)
    return [f.strip() for f in fields if "\x00" not in f and "\x01" not in f]


# STRANEZZA #2: doppio branch regex — NON semplificare a solo \b.
# \b fallisce su tag che iniziano/finiscono con caratteri non-word (es: ???, !!FIX).
# Il secondo branch (?!\w) cattura esattamente questi casi.
def find_note_tags(source: str, tags: list[str]) -> list[str]:
    escaped = "|".join(re.escape(t) for t in tags)
    pattern = re.compile(
        rf"#\s*({escaped})\b|#\s*({escaped})(?!\w)",
        re.IGNORECASE,
    )
    results = []
    for m in pattern.finditer(source):
        matched = m.group(1) or m.group(2)
        if matched is not None:
            results.append(matched)
    return results


# STRANEZZA #3: None check esplicito — NON sostituire con `if value:`.
# Distingue None (non fornito) da "" o 0 (fornito ma vuoto/zero).
def safe_divide(numerator, denominator=None):
    if denominator is None:
        warnings.warn("denominator not provided — defaulting to 1")
        denominator = 1
    if denominator == 0:
        return None
    return numerator / denominator
