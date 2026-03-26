"""gap_detector.py — Autonomous gap detection for SHARD's self-improvement loop.

Analyzes benchmark failure history semantically and generates study topics
without any human input. This is the bridge between "SHARD failed at X"
and "SHARD decides to study X tonight".

Flow:
  1. Read all failed benchmark episodes
  2. Cluster failure error messages semantically (using SemanticMemory embeddings)
  3. For each cluster, identify the skill gap behind it
  4. Generate study topics and push to ImprovementEngine queue
  5. Report what was found

Usage:
    from gap_detector import GapDetector
    detector = GapDetector()
    report = detector.detect()
    print(report.summary())
"""
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_HERE   = Path(__file__).resolve().parent
_ROOT   = _HERE.parent
_MEMORY = _ROOT / "shard_memory"

# Error pattern → skill gap mappings (heuristic layer)
_ERROR_TO_SKILL = [
    (r"numpy|ndarray|truth value.*array|ambiguous",         "numpy array operations and boolean indexing"),
    (r"import.*not found|ModuleNotFound|No module",         "python module system and dependency management"),
    (r"recursion|maximum recursion|RecursionError",         "recursion and stack management in python"),
    (r"timeout|exceeded.*second|took too long",             "algorithm complexity and performance optimization"),
    (r"thread|race condition|concurrent|lock|deadlock",     "concurrent programming and thread safety python"),
    (r"async|await|coroutine|event loop",                   "asyncio and async patterns in python"),
    (r"KeyError|dict.*key|missing.*key",                    "python dictionary operations and error handling"),
    (r"TypeError.*NoneType|None.*has no attribute",         "null safety and defensive programming python"),
    (r"index.*out of range|list index",                     "python list indexing and bounds checking"),
    (r"encoding|codec|UnicodeDecodeError|UnicodeEncode",    "python string encoding and unicode handling"),
    (r"sql|inject|sanitize|escape",                         "sql injection prevention and input sanitization"),
    (r"regex|re\.|pattern|match|search",                    "regular expressions in python"),
    (r"assertion.*failed|AssertionError",                   "test driven development and assertion design"),
    (r"syntax.*error|SyntaxError|invalid syntax",           "python syntax and code structure"),
    (r"memory|heap|allocation|out of memory",               "memory management and optimization"),
    (r"json|parse|decode.*json|JSONDecodeError",            "json parsing and serialization python"),
    (r"http|request|response|status.*code|api",             "http client implementation python"),
    (r"file.*not found|FileNotFoundError|path.*exist",      "python file system operations"),
    (r"class|inherit|method.*resolution|MRO",               "python object oriented programming"),
    (r"generator|yield|iterator|StopIteration",             "python generators and coroutines"),
]


@dataclass
class GapReport:
    detected_at: str
    total_failures_analyzed: int
    gaps_found: list[dict]
    topics_queued: list[str]
    skipped: list[str]

    def summary(self) -> str:
        lines = [
            f"[GAP DETECTOR] {self.detected_at}",
            f"  Failures analyzed: {self.total_failures_analyzed}",
            f"  Gaps found:        {len(self.gaps_found)}",
            f"  Topics queued:     {len(self.topics_queued)}",
        ]
        for g in self.gaps_found:
            lines.append(f"  GAP: {g['skill']} (seen {g['count']}x)")
        return "\n".join(lines)


class GapDetector:
    """Detects knowledge gaps from benchmark failure history.

    Uses two layers:
      1. Heuristic regex patterns → fast, interpretable
      2. Semantic clustering via SemanticMemory → catches unknown patterns
    """

    def __init__(self, min_occurrences: int = 2):
        self.min_occurrences = min_occurrences

    def detect(self, enqueue: bool = True) -> GapReport:
        """Analyze failures and optionally enqueue study topics."""
        failures = self._load_failures()
        if not failures:
            return GapReport(
                detected_at=datetime.now().isoformat(),
                total_failures_analyzed=0,
                gaps_found=[], topics_queued=[], skipped=[],
            )

        # Layer 1: heuristic pattern matching
        skill_counts: dict[str, int] = defaultdict(int)
        skill_errors: dict[str, list] = defaultdict(list)

        for err in failures:
            err_lower = err.lower()
            matched = False
            for pattern, skill in _ERROR_TO_SKILL:
                if re.search(pattern, err_lower):
                    skill_counts[skill] += 1
                    skill_errors[skill].append(err[:100])
                    matched = True
                    break
            if not matched:
                # Layer 2: unclassified errors → try semantic clustering
                topic = self._semantic_gap(err)
                if topic:
                    skill_counts[topic] += 1
                    skill_errors[topic].append(err[:100])

        # Filter by minimum occurrences
        gaps = [
            {"skill": skill, "count": count, "examples": skill_errors[skill][:2]}
            for skill, count in sorted(skill_counts.items(), key=lambda x: -x[1])
            if count >= self.min_occurrences
        ]

        topics_queued = []
        skipped = []

        if enqueue and gaps:
            try:
                from improvement_engine import ImprovementEngine
                engine = ImprovementEngine()
                existing = set(engine.peek_queue())

                # Skip gaps already resolved by NightRunner (gap_resolutions.json)
                resolved: set[str] = set()
                _res_path = _MEMORY / "gap_resolutions.json"
                if _res_path.exists():
                    try:
                        resolved = set(json.loads(_res_path.read_text(encoding="utf-8")).keys())
                    except Exception:
                        pass

                new_topics = [
                    g["skill"] for g in gaps
                    if g["skill"] not in existing and g["skill"] not in resolved
                ]
                if new_topics:
                    added = engine.enqueue_topics(new_topics)
                    topics_queued = new_topics[:added]
                else:
                    skipped = [g["skill"] for g in gaps]
            except Exception as e:
                skipped = [g["skill"] for g in gaps]

        return GapReport(
            detected_at=datetime.now().isoformat(),
            total_failures_analyzed=len(failures),
            gaps_found=gaps,
            topics_queued=topics_queued,
            skipped=skipped,
        )

    def _load_failures(self) -> list[str]:
        """Extract all error summaries from failed benchmark episodes."""
        ep_path = _MEMORY / "benchmark_episodes.json"
        if not ep_path.exists():
            return []

        failures = []
        try:
            data = json.loads(ep_path.read_text(encoding="utf-8"))
            for task_key, sessions in data.items():
                if not isinstance(sessions, list):
                    continue
                for session in sessions:
                    if session.get("success"):
                        continue
                    for att in session.get("attempts", []):
                        err = att.get("error_summary", "").strip()
                        if err and len(err) > 15 and err != "(no details)":
                            failures.append(err)
        except Exception:
            pass

        return failures

    def _semantic_gap(self, error_text: str) -> Optional[str]:
        """Use semantic similarity to classify an unknown error pattern."""
        try:
            from semantic_memory import get_semantic_memory
            mem = get_semantic_memory()
            results = mem.query(error_text, top_k=1,
                                collections=["knowledge", "errors"])
            if results and results[0]["score"] > 0.5:
                # Use the knowledge base title as the study topic
                meta = results[0].get("metadata", {})
                title = meta.get("title", "")
                if title:
                    return title
        except Exception:
            pass
        return None
