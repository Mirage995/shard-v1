"""Strategy Memory — Persistent storage of successful learning strategies.

Stores strategies that worked during sandbox experiments so SHARD can
reuse successful methods in future studies. Uses ChromaDB for persistence
and semantic retrieval.
"""
import asyncio
import logging
import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from constants import SUCCESS_SCORE_THRESHOLD

from db_manager import get_collection, DB_PATH_STRATEGY_DB

logger = logging.getLogger("shard.strategy_memory")


class StrategyMemory:
    def __init__(self):
        # Usa il singleton db_manager — elimina il secondo client ChromaDB indipendente
        self.collection = get_collection(
            DB_PATH_STRATEGY_DB,
            name="strategy_memory",
            metadata={"description": "Successful learning strategies from experiments"}
        )
        # One writer at a time — prevents concurrent NightRunner/SessionOrchestrator races
        self._lock = asyncio.Lock()
        print(f"[STRATEGY] Memory initialized ({self.collection.count()} strategies stored)")

    @staticmethod
    def _is_junk_topic(topic: str) -> bool:
        """Reject recursive/garbage topic strings before storing."""
        t = topic.lower()
        return (
            t.count("integration of") >= 2
            or t.count("applied to") >= 2
            or len(topic) > 120
        )

    def store_strategy(self, topic: str, strategy: str, outcome: str, score: float = 0.0):
        """Save a strategy with its topic, description, and outcome."""
        if self._is_junk_topic(topic):
            print(f"[STRATEGY] Rejected junk topic (not storing): '{topic[:80]}'")
            return
        timestamp = datetime.now().isoformat()
        doc_id = f"strat_{timestamp}_{topic[:30].replace(' ', '_')}"

        # Compute running stats from all existing records for this topic
        runs = 1
        avg_score = round(score, 3)
        success_rate = 1.0 if score >= SUCCESS_SCORE_THRESHOLD else 0.0
        try:
            existing = self.collection.get(where={"topic": topic})
            if existing and existing.get("metadatas"):
                prev_scores = [float(m.get("score", 0)) for m in existing["metadatas"]]
                if prev_scores:
                    all_scores = prev_scores + [score]
                    runs = len(all_scores)
                    avg_score = round(sum(all_scores) / runs, 3)
                    success_rate = round(
                        sum(1 for s in all_scores if s >= SUCCESS_SCORE_THRESHOLD) / runs, 3
                    )
        except Exception:
            pass  # keep initial values on any collection error

        print(f"[STRATEGY] Updated stats → runs={runs} avg={avg_score} success={success_rate}")

        self.collection.add(
            documents=[strategy],
            metadatas=[{
                "topic": topic,
                "outcome": outcome,
                "score": str(score),
                "timestamp": timestamp,
                "runs": runs,
                "avg_score": avg_score,
                "success_rate": success_rate,
            }],
            ids=[doc_id]
        )
        print(f"[STRATEGY] Stored strategy for '{topic}' (outcome={outcome}, score={score})")

    def store_strategy_object(self, strategy):
        """Store a Strategy object."""
        from strategy_model import Strategy  # import here to avoid circular
        
        timestamp = datetime.now().isoformat()
        doc_id = f"strat_obj_{timestamp}_{strategy.id[:10]}"
        
        self.collection.add(
            documents=[f"{strategy.name}: {strategy.description}\nPattern: {' -> '.join(strategy.pattern)}"],
            metadatas=[{
                "strategy_id": strategy.id,
                "name": strategy.name,
                "description": strategy.description,
                "pattern": json.dumps(strategy.pattern),
                "success_rate": str(strategy.success_rate),
                "usage_count": strategy.usage_count,
                "domains": json.dumps(strategy.domains) if strategy.domains else "[]",
                "created_timestamp": strategy.created_timestamp,
                "last_used_timestamp": strategy.last_used_timestamp,
                "last_success_timestamp": strategy.last_success_timestamp,
                "timestamp": timestamp,
            }],
            ids=[doc_id]
        )
        print(f"[STRATEGY] Stored Strategy object '{strategy.name}' (id={strategy.id})")

    def query(self, topic: str, k: int = 3) -> List[Dict]:
        """Retrieve the most relevant strategies for a topic (sync)."""
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[topic],
            n_results=min(k, self.collection.count())
        )

        strategies = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                strategies.append({
                    "strategy": doc,
                    "topic": meta.get("topic", ""),
                    "outcome": meta.get("outcome", ""),
                    "score": float(meta.get("score", 0)),
                })
        return strategies

    async def query_async(self, topic: str, k: int = 3) -> List[Dict]:
        """Async wrapper — non blocca l'event loop durante la query ChromaDB."""
        return await asyncio.to_thread(self.query, topic, k)

    async def store_strategy_async(self, topic: str, strategy: str, outcome: str, score: float = 0.0):
        """Async-safe write — serialises concurrent NightRunner/SessionOrchestrator calls."""
        async with self._lock:
            await asyncio.to_thread(self.store_strategy, topic, strategy, outcome, score)

    async def store_strategy_object_async(self, strategy):
        """Async-safe write for Strategy objects."""
        async with self._lock:
            await asyncio.to_thread(self.store_strategy_object, strategy)

    async def get_all_strategies_async(self) -> List[Dict]:
        """Async wrapper per get_all_strategies."""
        return await asyncio.to_thread(self.get_all_strategies)

    async def get_success_rate_async(self) -> float:
        """Async wrapper per get_success_rate."""
        return await asyncio.to_thread(self.get_success_rate)

    def get_all_strategies(self):
        """
        Restituisce tutte le strategie memorizzate in ChromaDB.
        Serve al modulo MetaLearning per calcolare statistiche globali.
        """
        try:
            results = self.collection.get(include=["metadatas"])
            
            strategies = []
            
            for meta in results.get("metadatas", []):
                strategies.append(meta)
                
            return strategies
            
        except Exception as e:
            print(f"[STRATEGY] Failed to retrieve strategies: {e}")
            return []

    def get_success_rate(self) -> float:
        """Return global strategy success rate across stored records."""
        try:
            strategies = self.get_all_strategies()
            if not strategies:
                return 0.0

            success = 0
            total = 0

            for meta in strategies:
                total += 1
                if str(meta.get("outcome", "")).lower() == "success":
                    success += 1

            if total == 0:
                return 0.0

            return success / total
        except Exception:
            return 0.0

    def pivot_on_chronic_block(self, topic: str) -> int:
        """Cancella tutte le strategie per un topic in near-miss loop.

        Chiamato da night_runner quando lo stesso topic fallisce N volte
        consecutive con score < cert_threshold. Forza un approccio nuovo
        al prossimo tentativo cancellando la memoria strategica corrente.

        Returns:
            Numero di entry cancellate da ChromaDB.
        """
        try:
            existing = self.collection.get(where={"topic": topic})
            ids = existing.get("ids", [])
            if ids:
                self.collection.delete(ids=ids)
                print(f"[STRATEGY] PIVOT: cleared {len(ids)} strateg{'y' if len(ids)==1 else 'ies'} for '{topic}' — forcing new approach")
                return len(ids)
            return 0
        except Exception as exc:
            print(f"[STRATEGY] PIVOT failed for '{topic}': {exc}")
            return 0

    @staticmethod
    def extract_strategy(experiment: Dict) -> Optional[Dict]:
        """Extract a strategy description from an experiment result.

        Args:
            experiment: Dict with keys from study_topic context:
                - sandbox_result: {success, stdout, stderr, code}
                - eval_data: {score, verdict, gaps, ...}
                - structured: {concepts, codice_pratico, ...}
                - topic: str

        Returns:
            Dict with {strategy, outcome} or None if not extractable.
        """
        if not experiment:
            return None

        sandbox = experiment.get("sandbox_result")
        eval_data = experiment.get("eval_data", {})
        structured = experiment.get("structured", {})
        topic = experiment.get("topic", "unknown")

        score = float(eval_data.get("score", 0))
        verdict = eval_data.get("verdict", "FAIL")

        # Sanity Filter: Solo strategie con score decente o sandbox funzionante
        if score < 5.0 and verdict != "PASS":
            print(f"[STRATEGY] Strategia scartata (score insufficiente: {score}, {verdict})")
            return None

        # Only extract strategy if we have meaningful data
        if not sandbox and not structured:
            return None

        # Build strategy description from what worked
        parts = []

        # What concepts were studied
        concepts = structured.get("concepts", [])
        if concepts:
            concept_names = [c.get("name", c) if isinstance(c, dict) else str(c) for c in concepts[:5]]
            parts.append(f"Concepts: {', '.join(concept_names)}")

        # What code was tried
        code = ""
        if sandbox:
            code = sandbox.get("code", "")
            if sandbox.get("success"):
                parts.append(f"Sandbox: SUCCESS — code executed without errors")
                if sandbox.get("stdout"):
                    parts.append(f"Output: {sandbox['stdout'][:200]}")
            else:
                stderr = sandbox.get("stderr", "")
                parts.append(f"Sandbox: FAILED — {stderr[:150]}")

        # Evaluation insights
        stance = eval_data.get("shard_stance", "")
        if stance:
            parts.append(f"Insight: {stance[:200]}")

        gaps = eval_data.get("gaps", [])
        if gaps:
            parts.append(f"Gaps identified: {', '.join(str(x) for x in gaps[:3])}")

        if not parts:
            return None

        strategy = f"[{topic}] " + " | ".join(parts)
        outcome = "success" if verdict == "PASS" else "failure"

        return {
            "strategy": strategy[:1200],  # Cap to 1200 chars (same as memory gate)
            "outcome": outcome,
            "score": score,
        }
