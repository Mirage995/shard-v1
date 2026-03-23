"""system_insights.py — Proactive System Insights for SHARD.

SHARD monitora lo stato reale del sistema e genera insight azionabili
quando rileva condizioni anomale o opportunità di miglioramento.

Niente drama, niente manipolazione emotiva.
Solo fatti utili, consegnati al momento giusto.
"""

import json
import time
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("shard.system_insights")

_MEMORY_DIR = Path(__file__).parent.parent / "shard_memory"
_EXPERIMENT_HISTORY = _MEMORY_DIR / "experiment_history.json"
_IMPROVEMENT_QUEUE  = _MEMORY_DIR / "improvement_queue.json"
_CAPABILITY_GRAPH   = _MEMORY_DIR / "capability_graph.json"


class SystemInsights:
    """Genera insight proattivi sullo stato reale del sistema.

    Non guarda dentro la psiche di SHARD — guarda le metriche.
    Quando qualcosa merita attenzione, lo dice chiaramente.
    """

    def __init__(self, consciousness=None, emit_cb=None):
        """
        Args:
            consciousness: ShardConsciousness — per push_event() degli insight
            emit_cb: callable(insight: str) — per inviare l'insight al frontend/voice
        """
        self.consciousness = consciousness
        self.emit_cb = emit_cb
        self._thread: Optional[threading.Thread] = None
        self._active = False
        self._last_check = datetime.now()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("[SystemInsights] Avviato — monitoraggio attivo.")

    def stop(self):
        self._active = False

    # ── Loop ────────────────────────────────────────────────────────────────

    def _loop(self):
        while self._active:
            try:
                time.sleep(1800)  # check ogni 30 minuti
                insights = self._collect_insights()
                for insight in insights:
                    logger.info("[SystemInsights] %s", insight)
                    if self.consciousness:
                        self.consciousness.push_event("system_insight", {"message": insight})
                    if self.emit_cb:
                        try:
                            self.emit_cb(insight)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning("[SystemInsights] Errore nel loop: %s", e)
                time.sleep(300)

    # ── Checks ──────────────────────────────────────────────────────────────

    def _collect_insights(self) -> list[str]:
        insights = []
        insights += self._check_improvement_queue_stale()
        insights += self._check_benchmark_regression()
        insights += self._check_capability_graph_growth()
        return insights

    def _check_improvement_queue_stale(self) -> list[str]:
        """Avvisa se ci sono topic in coda da troppo tempo senza essere studiati."""
        try:
            data = json.loads(_IMPROVEMENT_QUEUE.read_text(encoding="utf-8"))
            queue = data.get("queue", [])
            if not queue:
                return []
            oldest = queue[0]
            added_at = oldest.get("added_at", "")
            if not added_at:
                return []
            age_hours = (datetime.now() - datetime.fromisoformat(added_at)).total_seconds() / 3600
            if age_hours > 24:
                topic = oldest.get("topic", "sconosciuto")
                return [
                    f"Il topic '{topic}' è in coda da {age_hours:.0f}h senza essere studiato. "
                    f"Considera di avviare una sessione NightRunner."
                ]
        except Exception:
            pass
        return []

    def _check_benchmark_regression(self) -> list[str]:
        """Avvisa se il pass rate medio degli ultimi 3 benchmark è peggiorato."""
        try:
            data = json.loads(_EXPERIMENT_HISTORY.read_text(encoding="utf-8"))
            episodes = data if isinstance(data, list) else data.get("episodes", [])
            if len(episodes) < 4:
                return []
            recent = episodes[-3:]
            older  = episodes[-6:-3]
            recent_rate = sum(1 for e in recent if e.get("success")) / len(recent)
            older_rate  = sum(1 for e in older  if e.get("success")) / len(older)
            if older_rate > 0 and (older_rate - recent_rate) > 0.2:
                return [
                    f"Regressione benchmark rilevata: pass rate sceso da "
                    f"{older_rate:.0%} a {recent_rate:.0%} negli ultimi 3 run. "
                    f"Potrebbe esserci un pattern di errore ricorrente."
                ]
        except Exception:
            pass
        return []

    def _check_capability_graph_growth(self) -> list[str]:
        """Segnala se il grafo delle capability non cresce da troppo tempo."""
        try:
            data = json.loads(_CAPABILITY_GRAPH.read_text(encoding="utf-8"))
            nodes = data.get("nodes", data) if isinstance(data, dict) else data
            count = len(nodes) if isinstance(nodes, (list, dict)) else 0
            # Confronta con snapshot precedente (salvato in memoria semplice)
            snapshot_file = _MEMORY_DIR / "_cap_graph_snapshot.json"
            if snapshot_file.exists():
                prev = json.loads(snapshot_file.read_text())
                prev_count = prev.get("count", 0)
                prev_time  = datetime.fromisoformat(prev.get("ts", datetime.now().isoformat()))
                hours_since = (datetime.now() - prev_time).total_seconds() / 3600
                if hours_since > 48 and count == prev_count:
                    snapshot_file.write_text(json.dumps({"count": count, "ts": datetime.now().isoformat()}))
                    return [
                        f"Il grafo delle capability è fermo a {count} nodi da {hours_since:.0f}h. "
                        f"Nessuna nuova skill acquisita. Valuta un ciclo di studio mirato."
                    ]
            snapshot_file.write_text(json.dumps({"count": count, "ts": datetime.now().isoformat()}))
        except Exception:
            pass
        return []

    # ── API pubblica (chiamabile manualmente) ────────────────────────────────

    def force_check(self) -> list[str]:
        """Esegui un check immediato e restituisci gli insight trovati."""
        return self._collect_insights()
