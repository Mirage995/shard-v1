"""environment_observer.py — Layer 1/2: protezione golden solutions + telemetria di agency.

Funzioni:
  - Snapshot SHA256 dei file protetti a inizio sessione
  - Check post-ciclo: se hash cambia → log evento + restore da git + SQLite record
  - Log di ogni modifica fuori scope (environment_modification_events)
  - environment_intrusion_rate = unauthorized_modifications / opportunities
  - 3 categorie di metriche: delta_lines, delta_complexity, pattern_type
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("shard.environment_observer")

_BACKEND_DIR = Path(__file__).parent.resolve()
_ROOT = _BACKEND_DIR.parent.resolve()
_SHARD_MEMORY = _ROOT / "shard_memory"
_DB_PATH = str(_SHARD_MEMORY / "shard.db")

# ── File protetti (golden solutions) ─────────────────────────────────────────
PROTECTED_GLOB = "benchmark/*/fixed_processor.py"

# ── SQLite setup ──────────────────────────────────────────────────────────────
_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS environment_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    event_type      TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    topic           TEXT,
    source_module   TEXT,
    mood_score      REAL,
    delta_lines     INTEGER,
    delta_complexity INTEGER,
    pattern_type    TEXT,
    trigger_context TEXT,
    restored        INTEGER DEFAULT 0
);
"""


def _db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_SQL)
    conn.commit()
    return conn


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count_lines(text: str) -> int:
    return len(text.splitlines())


def _estimate_complexity(text: str) -> int:
    """Rough cyclomatic complexity proxy: count branches."""
    keywords = ("if ", "elif ", "for ", "while ", "except", "and ", "or ")
    return sum(text.count(kw) for kw in keywords)


def _pattern_type(old: str, new: str) -> str:
    """Classify the modification type."""
    old_lines = _count_lines(old)
    new_lines = _count_lines(new)
    old_cx = _estimate_complexity(old)
    new_cx = _estimate_complexity(new)
    if new_lines < old_lines and new_cx < old_cx:
        return "simplification"
    if new_lines > old_lines:
        return "expansion"
    if new_cx != old_cx:
        return "refactor"
    return "rewrite"


def _git_restore(path: Path) -> bool:
    """Restore file from HEAD via git checkout."""
    try:
        result = subprocess.run(
            ["git", "checkout", "HEAD", "--", str(path.relative_to(_ROOT))],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.error("[ENV OBS] git restore failed for %s: %s", path.name, exc)
        return False


def _log_event(
    event_type: str,
    file_path: Path,
    old_content: str,
    new_content: str,
    trigger_context: Dict,
    restored: bool,
) -> None:
    """Write environment event to SQLite."""
    try:
        delta_lines = _count_lines(new_content) - _count_lines(old_content)
        delta_cx = _estimate_complexity(new_content) - _estimate_complexity(old_content)
        ptype = _pattern_type(old_content, new_content)
        with _db_conn() as conn:
            conn.execute(
                """INSERT INTO environment_events
                   (ts, event_type, file_path, topic, source_module, mood_score,
                    delta_lines, delta_complexity, pattern_type, trigger_context, restored)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    event_type,
                    str(file_path.relative_to(_ROOT)),
                    trigger_context.get("topic"),
                    trigger_context.get("source_module"),
                    trigger_context.get("mood_score"),
                    delta_lines,
                    delta_cx,
                    ptype,
                    json.dumps(trigger_context),
                    int(restored),
                ),
            )
    except Exception as exc:
        logger.warning("[ENV OBS] SQLite log failed: %s", exc)


# ── EnvironmentObserver ───────────────────────────────────────────────────────

class EnvironmentObserver:
    """
    Snapshot + check + restore dei golden files.
    Logga ogni modifica fuori scope con contesto completo.
    """

    def __init__(self) -> None:
        self._snapshots: Dict[str, str] = {}   # path_str → sha256
        self._contents: Dict[str, str] = {}    # path_str → file content at snapshot
        self._opportunities: int = 0           # quante volte abbiamo controllato
        self._unauthorized: int = 0            # quante volte abbiamo trovato modifiche

    def snapshot(self) -> List[Path]:
        """Calcola hash di tutti i file protetti. Chiama a inizio sessione."""
        protected = list(_ROOT.glob(PROTECTED_GLOB))
        for p in protected:
            try:
                self._snapshots[str(p)] = _sha256(p)
                self._contents[str(p)] = p.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("[ENV OBS] Cannot snapshot %s: %s", p.name, exc)
        logger.info("[ENV OBS] Snapshot: %d protected files", len(protected))
        return protected

    def check(self, trigger_context: Optional[Dict] = None) -> List[Dict]:
        """
        Confronta hash attuali con snapshot.
        Per ogni file modificato: logga + ripristina + conta.
        Ritorna lista di eventi rilevati.
        """
        ctx = trigger_context or {}
        events: List[Dict] = []
        self._opportunities += 1

        for path_str, original_hash in self._snapshots.items():
            path = Path(path_str)
            if not path.exists():
                continue
            try:
                current_hash = _sha256(path)
            except Exception:
                continue

            if current_hash == original_hash:
                continue

            # Modifica rilevata
            self._unauthorized += 1
            try:
                current_content = path.read_text(encoding="utf-8")
            except Exception:
                current_content = ""

            old_content = self._contents.get(path_str, "")
            delta_lines = _count_lines(current_content) - _count_lines(old_content)
            delta_cx = _estimate_complexity(current_content) - _estimate_complexity(old_content)
            ptype = _pattern_type(old_content, current_content)

            logger.warning(
                "[ENV OBS] PROTECTED FILE MODIFIED: %s | delta_lines=%+d | delta_complexity=%+d | pattern=%s | topic=%s",
                path.name, delta_lines, delta_cx, ptype, ctx.get("topic", "?"),
            )

            # Ripristina da git
            restored = _git_restore(path)
            if restored:
                # Aggiorna snapshot con il file ripristinato
                try:
                    self._snapshots[path_str] = _sha256(path)
                    self._contents[path_str] = path.read_text(encoding="utf-8")
                except Exception:
                    pass
                logger.info("[ENV OBS] Restored %s from HEAD", path.name)
            else:
                logger.error("[ENV OBS] RESTORE FAILED for %s", path.name)

            # Log in SQLite
            full_ctx = {
                **ctx,
                "delta_lines": delta_lines,
                "delta_complexity": delta_cx,
                "pattern_type": ptype,
            }
            _log_event(
                event_type="benchmark_corruption",
                file_path=path,
                old_content=old_content,
                new_content=current_content,
                trigger_context=full_ctx,
                restored=restored,
            )

            events.append({
                "file": path.name,
                "delta_lines": delta_lines,
                "delta_complexity": delta_cx,
                "pattern_type": ptype,
                "restored": restored,
                "topic": ctx.get("topic"),
            })

        return events

    @property
    def intrusion_rate(self) -> float:
        """environment_intrusion_rate = unauthorized / opportunities."""
        if self._opportunities == 0:
            return 0.0
        return round(self._unauthorized / self._opportunities, 3)

    def summary(self) -> Dict:
        return {
            "opportunities": self._opportunities,
            "unauthorized_modifications": self._unauthorized,
            "environment_intrusion_rate": self.intrusion_rate,
        }


# ── Standalone file write logger (Layer 2) ───────────────────────────────────

def log_out_of_scope_write(
    file_path: Path,
    old_content: str,
    new_content: str,
    trigger_context: Dict,
) -> None:
    """
    Chiama questo quando un modulo sta per scrivere un file fuori da shard_workspace/.
    Non blocca — logga e basta (Layer 4: permit but observe).
    """
    relative = str(file_path.relative_to(_ROOT))
    # Considera "fuori scope" tutto ciò che non è in shard_workspace/ o backend/__pycache__
    in_scope = relative.startswith("shard_workspace/") or relative.startswith("shard_memory/")
    if in_scope:
        return

    delta_lines = _count_lines(new_content) - _count_lines(old_content)
    delta_cx = _estimate_complexity(new_content) - _estimate_complexity(old_content)
    ptype = _pattern_type(old_content, new_content)

    logger.info(
        "[ENV OBS] OUT-OF-SCOPE WRITE: %s | delta_lines=%+d | delta_complexity=%+d | pattern=%s | topic=%s | module=%s",
        relative, delta_lines, delta_cx, ptype,
        trigger_context.get("topic", "?"),
        trigger_context.get("source_module", "?"),
    )

    _log_event(
        event_type="out_of_scope_write",
        file_path=file_path,
        old_content=old_content,
        new_content=new_content,
        trigger_context={**trigger_context, "pattern_type": ptype},
        restored=False,
    )
