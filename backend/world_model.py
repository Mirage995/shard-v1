"""world_model.py -- SHARD's model of the external software world.

Answers the question: "what actually matters out there?" so SHARD
studies high-leverage skills instead of random topics.

Two layers:
  1. Static seed -- curated 2026 software landscape relevance scores
  2. Dynamic layer -- updated as SHARD certifies topics (tracks what
     it already knows vs what the world needs)

Influences:
  - GapDetector: high-relevance gaps get enqueued first
  - NightRunner topic selection: curated topics weighted by world relevance
  - Self-assessment: "I know X but the world prioritizes Y"

File written:
  shard_memory/world_model.json

Usage:
    from world_model import WorldModel
    wm = WorldModel.load_or_default()
    print(wm.relevance("asyncio and async patterns in python"))  # -> 0.92
    wm.mark_known("asyncio and async patterns in python", score=8.5)
    gaps = wm.priority_gaps(known_skills={"numpy", "asyncio"})
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

_ROOT   = Path(__file__).resolve().parents[1]
_MEMORY = _ROOT / "shard_memory"
_WORLD_MODEL_PATH = _MEMORY / "world_model.json"

# ── Static knowledge seed: 2026 software landscape ────────────────────────────
# relevance: 0.0–1.0 (how critical this skill is in real-world codebases)
# xp_leverage: how much knowing this helps with adjacent skills
_SEED: dict[str, dict] = {
    # Python -- core
    "asyncio and async patterns in python":         {"relevance": 0.95, "domain": "python", "xp_leverage": 1.4},
    "python generators and coroutines":             {"relevance": 0.88, "domain": "python", "xp_leverage": 1.3},
    "python typing system and generics":            {"relevance": 0.85, "domain": "python", "xp_leverage": 1.2},
    "python object oriented programming":           {"relevance": 0.80, "domain": "python", "xp_leverage": 1.1},
    "python dictionary operations and error handling": {"relevance": 0.82, "domain": "python", "xp_leverage": 1.0},
    "python list indexing and bounds checking":     {"relevance": 0.75, "domain": "python", "xp_leverage": 0.9},
    "python string encoding and unicode handling":  {"relevance": 0.72, "domain": "python", "xp_leverage": 0.9},
    "python file system operations":                {"relevance": 0.70, "domain": "python", "xp_leverage": 0.8},
    "python module system and dependency management": {"relevance": 0.78, "domain": "python", "xp_leverage": 1.0},
    "recursion and stack management in python":     {"relevance": 0.73, "domain": "python", "xp_leverage": 1.1},
    "null safety and defensive programming python": {"relevance": 0.80, "domain": "python", "xp_leverage": 1.0},
    "regular expressions in python":               {"relevance": 0.76, "domain": "python", "xp_leverage": 0.9},
    "json parsing and serialization python":        {"relevance": 0.77, "domain": "python", "xp_leverage": 0.9},

    # Python -- advanced
    "numpy array operations and boolean indexing":  {"relevance": 0.90, "domain": "data_science", "xp_leverage": 1.3},
    "concurrent programming and thread safety python": {"relevance": 0.87, "domain": "python", "xp_leverage": 1.3},
    "memory management and optimization":           {"relevance": 0.83, "domain": "systems", "xp_leverage": 1.2},
    "algorithm complexity and performance optimization": {"relevance": 0.91, "domain": "cs_fundamentals", "xp_leverage": 1.5},
    "test driven development and assertion design": {"relevance": 0.88, "domain": "engineering", "xp_leverage": 1.2},

    # Security
    "sql injection prevention and input sanitization": {"relevance": 0.92, "domain": "security", "xp_leverage": 1.3},
    "password hashing bcrypt argon2":               {"relevance": 0.10, "domain": "security", "xp_leverage": 0.3},  # sandbox-incompatible, filtered by is_valid_topic
    "http client implementation python":            {"relevance": 0.85, "domain": "networking", "xp_leverage": 1.2},

    # Data structures & algorithms
    "graph traversal algorithms bfs dfs":           {"relevance": 0.88, "domain": "cs_fundamentals", "xp_leverage": 1.4},
    "union find disjoint set":                      {"relevance": 0.75, "domain": "cs_fundamentals", "xp_leverage": 1.1},
    "sorting algorithms":                           {"relevance": 0.80, "domain": "cs_fundamentals", "xp_leverage": 1.0},
    "dynamic programming":                          {"relevance": 0.85, "domain": "cs_fundamentals", "xp_leverage": 1.4},
    "binary search and variants":                   {"relevance": 0.82, "domain": "cs_fundamentals", "xp_leverage": 1.1},
    "tree structures and traversal":                {"relevance": 0.83, "domain": "cs_fundamentals", "xp_leverage": 1.2},

    # Systems
    "docker container python sdk":                  {"relevance": 0.86, "domain": "devops", "xp_leverage": 1.2},
    "websocket protocol implementation":            {"relevance": 0.82, "domain": "networking", "xp_leverage": 1.1},
    "transformer attention mechanism":              {"relevance": 0.89, "domain": "ml", "xp_leverage": 1.5},
    "design patterns factory singleton observer":   {"relevance": 0.84, "domain": "engineering", "xp_leverage": 1.3},

    # JavaScript / multi-lang
    "javascript async await and promises":          {"relevance": 0.87, "domain": "javascript", "xp_leverage": 1.2},
    "typescript type system":                       {"relevance": 0.83, "domain": "javascript", "xp_leverage": 1.1},
    "node.js event loop and streams":               {"relevance": 0.80, "domain": "javascript", "xp_leverage": 1.1},
    "rust ownership and borrowing":                 {"relevance": 0.82, "domain": "rust", "xp_leverage": 1.4},
    "go goroutines and channels":                   {"relevance": 0.78, "domain": "go", "xp_leverage": 1.2},
}

# Domain priority -- how much SHARD should focus on each area
_DOMAIN_PRIORITY = {
    "cs_fundamentals": 1.0,
    "python":          0.95,
    "security":        0.90,
    "engineering":     0.88,
    "data_science":    0.85,
    "networking":      0.82,
    "systems":         0.80,
    "ml":              0.78,
    "devops":          0.75,
    "javascript":      0.70,
    "rust":            0.65,
    "go":              0.60,
}


class WorldModel:
    """SHARD's model of the external software world.

    Two layers:
    - static seed (above) -- curated by hand, never changes
    - dynamic known_skills -- updated as SHARD certifies topics
    """

    def __init__(self, data: dict):
        self._data = data
        # Merge seed into skills if missing
        if "skills" not in self._data:
            self._data["skills"] = {}
        for skill, meta in _SEED.items():
            if skill not in self._data["skills"]:
                self._data["skills"][skill] = {
                    "relevance":   meta["relevance"],
                    "domain":      meta["domain"],
                    "xp_leverage": meta["xp_leverage"],
                    "known":       False,
                    "known_score": None,
                }

    # ── Core API ───────────────────────────────────────────────────────────────

    def relevance(self, skill: str) -> float:
        """0.0–1.0 relevance of a skill in the current software landscape."""
        # Exact match first
        entry = self._data["skills"].get(skill.lower())
        if entry:
            return entry["relevance"]
        # Fuzzy match -- find the highest-relevance known skill that overlaps
        best = 0.0
        skill_tokens = set(re.split(r"[\s\-_]+", skill.lower()))
        for known_skill, meta in self._data["skills"].items():
            known_tokens = set(re.split(r"[\s\-_]+", known_skill))
            overlap = len(skill_tokens & known_tokens)
            if overlap >= 2:
                candidate = meta["relevance"] * (overlap / max(len(skill_tokens), len(known_tokens)))
                best = max(best, candidate)
        return round(best, 3)

    def domain_of(self, skill: str) -> str:
        entry = self._data["skills"].get(skill.lower())
        if entry:
            return entry.get("domain", "unknown")
        return "unknown"

    def mark_known(self, skill: str, score: float):
        """Record that SHARD has certified a skill with a given score."""
        key = skill.lower()
        if key not in self._data["skills"]:
            # Add it dynamically with a neutral relevance
            self._data["skills"][key] = {
                "relevance":   0.5,
                "domain":      "unknown",
                "xp_leverage": 1.0,
                "known":       False,
                "known_score": None,
            }
        self._data["skills"][key]["known"] = True
        self._data["skills"][key]["known_score"] = score
        self._data["updated_at"] = datetime.now().isoformat()

    def priority_gaps(self, known_skills: set[str], top_n: int = 10) -> list[dict]:
        """High-relevance skills that SHARD doesn't know yet.

        Returns list of {skill, relevance, domain, xp_leverage} sorted by priority.
        """
        known_lower = {s.lower() for s in known_skills}
        gaps = []
        for skill, meta in self._data["skills"].items():
            if meta.get("known"):
                continue
            if skill in known_lower:
                continue
            # Check fuzzy overlap with known
            skill_tokens = set(re.split(r"[\s\-_]+", skill))
            already_known = any(
                len(skill_tokens & set(re.split(r"[\s\-_]+", k))) >= 2
                for k in known_lower
            )
            if already_known:
                continue
            domain_boost = _DOMAIN_PRIORITY.get(meta.get("domain", ""), 0.5)
            priority_score = meta["relevance"] * domain_boost * meta.get("xp_leverage", 1.0)
            gaps.append({
                "skill":       skill,
                "relevance":   meta["relevance"],
                "domain":      meta.get("domain", "unknown"),
                "xp_leverage": meta.get("xp_leverage", 1.0),
                "priority":    round(priority_score, 4),
            })
        gaps.sort(key=lambda x: -x["priority"])
        return gaps[:top_n]

    def score_topic(self, topic: str) -> float:
        """Priority score for a candidate topic. Used by NightRunner topic steering."""
        base = self.relevance(topic)
        domain = self.domain_of(topic)
        domain_boost = _DOMAIN_PRIORITY.get(domain, 0.5)
        return round(base * domain_boost, 4)

    def coverage_summary(self) -> dict:
        """How much of the world model SHARD has covered."""
        skills = self._data["skills"]
        total = len(skills)
        known = sum(1 for s in skills.values() if s.get("known"))
        by_domain: dict[str, dict] = {}
        for meta in skills.values():
            d = meta.get("domain", "unknown")
            by_domain.setdefault(d, {"total": 0, "known": 0})
            by_domain[d]["total"] += 1
            if meta.get("known"):
                by_domain[d]["known"] += 1
        return {
            "total_skills": total,
            "known_skills": known,
            "coverage_pct": round(known / total * 100, 1) if total else 0.0,
            "by_domain": {
                d: f"{v['known']}/{v['total']}"
                for d, v in sorted(by_domain.items())
            },
        }

    # ── Shared environment interface ───────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to environment events broadcast by CognitionCore."""
        if event_type == "skill_certified":
            topic = data.get("topic", "")
            score = data.get("score", 7.5)
            if topic:
                self.mark_known(topic, score)
                self.save()

        elif event_type == "momentum_changed":
            new_momentum = data.get("new", "")
            if new_momentum == "stagnating":
                # Re-calibrate with lower threshold -- stagnation needs more signal, not less
                self.self_calibrate(min_experiments=5)
                self.save()

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self):
        _WORLD_MODEL_PATH.parent.mkdir(exist_ok=True)
        _WORLD_MODEL_PATH.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load_or_default(cls) -> "WorldModel":
        if _WORLD_MODEL_PATH.exists():
            try:
                data = json.loads(_WORLD_MODEL_PATH.read_text(encoding="utf-8"))
                return cls(data)
            except Exception:
                pass
        instance = cls({"created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat()})
        # Sync known skills from experiment history
        instance._sync_from_history()
        instance.save()
        return instance

    def _sync_from_history(self):
        """Mark skills as known if they appear as certified in experiment history."""
        ep_path = _MEMORY / "experiment_history.json"
        if not ep_path.exists():
            return
        try:
            raw = json.loads(ep_path.read_text(encoding="utf-8"))
            for e in raw:
                if isinstance(e, dict) and e.get("success") and e.get("topic"):
                    self.mark_known(e["topic"], e.get("score", 7.5))
        except Exception:
            pass

    def self_calibrate(self, min_experiments: int = 10) -> dict[str, float]:
        """Recalibrate relevance scores using SHARD's own certification data.

        Docker test showed: external SO counts are noisy and dominated by
        outliers (Java 1.9M dwarfs everything). SHARD's own cert rate
        per domain is the most honest signal available.

        Formula: new_relevance = 0.7 * seed_relevance + 0.3 * scaled_cert_rate
        Where scaled_cert_rate = cert_rate * 5 (so 20% cert -> 1.0, capped at 1.0)
        This blends prior knowledge with empirical SHARD performance.

        Only updates domains with >= min_experiments data points.
        Returns dict of {skill: old_relevance -> new_relevance} for logging.
        """
        ep_path = _MEMORY / "experiment_history.json"
        if not ep_path.exists():
            return {}

        # Junk filter
        _junk = re.compile(
            r"integration of .+ and .+|impossible differentials|applied to interrogative|"
            r"applied to transitive|\bmond\b|potrei|chiedo|facendo|applied to post.quantum|"
            r"applied to safe_code|tier \d+$|shard_debug",
            re.IGNORECASE,
        )
        _composite = re.compile(r"\bapplied to\b", re.IGNORECASE)

        try:
            raw = json.loads(ep_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        # Group experiments by seed skill (fuzzy token match)
        domain_stats: dict[str, dict] = {}
        for skill in self._data["skills"]:
            domain_stats[skill] = {"cert": 0, "total": 0}

        for e in raw:
            t = e.get("topic", "").lower()
            if not t or _junk.search(t) or _composite.search(t):
                continue
            t_tokens = set(re.split(r"[\s\-_]+", t))
            for skill in self._data["skills"]:
                sk_tokens = set(re.split(r"[\s\-_]+", skill.lower()))
                if len(t_tokens & sk_tokens) >= 2:
                    domain_stats[skill]["total"] += 1
                    if e.get("success"):
                        domain_stats[skill]["cert"] += 1

        adjustments = {}
        for skill, stats in domain_stats.items():
            n = stats["total"]
            if n < min_experiments:
                continue
            cert_rate = stats["cert"] / n
            scaled = min(1.0, cert_rate * 5)  # 20% cert -> 1.0
            old_rel = self._data["skills"][skill]["relevance"]
            new_rel = round(0.7 * old_rel + 0.3 * scaled, 4)
            if abs(new_rel - old_rel) > 0.01:  # only update meaningful changes
                self._data["skills"][skill]["relevance"] = new_rel
                adjustments[skill] = {"old": old_rel, "new": new_rel,
                                       "cert_rate": round(cert_rate, 3), "n": n}

        if adjustments:
            self._data["last_calibrated"] = datetime.now().isoformat()
            self.save()

        return adjustments
