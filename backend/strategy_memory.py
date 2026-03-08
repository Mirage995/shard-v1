"""Strategy Memory — Persistent storage of successful learning strategies.

Stores strategies that worked during sandbox experiments so SHARD can
reuse successful methods in future studies. Uses ChromaDB for persistence
and semantic retrieval.
"""
import chromadb
import os
import json
from datetime import datetime
from typing import Dict, List, Optional

CHROMA_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'shard_memory', 'strategy_db')


class StrategyMemory:
    def __init__(self):
        os.makedirs(CHROMA_DB_PATH, exist_ok=True)
        self.client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        self.collection = self.client.get_or_create_collection(
            name="strategy_memory",
            metadata={"description": "Successful learning strategies from experiments"}
        )
        print(f"[STRATEGY] Memory initialized ({self.collection.count()} strategies stored)")

    def store_strategy(self, topic: str, strategy: str, outcome: str, score: float = 0.0):
        """Save a strategy with its topic, description, and outcome."""
        timestamp = datetime.now().isoformat()
        doc_id = f"strat_{timestamp}_{topic[:30].replace(' ', '_')}"

        self.collection.add(
            documents=[strategy],
            metadatas=[{
                "topic": topic,
                "outcome": outcome,
                "score": str(score),
                "timestamp": timestamp,
            }],
            ids=[doc_id]
        )
        print(f"[STRATEGY] Stored strategy for '{topic}' (outcome={outcome}, score={score})")

    def query(self, topic: str, k: int = 3) -> List[Dict]:
        """Retrieve the most relevant strategies for a topic."""
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
            parts.append(f"Gaps identified: {', '.join(gaps[:3])}")

        if not parts:
            return None

        strategy = f"[{topic}] " + " | ".join(parts)
        outcome = "success" if verdict == "PASS" else "failure"

        return {
            "strategy": strategy[:1200],  # Cap to 1200 chars (same as memory gate)
            "outcome": outcome,
            "score": score,
        }
