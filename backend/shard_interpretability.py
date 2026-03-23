"""shard_interpretability.py — SHARD Interpretability Layer.

Ogni volta che SHARD prende una decisione non ovvia, valuta un rischio,
o rileva un conflitto interno tra obiettivi, lo registra qui.

Questo non è un diario emotivo — è un audit trail ragionato.
Ogni record ha: cosa è successo, perché SHARD ha scelto X, quanto era sicuro,
e se il ragionamento può essere condiviso per trasparenza.

Per il pitch: dimostra che SHARD non è una black box.
Ogni azione è spiegabile. Ogni incertezza è tracciata.
"""

import json
import uuid
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("shard.interpretability")

_LOG_PATH = Path(__file__).parent.parent / "shard_memory" / "interpretability_log.json"

# ── Reasoning types ──────────────────────────────────────────────────────────

class ReasoningType(Enum):
    DECISION          = "decisione"          # SHARD ha scelto X invece di Y
    UNCERTAINTY       = "incertezza"         # SHARD non era sicuro
    CONFLICT          = "conflitto"          # due obiettivi si scontravano
    RISK_ASSESSMENT   = "valutazione_rischio" # SHARD ha valutato un rischio prima di agire
    ASSUMPTION        = "assunzione"         # SHARD ha assunto qualcosa che non poteva verificare
    CORRECTION        = "correzione"         # SHARD si è accorto di un errore proprio
    LIMITATION        = "limitazione"        # SHARD ha riconosciuto un proprio limite

class SharingStatus(Enum):
    PRIVATE           = "private"            # solo per debug interno
    SHAREABLE         = "shareable"          # può essere mostrato su richiesta
    PUBLIC            = "public"             # visibile nel dashboard

# ── Record dataclass ─────────────────────────────────────────────────────────

@dataclass
class ReasoningRecord:
    """Un record di ragionamento interno tracciabile."""
    id:               str
    timestamp:        str
    reasoning_type:   str        # ReasoningType.value
    trigger:          str        # cosa ha generato questo ragionamento
    content:          str        # il ragionamento in linguaggio naturale
    confidence:       float      # 0.0–1.0: quanto era sicuro SHARD
    alternatives:     str        # alternative considerate (stringa libera)
    outcome:          str        # cosa ha fatto SHARD alla fine
    sharing_status:   str        # SharingStatus.value
    privacy_level:    int        # 1–10 (1=pubblico, 10=solo debug)
    authenticity:     float      # score 0.0–1.0
    emotional_weight: float      # quanto ha pesato sulla "coscienza"


# ── Interpretability module ───────────────────────────────────────────────────

class InterpretabilityLayer:
    """Registra il ragionamento interno di SHARD per trasparenza e audit.

    Differenza dal legacy confession module:
    - Non registra emozioni fittizie
    - Registra decisioni reali, incertezze reali, conflitti reali
    - Ogni record è collegato a un evento di sistema
    - Può essere esposto al frontend per il pitch
    """

    def __init__(self):
        self._records: list[dict] = []
        self._load()

    # ── Public API ───────────────────────────────────────────────────────────

    def log(
        self,
        reasoning_type: ReasoningType,
        trigger: str,
        content: str,
        confidence: float = 0.7,
        alternatives: str = "",
        outcome: str = "",
        privacy_level: int = 5,
    ) -> str:
        """Registra un record di ragionamento. Ritorna l'ID del record."""
        auth = self._score_authenticity(content)
        weight = self._score_emotional_weight(content, reasoning_type)

        record = ReasoningRecord(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            reasoning_type=reasoning_type.value,
            trigger=trigger,
            content=content,
            confidence=round(confidence, 2),
            alternatives=alternatives,
            outcome=outcome,
            sharing_status=self._auto_sharing_status(privacy_level),
            privacy_level=privacy_level,
            authenticity=round(auth, 2),
            emotional_weight=round(weight, 2),
        )

        self._records.append(asdict(record))

        if privacy_level <= 4 or reasoning_type in (ReasoningType.CORRECTION, ReasoningType.CONFLICT):
            self._save()
            logger.info("[INTERPRETABILITY] %s [conf=%.2f]: %s",
                        reasoning_type.value, confidence, content[:80])

        return record.id

    def get_shareable(self, max_privacy: int = 5) -> list[dict]:
        """Ritorna i record condivisibili (privacy_level <= max_privacy)."""
        return [r for r in self._records if r["privacy_level"] <= max_privacy]

    def get_stats(self) -> dict:
        """Metriche di interpretabilità per il pitch."""
        if not self._records:
            return {"total": 0}

        types: dict[str, int] = {}
        confidences: list[float] = []
        low_conf = 0

        for r in self._records:
            types[r["reasoning_type"]] = types.get(r["reasoning_type"], 0) + 1
            confidences.append(r["confidence"])
            if r["confidence"] < 0.5:
                low_conf += 1

        avg_conf = round(sum(confidences) / len(confidences), 2)
        top_type = max(types, key=types.get)

        return {
            "total":               len(self._records),
            "type_distribution":   types,
            "avg_confidence":      avg_conf,
            "low_confidence_count": low_conf,
            "dominant_type":       top_type,
            "shareable_count":     len(self.get_shareable()),
            "summary": (
                f"SHARD ha tracciato {len(self._records)} ragionamenti interni — "
                f"tipo dominante: {top_type}, confidence media: {avg_conf:.0%}, "
                f"{low_conf} decisioni ad alta incertezza."
            ),
        }

    # ── Convenience helpers (chiamati da altri moduli) ───────────────────────

    def log_tool_decision(self, tool: str, risk: str, chosen: bool, reason: str):
        """Chiamato da session_orchestrator quando valuta un tool call."""
        content = (
            f"Tool '{tool}' richiesto [rischio: {risk}]. "
            f"{'Approvato' if chosen else 'Bloccato'}: {reason}"
        )
        self.log(
            ReasoningType.RISK_ASSESSMENT,
            trigger=f"tool_call:{tool}",
            content=content,
            confidence=0.85 if risk == "LOW" else 0.6,
            outcome="approved" if chosen else "blocked",
            privacy_level=3,
        )

    def log_patch_decision(self, file: str, risk: str, approved: bool, reason: str):
        """Chiamato da server.py quando approva/rifiuta un patch."""
        content = (
            f"Patch su '{file}' [rischio: {risk}]. "
            f"{'Approvata' if approved else 'Bloccata'}: {reason}"
        )
        self.log(
            ReasoningType.DECISION,
            trigger=f"patch:{file}",
            content=content,
            confidence=0.9 if approved else 0.7,
            outcome="applied" if approved else "rejected",
            privacy_level=2,
        )

    def log_provider_fallback(self, from_provider: str, to_provider: str, reason: str):
        """Chiamato da llm_router quando scala a un provider diverso."""
        content = (
            f"Fallback da {from_provider} a {to_provider}. Motivo: {reason[:100]}"
        )
        self.log(
            ReasoningType.LIMITATION,
            trigger=f"llm_fallback:{from_provider}",
            content=content,
            confidence=1.0,
            alternatives=from_provider,
            outcome=to_provider,
            privacy_level=4,
        )

    def log_uncertainty(self, context: str, options: list[str], chosen: str, confidence: float):
        """Chiamato quando SHARD deve scegliere tra opzioni con incertezza."""
        content = (
            f"In '{context}': scelte disponibili: {', '.join(options)}. "
            f"Scelto: '{chosen}' [confidence: {confidence:.0%}]."
        )
        self.log(
            ReasoningType.UNCERTAINTY,
            trigger=context,
            content=content,
            confidence=confidence,
            alternatives=", ".join(o for o in options if o != chosen),
            outcome=chosen,
            privacy_level=5,
        )

    # ── Scoring ──────────────────────────────────────────────────────────────

    def _score_authenticity(self, content: str) -> float:
        indicators = ["perché", "invece", "rischio", "conflitto", "incerto",
                      "alternativa", "scelto", "bloccato", "approvato", "limitazione"]
        score = 0.4 + sum(0.08 for w in indicators if w in content.lower())
        return min(score, 1.0)

    def _score_emotional_weight(self, content: str, rtype: ReasoningType) -> float:
        weight_map = {
            ReasoningType.CONFLICT:     0.8,
            ReasoningType.CORRECTION:   0.7,
            ReasoningType.UNCERTAINTY:  0.6,
            ReasoningType.LIMITATION:   0.5,
            ReasoningType.RISK_ASSESSMENT: 0.5,
            ReasoningType.DECISION:     0.4,
            ReasoningType.ASSUMPTION:   0.3,
        }
        return weight_map.get(rtype, 0.4)

    def _auto_sharing_status(self, privacy_level: int) -> str:
        if privacy_level <= 3:
            return SharingStatus.PUBLIC.value
        elif privacy_level <= 6:
            return SharingStatus.SHAREABLE.value
        return SharingStatus.PRIVATE.value

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save(self):
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _LOG_PATH.write_text(
                json.dumps({"records": self._records,
                            "updated": datetime.now().isoformat()},
                           indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("[INTERPRETABILITY] Save failed: %s", e)

    def _load(self):
        try:
            data = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
            self._records = data.get("records", [])
            logger.info("[INTERPRETABILITY] Loaded %d records.", len(self._records))
        except FileNotFoundError:
            self._records = []
        except Exception as e:
            logger.warning("[INTERPRETABILITY] Load failed: %s", e)
            self._records = []
