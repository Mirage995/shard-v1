"""skill_library.py -- Voyager-inspired persistent skill library for SHARD.

Every certified skill is stored with its approach and score.
When SHARD studies a related topic, past certified solutions are injected
as context -- so SHARD never re-invents what it already knows.

Two components:
  1. SkillLibrary -- save/retrieve certified skills from SQLite
  2. suggest_curriculum_topics() -- proactive next-topic suggestion via GraphRAG

Design rules:
  - Storage is SQLite only (shard.db, table skill_library)
  - No LLM calls: this is pure data plumbing
  - Injection block is compact (<300 chars per skill, max 3 skills shown)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("shard.skill_library")

# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS skill_library (
    topic        TEXT PRIMARY KEY,
    score        REAL,
    session_id   TEXT,
    strategies   TEXT,    -- JSON list of strategy names reused during certification
    certified_at TEXT
)
"""

_CREATE_IMPL_SQL = """
CREATE TABLE IF NOT EXISTS skill_implementations (
    topic        TEXT PRIMARY KEY,
    code         TEXT,    -- exact code that passed the benchmark
    score        REAL,
    pass_rate    REAL,    -- 0.0-1.0 benchmark pass rate at certification
    saved_at     TEXT
)
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _db_query(sql: str, params: tuple = ()):
    from shard_db import query as q
    return q(sql, params)

def _db_execute(sql: str, params: tuple = ()):
    from shard_db import execute as e
    return e(sql, params)

def _ensure_table():
    try:
        _db_execute(_CREATE_SQL)
        _db_execute(_CREATE_IMPL_SQL)
    except Exception as exc:
        logger.warning("[SKILL_LIB] table init failed: %s", exc)


# ── SkillLibrary ──────────────────────────────────────────────────────────────

class SkillLibrary:
    """Save and retrieve certified skills to avoid regression."""

    def save_skill(
        self,
        topic: str,
        score: float,
        session_id: str = "",
        strategies: Optional[list] = None,
    ) -> None:
        """Persist a certified skill. Upserts on topic (keeps best score)."""
        _ensure_table()
        try:
            existing = _db_query(
                "SELECT score FROM skill_library WHERE topic = ?", (topic,)
            )
            strats_json = json.dumps(strategies or [])
            now = datetime.now().isoformat()

            if existing:
                # Only update if new score is better
                if score >= existing[0]["score"]:
                    _db_execute(
                        "UPDATE skill_library SET score=?, session_id=?, strategies=?, certified_at=? WHERE topic=?",
                        (score, session_id, strats_json, now, topic),
                    )
                    logger.info("[SKILL_LIB] Updated '%s' score %.1f -> %.1f", topic, existing[0]["score"], score)
            else:
                _db_execute(
                    "INSERT INTO skill_library (topic, score, session_id, strategies, certified_at) VALUES (?,?,?,?,?)",
                    (topic, score, session_id, strats_json, now),
                )
                logger.info("[SKILL_LIB] Saved new skill '%s' (score=%.1f)", topic, score)
        except Exception as exc:
            logger.warning("[SKILL_LIB] save_skill failed: %s", exc)

    def get_skill(self, topic: str) -> Optional[dict]:
        """Return the stored entry for a topic, or None."""
        _ensure_table()
        try:
            rows = _db_query("SELECT * FROM skill_library WHERE topic = ?", (topic,))
            return rows[0] if rows else None
        except Exception:
            return None

    def get_all_certified(self) -> list[str]:
        """Return all topics in the skill library."""
        _ensure_table()
        try:
            rows = _db_query("SELECT topic FROM skill_library ORDER BY certified_at DESC")
            return [r["topic"] for r in rows]
        except Exception:
            return []

    # ── Skill implementations (Voyager #13) ───────────────────────────────────

    def save_implementation(
        self,
        topic: str,
        code: str,
        score: float,
        pass_rate: float,
    ) -> None:
        """Save the exact code that passed the benchmark for a certified topic.

        Only saves if pass_rate >= 0.80 -- partial passes may have hidden bugs.
        Upserts: keeps the implementation with the highest score.
        """
        if not code or not code.strip():
            return
        if pass_rate < 0.80:
            logger.debug("[SKILL_LIB] impl not saved for '%s': pass_rate=%.0f%% < 80%%", topic, pass_rate * 100)
            return
        _ensure_table()
        try:
            existing = _db_query(
                "SELECT score FROM skill_implementations WHERE topic = ?", (topic,)
            )
            if existing and existing[0]["score"] >= score:
                return  # keep the better implementation
            _db_execute(
                """
                INSERT INTO skill_implementations (topic, code, score, pass_rate, saved_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET
                    code=excluded.code, score=excluded.score,
                    pass_rate=excluded.pass_rate, saved_at=excluded.saved_at
                """,
                (topic, code.strip(), score, pass_rate, datetime.now().isoformat()),
            )
            logger.info("[SKILL_LIB] Implementation saved for '%s' (score=%.1f, pass_rate=%.0f%%)",
                        topic, score, pass_rate * 100)
        except Exception as exc:
            logger.warning("[SKILL_LIB] save_implementation failed: %s", exc)

    def get_implementation_block(self, topic: str, similarity_threshold: float = 0.5) -> str:
        """Return a compact injection block with past working code for similar topics.

        Only injects if topic is similar but not identical (0.50 <= similarity <= 0.85)
        to avoid verbatim copy on re-study and irrelevant code on distant topics.
        Returns "" if nothing useful found.
        """
        _ensure_table()
        try:
            rows = _db_query(
                "SELECT topic, code, score, pass_rate FROM skill_implementations ORDER BY score DESC LIMIT 20"
            )
            if not rows:
                return ""

            # Find the most similar past implementation (not the exact same topic)
            try:
                from sentence_transformers import SentenceTransformer, util
                model = SentenceTransformer("all-MiniLM-L6-v2")
                topic_emb = model.encode(topic, convert_to_tensor=True)
                best_row = None
                best_sim = 0.0
                for r in rows:
                    if r["topic"].lower() == topic.lower():
                        continue
                    emb = model.encode(r["topic"], convert_to_tensor=True)
                    sim = float(util.cos_sim(topic_emb, emb))
                    if similarity_threshold <= sim <= 0.85 and sim > best_sim:
                        best_sim = sim
                        best_row = r
            except Exception:
                best_row = None

            if not best_row:
                return ""

            code_preview = best_row["code"][:600] + ("..." if len(best_row["code"]) > 600 else "")
            return (
                f"[PAST WORKING CODE -- adapt, don't copy]\n"
                f"Topic: {best_row['topic']} | score={best_row['score']:.1f} | "
                f"pass_rate={best_row['pass_rate']:.0%}\n"
                f"```python\n{code_preview}\n```"
            )
        except Exception as exc:
            logger.debug("[SKILL_LIB] get_implementation_block failed: %s", exc)
            return ""

    def get_injection_block(self, topic: str, capability_graph=None) -> str:
        """
        Build a compact text block of relevant past certified skills to inject
        into the study prompt before SHARD works on `topic`.

        Looks for:
          1. Exact match (topic already certified -> reinforcement/review note)
          2. GraphRAG relatives: topics linked via extends/improves/requires/depends_on
        """
        _ensure_table()
        relevant: list[dict] = []

        try:
            # 1. Exact match
            exact = self.get_skill(topic)
            if exact:
                relevant.append({"match": "exact", **exact})

            # 2. GraphRAG relatives
            if capability_graph is not None:
                try:
                    from shard_db import query as db_query
                    # Relations FROM topic (topic -> other)
                    out_rows = db_query(
                        "SELECT target, relation_type FROM knowledge_graph "
                        "WHERE source = ? AND relation_type IN ('extends','improves','requires','depends_on')",
                        (topic,),
                    )
                    # Relations TO topic (other -> topic)
                    in_rows = db_query(
                        "SELECT source as target, relation_type FROM knowledge_graph "
                        "WHERE target = ? AND relation_type IN ('extends','improves','requires','depends_on')",
                        (topic,),
                    )
                    related_topics = {r["target"] for r in out_rows + in_rows}

                    for rel_topic in related_topics:
                        if rel_topic == topic:
                            continue
                        skill = self.get_skill(rel_topic)
                        if skill:
                            relevant.append({"match": "related", **skill})
                except Exception as _grag_err:
                    logger.debug("[SKILL_LIB] GraphRAG lookup failed: %s", _grag_err)
        except Exception as exc:
            logger.debug("[SKILL_LIB] get_injection_block error: %s", exc)

        if not relevant:
            return ""

        # Deduplicate (exact match wins over related)
        seen: set[str] = set()
        deduped: list[dict] = []
        for s in sorted(relevant, key=lambda x: (0 if x["match"] == "exact" else 1, -x["score"])):
            if s["topic"] not in seen:
                seen.add(s["topic"])
                deduped.append(s)

        lines = ["=== SHARD SKILL LIBRARY -- relevant certified skills ==="]
        for s in deduped[:3]:  # max 3 to keep prompt compact
            strats = json.loads(s.get("strategies") or "[]")
            strat_note = f" via {', '.join(strats[:2])}" if strats else ""
            match_note = " [THIS TOPIC -- review/reinforce]" if s["match"] == "exact" else " [related]"
            lines.append(
                f"• {s['topic']} -- score {s['score']:.1f}/10{strat_note}{match_note}"
            )
        lines.append("Use these as foundation. Do not re-derive what you already know.")
        return "\n".join(lines)

    # ── CognitionCore interface ───────────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to environment events from CognitionCore."""
        if event_type == "skill_certified":
            topic = data.get("topic", "")
            score = data.get("score", 7.5)
            if topic:
                # Event-driven save (fallback: NightRunner also calls directly with strategies)
                self.save_skill(topic=topic, score=score)

    def get_stats(self) -> dict:
        """Return library statistics."""
        _ensure_table()
        try:
            rows = _db_query("SELECT COUNT(*) as n, AVG(score) as avg_score, MAX(score) as max_score FROM skill_library")
            r = rows[0] if rows else {}
            return {
                "total_skills": r.get("n", 0),
                "avg_score":    round(r.get("avg_score") or 0.0, 2),
                "max_score":    r.get("max_score") or 0.0,
            }
        except Exception:
            return {"total_skills": 0, "avg_score": 0.0, "max_score": 0.0}


# ── Curriculum suggestion ─────────────────────────────────────────────────────

def suggest_curriculum_topics(
    certified_topics: set[str],
    curated_pool: list[str],
    top_n: int = 5,
) -> list[str]:
    """
    Proactive curriculum: propose next topics that directly extend already-
    certified skills, following GraphRAG 'extends'/'improves' edges.

    Returns up to `top_n` topic names not yet certified, ranked by how many
    certified prerequisites they have (most-ready first).

    Falls back to empty list silently on any error.
    """
    if not certified_topics:
        return []

    try:
        from shard_db import query as db_query

        # For each certified topic, find topics that require/extend it
        # Note: knowledge_graph columns are source_concept/target_concept (concept-level)
        # and topic_origin (the study topic that created the edge).
        placeholders = ",".join("?" * len(certified_topics))
        rows = db_query(
            f"SELECT source_concept, target_concept, topic_origin, relation_type FROM knowledge_graph "
            f"WHERE topic_origin IN ({placeholders}) "
            f"AND relation_type IN ('extends','improves','depends_on','requires')",
            tuple(certified_topics),
        )

        # Count how many certified prereqs each candidate topic_origin has
        from collections import defaultdict
        prereq_count: dict[str, int] = defaultdict(int)
        for r in rows:
            candidate = r["topic_origin"]
            if candidate and candidate not in certified_topics:
                prereq_count[candidate] += 1

        # Also look at outward edges from certified topic_origins
        rows2 = db_query(
            f"SELECT source_concept, target_concept, topic_origin, relation_type FROM knowledge_graph "
            f"WHERE topic_origin IN ({placeholders}) "
            f"AND relation_type IN ('extends','improves')",
            tuple(certified_topics),
        )
        for r in rows2:
            candidate = r["topic_origin"]
            if candidate and candidate not in certified_topics:
                prereq_count[candidate] += 1

        if not prereq_count:
            return []

        # Sort by prereq_count desc, then filter to topics in curated pool if possible
        ranked = sorted(prereq_count.items(), key=lambda x: -x[1])
        curated_set = set(curated_pool)

        # Prefer topics that are in the curated pool
        in_pool   = [t for t, _ in ranked if t in curated_set]
        out_pool  = [t for t, _ in ranked if t not in curated_set]
        result    = (in_pool + out_pool)[:top_n]

        logger.info("[CURRICULUM] Suggested %d topic(s): %s", len(result), result)
        return result

    except Exception as exc:
        logger.debug("[CURRICULUM] suggest failed: %s", exc)
        return []
