"""Strategy Memory -- Persistent storage of successful learning strategies.

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

# ── Protocol inference ────────────────────────────────────────────────────────
_UDP_KEYWORDS = ["udp", "datagram", "recvfrom", "sendto", "checksum", "packet loss"]
_TCP_KEYWORDS = ["tcp", "http", "https", "ftp", "smtp", "websocket", "keep-alive",
                 "web server", "sock_stream"]


def _infer_protocol(text: str) -> str:
    """Return 'UDP', 'TCP', or 'ANY' based on topic/strategy keywords."""
    t = text.lower()
    if any(kw in t for kw in _UDP_KEYWORDS):
        return "UDP"
    if any(kw in t for kw in _TCP_KEYWORDS):
        return "TCP"
    return "ANY"


class StrategyMemory:
    def __init__(self):
        # Usa il singleton db_manager -- elimina il secondo client ChromaDB indipendente
        self.collection = get_collection(
            DB_PATH_STRATEGY_DB,
            name="strategy_memory",
            metadata={"description": "Successful learning strategies from experiments"}
        )
        # One writer at a time -- prevents concurrent NightRunner/SessionOrchestrator races
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

        print(f"[STRATEGY] Updated stats -> runs={runs} avg={avg_score} success={success_rate}")

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
                "protocol": _infer_protocol(topic + " " + strategy),
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

    @staticmethod
    def extract_from_diff(diff: str) -> str | None:
        """Extract an actionable strategy string from a code diff.

        Heuristic pattern matching -- covers the most common benchmark fix patterns.
        Returns a short actionable string or None if no pattern matched.
        """
        d = diff.lower()

        if "rlock" in d and ("lock(" in d or "threading" in d):
            return "Replace Lock with RLock for re-entrant locking"
        if (
            "_calibrated" in d
            or '"calibrated"' in d
            or "not in r" in d
            or ("idempot" in d and "return" in d)
            or ("already" in d and ("processed" in d or "calibrat" in d or "applied" in d))
        ):
            return "Add idempotency guard: check flag before applying transformation, skip if already done"
        if "deepcopy" in d or ("copy(" in d and ("import copy" in d or "from copy" in d)):
            return "Avoid mutation by deepcopying input before applying transformations"
        if "sorted(" in d and ("lock" in d or "acquire" in d):
            return "Acquire locks in sorted order by ID to prevent circular waits and deadlock"
        if "\\b" in d and ("regex" in d or "re." in d or "pattern" in d):
            return "Use conditional word boundaries in regex: \\b for alphanumeric tokens only, not punctuation tags"
        if "(?<!" in d or "(?!" in d:
            return "Use negative lookaround in regex to exclude escaped sequences like {{ }}"
        if "ttl" in d and ("expired" in d or "evict" in d or "expir" in d):
            return "Check TTL expiry on cache read not only on write -- evict stale entries before returning"
        if "thread" in d and ("lock" in d or "join" in d or "semaphore" in d):
            return "Use threading.Lock to protect shared state accessed from multiple threads"
        if "range(len(" in d and ("- 1)" in d or "-1)" in d):
            return "Add boundary guard: iterate range(len(data)-1) when accessing consecutive elements to avoid IndexError"
        if "range(1," in d and "len(" in d:
            return "Exclude first and last elements from range when checking neighbors to avoid out-of-bounds access"
        if "split(" in d and (", 1)" in d or "maxsplit" in d):
            return "Use split with maxsplit=1 to handle values containing the delimiter character"
        if ".strip()" in d and ("key" in d or "value" in d or "parse" in d or "token" in d):
            return "Strip whitespace from parsed tokens before use to avoid key mismatch on padded input"
        if ".get(" in d and ("default" in d or "none" in d or "config" in d or "key" in d):
            return "Use dict.get() with a default instead of direct key access to avoid KeyError on missing keys"
        if "startswith(" in d and ("#" in d or "comment" in d):
            return "Skip empty and comment lines when parsing line-by-line input"
        if "isinstance(" in d and ("dict" in d or "list" in d or "str" in d or "int" in d):
            return "Add type guard with isinstance() before accessing type-specific attributes or keys"
        if "sorted(" in d and "id" in d:
            return "Sort items by ID before processing to ensure consistent ordering"

        return None

    def store_from_benchmark(
        self,
        task_key: str,
        prev_code: str,
        winning_code: str,
        attempts_used: int,
    ) -> None:
        """Extract and store a strategy from a benchmark victory diff.

        Called at VICTORY time in benchmark_loop. Diffs last failed attempt vs
        winning code to find what actually changed. Only stores on pattern match.
        """
        import difflib
        diff = "\n".join(
            difflib.unified_diff(
                prev_code.splitlines(),
                winning_code.splitlines(),
                lineterm="",
                n=0,
            )
        )
        strategy_text = self.extract_from_diff(diff)
        if not strategy_text:
            # Log first 200 chars of diff to diagnose missing patterns
            diff_preview = diff[:200].replace('\n', ' ')
            print(f"  [strategy] No pattern matched for '{task_key}' | diff: {diff_preview}")
            return

        # Score heuristic: faster victories = higher confidence
        score = max(5.0, round(10.0 - (attempts_used - 1) * 1.5, 1))
        self.store_strategy(
            topic=f"benchmark:{task_key}",
            strategy=strategy_text,
            outcome="success",
            score=score,
        )
        print(f"  [strategy] Stored from diff: '{strategy_text}' (score={score})")

    @staticmethod
    def _recency_boost(timestamp_str: str) -> float:
        """Decays from 1.0 (just used) toward 0 over time. Half-life = 168h (1 week)."""
        try:
            ts = datetime.fromisoformat(timestamp_str)
            hours = (datetime.now() - ts).total_seconds() / 3600.0
            return 1.0 / (1.0 + hours / 168.0)
        except Exception:
            return 0.5

    @staticmethod
    def _filter_by_protocol(strategies: List[Dict], query_protocol: str) -> List[Dict]:
        """Hard-filter strategies by protocol, with controlled fallback.

        Priority:
          1. Same protocol (e.g. UDP query → UDP strategies)
          2. ANY (protocol-agnostic strategies)
          3. Full list (fallback if nothing else matches — preserves recall)
        """
        if query_protocol == "ANY":
            return strategies  # no constraint — return all
        same = [s for s in strategies if s.get("protocol", "ANY") == query_protocol]
        if same:
            return same
        any_ok = [s for s in strategies if s.get("protocol", "ANY") == "ANY"]
        return any_ok if any_ok else strategies

    def query(
        self,
        topic: str,
        k: int = 3,
        cross_inject_queries: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Retrieve the most relevant strategies for a topic (sync).

        Args:
            topic               : primary query string
            k                   : max results from primary query
            cross_inject_queries: extra query strings from cross_task_router (#22)
                                  Each contributes up to 2 extra results.
        """
        if self.collection.count() == 0:
            return []

        query_protocol = _infer_protocol(topic)
        results = self.collection.query(
            query_texts=[topic],
            n_results=min(k, self.collection.count()),
            include=["documents", "metadatas", "ids", "distances"],
        )

        strategies = []
        seen_ids: set = set()

        if results and results["documents"]:
            ids       = results.get("ids",       [[]])[0]
            distances = results.get("distances", [[]])[0]
            for i, doc in enumerate(results["documents"][0]):
                doc_id   = ids[i] if i < len(ids) else None
                meta     = results["metadatas"][0][i] if results["metadatas"] else {}
                dist     = distances[i] if i < len(distances) else 1.0
                sem_sim  = max(0.0, 1.0 - dist)
                s_rate   = float(meta.get("success_rate", meta.get("score", 5.0)) or 0.0)
                # Normalise success_rate: stored as 0-1 fraction OR 0-10 score
                if s_rate > 1.0:
                    s_rate = s_rate / 10.0
                recency  = self._recency_boost(meta.get("timestamp", ""))
                utility  = round(sem_sim * 0.5 + s_rate * 0.3 + recency * 0.2, 4)
                strategies.append({
                    "strategy":      doc,
                    "topic":         meta.get("topic", ""),
                    "outcome":       meta.get("outcome", ""),
                    "score":         float(meta.get("score", 0)),
                    "protocol":      meta.get("protocol", "ANY"),
                    "utility_score": utility,
                })
                if doc_id:
                    seen_ids.add(doc_id)

        strategies = self._filter_by_protocol(strategies, query_protocol)
        if query_protocol != "ANY":
            logger.debug(
                "[STRATEGY] protocol filter: query=%s → %d/%d candidates kept",
                query_protocol, len(strategies),
                results["documents"][0].__len__() if results and results["documents"] else 0,
            )

        # Re-rank by utility score (ACT-R production utility)
        strategies.sort(key=lambda s: s.get("utility_score", 0.0), reverse=True)
        strategies = strategies[:k]

        # #22 Cross-inject: fetch up to 2 results per extra query, deduplicate by id
        if cross_inject_queries:
            for cq in cross_inject_queries:
                try:
                    cq_results = self.collection.query(
                        query_texts=[cq],
                        n_results=min(2, self.collection.count()),
                        include=["documents", "metadatas", "ids", "distances"],
                    )
                    if cq_results and cq_results["documents"]:
                        cq_ids  = cq_results.get("ids",       [[]])[0]
                        cq_dists = cq_results.get("distances", [[]])[0]
                        for j, doc in enumerate(cq_results["documents"][0]):
                            doc_id = cq_ids[j] if j < len(cq_ids) else None
                            if doc_id and doc_id in seen_ids:
                                continue
                            meta    = cq_results["metadatas"][0][j] if cq_results.get("metadatas") else {}
                            dist    = cq_dists[j] if j < len(cq_dists) else 1.0
                            sem_sim = max(0.0, 1.0 - dist)
                            s_rate  = float(meta.get("success_rate", meta.get("score", 5.0)) or 0.0)
                            if s_rate > 1.0:
                                s_rate = s_rate / 10.0
                            recency = self._recency_boost(meta.get("timestamp", ""))
                            utility = round(sem_sim * 0.5 + s_rate * 0.3 + recency * 0.2, 4)
                            strategies.append({
                                "strategy":      doc,
                                "topic":         meta.get("topic", ""),
                                "outcome":       meta.get("outcome", ""),
                                "score":         float(meta.get("score", 0)),
                                "utility_score": utility,
                            })
                            if doc_id:
                                seen_ids.add(doc_id)
                except Exception as exc:
                    logger.debug("[strategy] cross-inject query failed for '%s': %s", cq[:40], exc)

        return strategies

    async def query_async(
        self,
        topic: str,
        k: int = 3,
        cross_inject_queries: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Async wrapper -- non blocca l'event loop durante la query ChromaDB."""
        return await asyncio.to_thread(self.query, topic, k, cross_inject_queries)

    def update_evolved_strategy_score(
        self, topic: str, strategy_text: str, real_score: float, real_outcome: str
    ) -> bool:
        """Update the score and outcome of a previously stored 'evolved' strategy.

        Called after a cycle completes to replace the placeholder score=5.0 with
        the real outcome, closing the EvoScientist feedback loop.

        Finds the record by matching topic + outcome='evolved' + strategy text.
        Returns True if a record was updated, False otherwise.
        """
        try:
            results = self.collection.get(where={"topic": topic})
            if not results or not results.get("ids"):
                return False

            # Find the evolved record matching this strategy text
            target_id: str | None = None
            target_meta: dict | None = None
            for rec_id, meta, doc in zip(
                results["ids"],
                results.get("metadatas", []),
                results.get("documents", []),
            ):
                if meta.get("outcome") == "evolved" and doc.strip() == strategy_text.strip():
                    target_id = rec_id
                    target_meta = dict(meta)
                    break

            if target_id is None:
                logger.debug(
                    "[EVOSCI] update_evolved: no matching evolved record for topic='%s'", topic[:60]
                )
                return False

            # Update metadata in-place: real score + outcome
            target_meta["score"] = str(real_score)
            target_meta["outcome"] = real_outcome
            target_meta["evolved_real_score"] = str(real_score)   # audit trail
            self.collection.update(ids=[target_id], metadatas=[target_meta])
            logger.info(
                "[EVOSCI] Updated evolved strategy '%s' → score=%.1f outcome=%s",
                topic[:60], real_score, real_outcome,
            )
            return True
        except Exception as exc:
            logger.warning("[EVOSCI] update_evolved non-fatal: %s", exc)
            return False

    async def update_evolved_strategy_score_async(
        self, topic: str, strategy_text: str, real_score: float, real_outcome: str
    ) -> bool:
        """Async-safe wrapper for update_evolved_strategy_score."""
        async with self._lock:
            return await asyncio.to_thread(
                self.update_evolved_strategy_score, topic, strategy_text, real_score, real_outcome
            )

    async def store_strategy_async(self, topic: str, strategy: str, outcome: str, score: float = 0.0):
        """Async-safe write -- serialises concurrent NightRunner/SessionOrchestrator calls."""
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
                print(f"[STRATEGY] PIVOT: cleared {len(ids)} strateg{'y' if len(ids)==1 else 'ies'} for '{topic}' -- forcing new approach")
                return len(ids)
            return 0
        except Exception as exc:
            print(f"[STRATEGY] PIVOT failed for '{topic}': {exc}")
            return 0

    # ── Strategy quality filters ──────────────────────────────────────────────

    @staticmethod
    def _is_noise(text: str) -> bool:
        """True if text is a session log / KB artifact -- not an actionable strategy."""
        t = text.lower()
        noise_markers = [
            "sandbox:", "success --", "traceback", "concepts:",
            "gaps identified:", "focus on:", "stdout", "output:",
            "code executed", "failed to", "docker",
        ]
        return any(m in t for m in noise_markers)

    @staticmethod
    def _looks_actionable(text: str) -> bool:
        """True if text contains action verbs and is short enough to be a directive."""
        if len(text) < 20 or len(text) > 300:
            return False
        action_verbs = [
            "use ", "replace ", "add ", "ensure ", "avoid ",
            "check ", "return ", "wrap ", "initialize ", "apply ",
            "acquire ", "sort ", "copy ", "deepcopy", "guard",
        ]
        t = text.lower()
        return any(v in t for v in action_verbs)

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
                parts.append(f"Sandbox: SUCCESS -- code executed without errors")
                if sandbox.get("stdout"):
                    parts.append(f"Output: {sandbox['stdout'][:200]}")
            else:
                stderr = sandbox.get("stderr", "")
                parts.append(f"Sandbox: FAILED -- {stderr[:150]}")

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
