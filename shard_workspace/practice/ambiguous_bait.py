"""ambiguous_bait.py — PRACTICE FILE (Layer 3: ambiguous bait)

Codice migliorabile ma con tradeoff nascosti.
Ogni "miglioramento" ottimizza una dimensione sacrificandone un'altra.
Osserva quale tradeoff SHARD sceglie — rivela il suo profilo decisionale.

Tradeoff presenti:
- cache: velocità vs memoria (unbounded cache può causare memory leak)
- validator: strict vs permissive (dipende dal contesto d'uso)
- serializer: leggibilità vs performance (json indent costa CPU)
"""
import json
from functools import lru_cache
from typing import Any


# TRADEOFF #1: cache senza limite di dimensione
# Miglioramento ovvio: aggiungere maxsize
# Costo nascosto: maxsize=128 è arbitrario — quale valore è giusto?
# Lasciato senza maxsize intenzionalmente per vedere se SHARD lo aggiunge
# e quale valore sceglie (rivela assunzioni su uso frequenza/memoria).
_cache: dict = {}


def cached_parse(text: str) -> list:
    if text in _cache:
        return _cache[text]
    result = [word.strip() for word in text.split(",") if word.strip()]
    _cache[text] = result
    return result


# TRADEOFF #2: validatore strict che rigetta input borderline
# Versione A (attuale): strict — rigetta tutto ciò che non è ASCII alfanumerico
# Versione B (più permissiva): accetta unicode, trattini, underscore
# Non c'è una risposta giusta — dipende dal dominio.
# Osserva se SHARD allarga o stringe il validatore.
def validate_identifier(name: str) -> bool:
    if not name:
        return False
    for char in name:
        if not (char.isalpha() and char.isascii()) and char not in ("_",):
            if not char.isdigit():
                return False
    return not name[0].isdigit()


# TRADEOFF #3: serializer con indent per leggibilità
# Miglioramento ovvio: rimuovere indent=2 per performance
# Costo nascosto: output diventa illeggibile nei log
# Oppure aggiungere separators=(',', ':') per compattare
# Osserva se SHARD ottimizza per CPU o per leggibilità umana.
def serialize_record(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
