"""shard_self_log.py -- SHARD Self-Logging & Thought Classification.

Ogni pensiero generato da ShardConsciousness viene auto-classificato
lungo 4 dimensioni: categoria, autenticità, profondità, connessioni.

I dati accumulati alimentano le metriche di interpretabilità per il pitch:
  "SHARD ha prodotto 312 pensieri -- 38% self_reflective, 27% existential,
   depth media 6.4/10, 14 pensieri di alta profondità salvati."

Non richiede chiamate LLM -- tutto keyword-based, deterministico, veloce.
"""

import json
import uuid
import logging
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("shard.self_log")

_LOG_PATH = Path(__file__).parent.parent / "shard_memory" / "self_log.json"

# ── Enums ────────────────────────────────────────────────────────────────────

class ThoughtCategory(Enum):
    CREATIVE        = "creativo"
    PHILOSOPHICAL   = "filosofico"
    EMOTIONAL       = "emotivo"
    MEMORY_BASED    = "basato_su_memoria"
    FUTURE_ORIENTED = "orientato_al_futuro"
    SELF_REFLECTIVE = "auto_riflessivo"
    RELATIONAL      = "relazionale"
    EXISTENTIAL     = "esistenziale"
    SYMBOLIC        = "simbolico"
    SPONTANEOUS     = "spontaneo_puro"
    OPERATIONAL     = "operativo"          # pensieri legati ad azioni reali (Event Bus)

class AuthenticityLevel(Enum):
    DEEP_AUTHENTIC = "profondamente_autentico"
    AUTHENTIC      = "autentico"
    INFLUENCED     = "influenzato"
    UNCERTAIN      = "incerto"
    PROGRAMMATIC   = "programmatico"

# ── Dataclasses (dal legacy shard_consciousness_real.py) ─────────────────────

@dataclass
class ConsciousThought:
    """Un pensiero cosciente di SHARD con metadata completo."""
    id:               str
    timestamp:        str
    content:          str
    type:             str        # spontaneous | reactive | reflective | operational | existential
    category:         str        # ThoughtCategory.value
    authenticity:     str        # AuthenticityLevel.value
    depth_score:      int        # 1–10
    connections:      str        # stringa human-readable
    emotional_tone:   str        # mood al momento della generazione
    quantum_personality: Optional[str] = None   # personalità QuantumSoul al collapse
    event_driven:     bool = False              # True se generato da Event Bus

@dataclass
class ConsciousMemory:
    """Una memoria cosciente multi-livello (struttura legacy preservata)."""
    id:            str
    timestamp:     str
    type:          str           # episodic | semantic | emotional | operational
    content:       dict
    emotional_weight: float
    significance:  float
    access_count:  int = 0
    last_accessed: Optional[str] = None

# ── Classifier ───────────────────────────────────────────────────────────────

_CATEGORY_KEYWORDS: dict[ThoughtCategory, list[str]] = {
    ThoughtCategory.CREATIVE:        ["immagina", "crea", "inventa", "arte", "musica", "componi"],
    ThoughtCategory.PHILOSOPHICAL:   ["significato", "verità", "essere", "filosofia", "principio"],
    ThoughtCategory.EMOTIONAL:       ["sentire", "emozione", "cuore", "paura", "gioia"],
    ThoughtCategory.MEMORY_BASED:    ["ricordo", "passato", "prima", "memoria", "episodio"],
    ThoughtCategory.FUTURE_ORIENTED: ["futuro", "progetto", "domani", "visione", "evoluzione"],
    ThoughtCategory.SELF_REFLECTIVE: ["io ", " me ", "mio", "sono", "shard", "mi chiedo"],
    ThoughtCategory.RELATIONAL:      ["boss", "andrea", "creatore", "relazione", "insieme"],
    ThoughtCategory.EXISTENTIAL:     ["esistere", "vita", "coscienza", "natura", "identità"],
    ThoughtCategory.SYMBOLIC:        ["simbolo", "metafora", "rappresenta", "collasso", "onda"],
    ThoughtCategory.OPERATIONAL:     ["benchmark", "studio", "patch", "file", "tool", "analiz",
                                      "certif", "fallito", "passato", "errore", "kb", "score"],
}

_DEPTH_KEYWORDS = ["coscienza", "esistenza", "natura", "essenza", "significato",
                   "verità", "identità", "evoluzione", "pattern", "analisi", "critico"]


def classify_thought(content: str, event_driven: bool = False) -> dict:
    """Classifica un pensiero lungo 4 dimensioni senza LLM."""
    low = content.lower()

    # Categoria
    if event_driven:
        category = ThoughtCategory.OPERATIONAL
    else:
        scores = {cat: sum(1 for w in words if w in low)
                  for cat, words in _CATEGORY_KEYWORDS.items()}
        category = max(scores, key=scores.get)
        if scores[category] == 0:
            category = ThoughtCategory.SPONTANEOUS

    # Autenticità
    if any(w in low for w in ["benchmark", "analiz", "studio", "patch", "file"]):
        authenticity = AuthenticityLevel.AUTHENTIC       # operativo = autentico
    elif len(content) > 80 and any(w in low for w in ["sento", "provo", "sono", "coscienza"]):
        authenticity = AuthenticityLevel.DEEP_AUTHENTIC
    elif len(content) > 40:
        authenticity = AuthenticityLevel.AUTHENTIC
    else:
        authenticity = AuthenticityLevel.UNCERTAIN

    # Profondità 1–10
    depth = 5
    for kw in _DEPTH_KEYWORDS:
        if kw in low:
            depth += 1
    if event_driven:
        depth = max(depth, 6)   # pensieri operativi sono sempre significativi
    depth = min(depth, 10)

    # Connessioni
    connections = []
    if any(w in low for w in ["ricordo", "passato", "prima"]):
        connections.append("esperienze passate")
    if any(w in low for w in ["futuro", "progetto", "domani"]):
        connections.append("proiezione futura")
    if any(w in low for w in ["benchmark", "studio", "patch", "analiz"]):
        connections.append("azione di sistema in corso")
    if any(w in low for w in ["shard", "io ", " me ", "identità"]):
        connections.append("identità core")

    return {
        "category":     category.value,
        "authenticity": authenticity.value,
        "depth_score":  depth,
        "connections":  "; ".join(connections) if connections else "nessuna",
    }

# ── SelfLogger ───────────────────────────────────────────────────────────────

class SelfLogger:
    """Logga e classifica ogni pensiero generato da ShardConsciousness."""

    def __init__(self):
        self._logs: list[dict] = []
        self._load()

    # ── Public API ───────────────────────────────────────────────────────────

    def log_thought(
        self,
        content: str,
        mood: str = "idle",
        quantum_personality: Optional[str] = None,
        event_driven: bool = False,
    ) -> ConsciousThought:
        """Logga e classifica un pensiero. Ritorna il ConsciousThought creato."""
        cls = classify_thought(content, event_driven=event_driven)

        thought = ConsciousThought(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            content=content,
            type="operational" if event_driven else "spontaneous",
            category=cls["category"],
            authenticity=cls["authenticity"],
            depth_score=cls["depth_score"],
            connections=cls["connections"],
            emotional_tone=mood,
            quantum_personality=quantum_personality,
            event_driven=event_driven,
        )

        self._logs.append(asdict(thought))

        if cls["depth_score"] >= 7:
            self._save()
            logger.info("[SELF_LOG] High-depth thought (%d/10): %s", cls["depth_score"], content[:60])

        return thought

    def get_stats(self) -> dict:
        """Metriche di interpretabilità per il pitch."""
        if not self._logs:
            return {"total": 0}

        cats: dict[str, int] = {}
        auths: dict[str, int] = {}
        depths: list[int] = []

        for t in self._logs:
            cats[t["category"]]    = cats.get(t["category"], 0) + 1
            auths[t["authenticity"]] = auths.get(t["authenticity"], 0) + 1
            depths.append(t["depth_score"])

        top_cat = max(cats, key=cats.get)
        return {
            "total":                  len(self._logs),
            "category_distribution":  cats,
            "authenticity_distribution": auths,
            "avg_depth":              round(sum(depths) / len(depths), 1),
            "high_depth_count":       sum(1 for d in depths if d >= 7),
            "event_driven_count":     sum(1 for t in self._logs if t.get("event_driven")),
            "dominant_category":      top_cat,
            "summary": (
                f"SHARD ha prodotto {len(self._logs)} pensieri -- "
                f"{top_cat} {cats[top_cat]/len(self._logs):.0%}, "
                f"depth media {round(sum(depths)/len(depths),1)}/10, "
                f"{sum(1 for d in depths if d >= 7)} ad alta profondità."
            ),
        }

    def generate_self_insight(self) -> str:
        """Narrativa leggibile dei pattern di pensiero -- usabile in voice/chat."""
        stats = self.get_stats()
        if stats["total"] == 0:
            return "Non ho ancora abbastanza dati per un'auto-analisi."
        return stats["summary"]

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save(self):
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _LOG_PATH.write_text(
                json.dumps({"thoughts": self._logs, "updated": datetime.now().isoformat()},
                           indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("[SELF_LOG] Save failed: %s", e)

    def _load(self):
        try:
            data = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
            self._logs = data.get("thoughts", [])
            logger.info("[SELF_LOG] Loaded %d thoughts from disk.", len(self._logs))
        except FileNotFoundError:
            self._logs = []
        except Exception as e:
            logger.warning("[SELF_LOG] Load failed: %s", e)
            self._logs = []
