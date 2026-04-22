"""epistemic_tracker.py — Track how much verified knowledge SHARD produces per session.

Metrics stored per session:
  - experiments confirmed/refuted/inconclusive/failed
  - new verified relations added to knowledge_graph
  - velocity score: confirmed / (total + 1)

stats.json is written to shard_workspace/stats.json for the Figma site dashboard.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("shard.epistemic_tracker")

_STATS_PATH = Path(__file__).resolve().parent.parent / "shard_workspace" / "stats.json"


class EpistemicTracker:
    def __init__(self):
        from shard_db import execute, query
        self._execute = execute
        self._query = query
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._execute("""
            CREATE TABLE IF NOT EXISTS epistemic_velocity_log (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id              TEXT    NOT NULL,
                session_date            TEXT    NOT NULL,
                topic                   TEXT,
                experiments_total       INTEGER DEFAULT 0,
                experiments_confirmed   INTEGER DEFAULT 0,
                experiments_refuted     INTEGER DEFAULT 0,
                experiments_inconclusive INTEGER DEFAULT 0,
                experiments_failed      INTEGER DEFAULT 0,
                gpu_cost_usd            REAL    DEFAULT 0.0,
                llm_calls_total         INTEGER DEFAULT 0,
                new_graph_relations     INTEGER DEFAULT 0,
                velocity_score          REAL    DEFAULT 0.0,
                created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def record_session(
        self,
        session_id: str,
        session_start_iso: str,
        topic: str = "",
        llm_calls: int = 0,
        gpu_cost: float = 0.0,
    ) -> dict:
        """Count experiment outcomes since session_start_iso, insert one row, return summary."""
        try:
            # Count from research_hypotheses (scientific experiments)
            rows = self._query(
                """
                SELECT status, COUNT(*) as cnt
                FROM research_hypotheses
                WHERE created_at >= ?
                GROUP BY status
                """,
                (session_start_iso,),
            )
            counts = {r["status"]: r["cnt"] for r in rows}
            total        = sum(counts.values())
            confirmed    = counts.get("CONFIRMED", 0)
            refuted      = counts.get("REFUTED", 0)
            inconclusive = counts.get("INCONCLUSIVE", 0)
            failed       = counts.get("FAILED", 0)

            # Count new verified relations added this session
            rel_rows = self._query(
                """
                SELECT COUNT(*) as cnt
                FROM knowledge_graph
                WHERE created_at >= ?
                  AND verified_status = 'verified'
                """,
                (session_start_iso,),
            )
            new_relations = rel_rows[0]["cnt"] if rel_rows else 0

            # Velocity: confirmed per (total experiments + 1 smoothing)
            velocity = round(confirmed / (total + 1), 4) if total >= 0 else 0.0

            self._execute(
                """
                INSERT INTO epistemic_velocity_log
                    (session_id, session_date, topic,
                     experiments_total, experiments_confirmed, experiments_refuted,
                     experiments_inconclusive, experiments_failed,
                     gpu_cost_usd, llm_calls_total, new_graph_relations, velocity_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, datetime.now().isoformat(), topic,
                    total, confirmed, refuted,
                    inconclusive, failed,
                    gpu_cost, llm_calls, new_relations, velocity,
                ),
            )

            result = {
                "session_id"   : session_id,
                "confirmed"    : confirmed,
                "total"        : total,
                "velocity"     : velocity,
                "new_relations": new_relations,
            }

            # Always export stats.json after recording
            try:
                self._export_stats_json()
            except Exception as _e:
                logger.warning("[EPISTEMIC] stats.json export failed: %s", _e)

            return result

        except Exception as exc:
            logger.error("[EPISTEMIC] record_session failed: %s", exc)
            return {"session_id": session_id, "confirmed": 0, "total": 0,
                    "velocity": 0.0, "new_relations": 0}

    def get_latest_stats(self) -> dict:
        """Return aggregated metrics for the Figma dashboard."""
        try:
            last_24h = self._query("""
                SELECT
                    COALESCE(SUM(experiments_total), 0)       as total,
                    COALESCE(SUM(experiments_confirmed), 0)   as confirmed,
                    COALESCE(SUM(experiments_refuted), 0)     as refuted,
                    COALESCE(SUM(experiments_inconclusive), 0) as inconclusive,
                    COALESCE(SUM(new_graph_relations), 0)     as new_relations,
                    COALESCE(AVG(velocity_score), 0)          as avg_velocity
                FROM epistemic_velocity_log
                WHERE created_at >= datetime('now', '-1 day')
            """)

            last_30d = self._query("""
                SELECT
                    COALESCE(SUM(experiments_confirmed), 0) as confirmed,
                    COALESCE(SUM(experiments_total), 0)     as total,
                    COALESCE(SUM(gpu_cost_usd), 0)          as gpu_cost,
                    COALESCE(AVG(velocity_score), 0)        as avg_velocity
                FROM epistemic_velocity_log
                WHERE created_at >= datetime('now', '-30 days')
            """)

            graph = self._query("""
                SELECT
                    COUNT(*)                                                  as total_relations,
                    COUNT(CASE WHEN verified_status = 'verified'  THEN 1 END) as verified,
                    COUNT(CASE WHEN verified_status = 'disputed'  THEN 1 END) as disputed
                FROM knowledge_graph
                WHERE confidence >= 0.6
            """)

            total_rel   = graph[0]["total_relations"] if graph else 1
            verified_rel = graph[0]["verified"] if graph else 0
            freshness   = round(verified_rel / max(total_rel, 1), 3)

            return {
                "last_24h": {
                    "experiments_total"    : last_24h[0]["total"],
                    "experiments_confirmed": last_24h[0]["confirmed"],
                    "experiments_refuted"  : last_24h[0]["refuted"],
                    "new_relations"        : last_24h[0]["new_relations"],
                    "avg_velocity"         : round(last_24h[0]["avg_velocity"], 3),
                },
                "last_30d": {
                    "confirmed"    : last_30d[0]["confirmed"],
                    "total"        : last_30d[0]["total"],
                    "gpu_cost_usd" : round(last_30d[0]["gpu_cost"], 2),
                    "avg_velocity" : round(last_30d[0]["avg_velocity"], 3),
                },
                "graphrag": {
                    "total_relations"   : total_rel,
                    "verified_relations": verified_rel,
                    "freshness"         : freshness,
                    "freshness_pct"     : f"{freshness * 100:.0f}%",
                },
                "velocity_trend": self._get_velocity_trend(7),
                "generated_at": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("[EPISTEMIC] get_latest_stats failed: %s", exc)
            return {}

    def _get_velocity_trend(self, days: int = 7) -> list:
        # SQLite: cannot use ? inside string literal — use concatenation
        rows = self._query(
            """
            SELECT
                date(created_at) as day,
                ROUND(AVG(velocity_score), 3) as avg_velocity,
                SUM(experiments_confirmed)    as confirmed
            FROM epistemic_velocity_log
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY date(created_at)
            ORDER BY day ASC
            """,
            (str(days),),
        )
        return [
            {"day": r["day"], "velocity": r["avg_velocity"], "confirmed": r["confirmed"]}
            for r in rows
        ]

    def _export_stats_json(self) -> None:
        stats = self.get_latest_stats()
        _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATS_PATH.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        logger.info("[EPISTEMIC] stats.json written to %s", _STATS_PATH)
