"""self_model.py — SHARD's persistent self-representation.

Not a mirror. Not a recital. A real statistical model of what SHARD
knows, what it keeps failing, how fast it's growing, and where its
blind spots are — rebuilt from experiment history after every session.

Injected as context into every study prompt so the LLM knows who it's
helping and what gaps actually exist.

Files read:
  shard_memory/experiment_history.json  — scored experiments
  shard_memory/failed_cache.json        — chronic failure topics
  shard_memory/capability_graph.json    — certified skills + XP

File written:
  shard_memory/self_model.json          — persisted snapshot

Usage:
    from self_model import SelfModel
    model = SelfModel.load_or_build()
    print(model.as_prompt_fragment())
    model.update_from_session(certified=["asyncio"], failed=["C++ templates"])
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_ROOT   = Path(__file__).resolve().parents[1]
_MEMORY = _ROOT / "shard_memory"
_SELF_MODEL_PATH = _MEMORY / "self_model.json"

# Skills that match these tokens are considered "junk" hallucinations
_JUNK_PATTERNS = [
    r"integration of .+ and .+",
    r"impossible differentials",
    r"hubble.scale",
    r"quantized inertia",
    r"casimir",
    r"applied to interrogative",
    r"applied to transitive",
    r"applied to eafp",
    r"\bmond\b",
    r"potrei|vorrei|chiedo|facendo|analizzare|forse|dovrei",
    r"applied to post.quantum",
    r"applied to numerical_computation",
    r"applied to deep_learning$",
    r"applied to safe_code",
    r"tier \d+$",
    r"shard_debug",
]
_JUNK_RE = re.compile("|".join(_JUNK_PATTERNS), re.IGNORECASE)

# Language keywords for confidence mapping
_LANG_KEYWORDS = {
    "python":     ["python", "asyncio", "numpy", "pandas", "django", "flask", "pydantic", "pytest"],
    "javascript": ["javascript", "typescript", "node", "jest", "react", "async/await", "esm"],
    "cpp":        ["c++", "cpp", "stl", "template", "cmake", "googletest", "memory management"],
    "rust":       ["rust", "ownership", "borrow", "cargo", "wasm", "tokio"],
    "go":         ["golang", "goroutine", "channel", "context", "go "],
    "java":       ["java", "jvm", "spring", "gradle", "junit"],
}


def _is_junk(topic: str) -> bool:
    return bool(_JUNK_RE.search(topic.lower()))


def _lang_of(topic: str) -> str:
    t = topic.lower()
    for lang, kws in _LANG_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return lang
    return "python"  # default — most experiments are Python


class SelfModel:
    """Computed self-representation of SHARD's capabilities and gaps.

    All fields are derived from real data. Nothing is hardcoded.
    """

    def __init__(self, data: dict):
        self._data = data

    # ── Public accessors ───────────────────────────────────────────────────────

    @property
    def total_experiments(self) -> int:
        return self._data.get("total_experiments", 0)

    @property
    def certification_rate(self) -> float:
        return self._data.get("certification_rate", 0.0)

    @property
    def avg_score(self) -> float:
        return self._data.get("avg_score", 0.0)

    @property
    def momentum(self) -> str:
        return self._data.get("momentum", "unknown")

    @property
    def strengths(self) -> list:
        return self._data.get("strengths", [])

    @property
    def blind_spots(self) -> list:
        return self._data.get("blind_spots", [])

    @property
    def language_confidence(self) -> dict:
        return self._data.get("language_confidence", {})

    # ── Prompt injection ───────────────────────────────────────────────────────

    def as_prompt_fragment(self) -> str:
        """Tight context string for injection into LLM prompts."""
        lines = ["=== SHARD SELF-MODEL ==="]

        cert_pct = round(self.certification_rate * 100, 1)
        lines.append(
            f"Track record: {self.total_experiments} experiments | "
            f"{cert_pct}% certified | avg score {self.avg_score:.1f}/10 | "
            f"momentum: {self.momentum}"
        )

        if self.strengths:
            lines.append(f"Strengths: {', '.join(self.strengths[:5])}")

        if self.blind_spots:
            lines.append(f"Blind spots (repeated failures): {', '.join(self.blind_spots[:4])}")

        conf = self.language_confidence
        if conf:
            conf_str = "  ".join(f"{lang}={round(v*100)}%" for lang, v in
                                 sorted(conf.items(), key=lambda x: -x[1]))
            lines.append(f"Language confidence: {conf_str}")

        lines.append("=== END SELF-MODEL ===")
        return "\n".join(lines)

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self):
        _SELF_MODEL_PATH.parent.mkdir(exist_ok=True)
        _SELF_MODEL_PATH.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def to_dict(self) -> dict:
        return dict(self._data)

    # ── Incremental update ─────────────────────────────────────────────────────

    def update_from_session(self, certified: list[str], failed: list[str],
                             scores: list[float]):
        """Update model after a NightRunner session — no full rebuild needed."""
        now = datetime.now().isoformat()
        self._data["updated_at"] = now
        self._data["last_session"] = {
            "date": now,
            "certified": certified,
            "failed": failed,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
        }
        # Append certified to strengths (no duplicates, cap at 20)
        existing = set(self._data.get("strengths", []))
        for t in certified:
            if not _is_junk(t):
                existing.add(t)
        self._data["strengths"] = list(existing)[:20]
        self.save()

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def build(cls) -> "SelfModel":
        """Full rebuild from raw experiment data. Takes ~50ms."""
        data: dict = {
            "built_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        # ── 1. Experiment history ──────────────────────────────────────────────
        experiments = []
        ep_path = _MEMORY / "experiment_history.json"
        if ep_path.exists():
            try:
                raw = json.loads(ep_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    experiments = [e for e in raw if isinstance(e, dict)]
            except Exception:
                pass

        real_exps = [e for e in experiments if not _is_junk(e.get("topic", ""))]
        total = len(real_exps)
        certified_exps = [e for e in real_exps if e.get("success")]
        scores = [e["score"] for e in real_exps if isinstance(e.get("score"), (int, float))]

        data["total_experiments"] = total
        data["total_certified"] = len(certified_exps)
        data["certification_rate"] = round(len(certified_exps) / total, 3) if total else 0.0
        data["avg_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0

        # ── 2. Strengths — certified topics sorted by recency ──────────────────
        seen: set[str] = set()
        strengths = []
        for e in sorted(certified_exps, key=lambda x: x.get("timestamp", ""), reverse=True):
            t = e.get("topic", "")
            if t and t not in seen:
                seen.add(t)
                strengths.append(t)
        data["strengths"] = strengths[:20]

        # ── 3. Blind spots — attempted 2+ times, never certified, avg < 6.5 ───
        topic_attempts: dict[str, list[float]] = defaultdict(list)
        topic_certified: dict[str, bool] = defaultdict(bool)
        for e in real_exps:
            t = e.get("topic", "")
            if not t:
                continue
            if isinstance(e.get("score"), (int, float)):
                topic_attempts[t].append(e["score"])
            if e.get("success"):
                topic_certified[t] = True

        blind_spots = []
        for t, attempt_scores in topic_attempts.items():
            if topic_certified[t]:
                continue
            if len(attempt_scores) >= 2 and (sum(attempt_scores) / len(attempt_scores)) < 6.5:
                blind_spots.append((t, len(attempt_scores), sum(attempt_scores) / len(attempt_scores)))

        blind_spots.sort(key=lambda x: (-x[1], x[2]))  # most attempted + lowest score first
        data["blind_spots"] = [t for t, _, _ in blind_spots[:10]]

        # ── Auto-quarantine candidates ─────────────────────────────────────────
        # Docker test confirmed: 0% of blind spots are real skill gaps.
        # Composite topics (X applied to Y) and junk that have been failed
        # 2+ times should be quarantined, not retried at higher tier.
        _composite_re = re.compile(r"\bapplied to\b", re.IGNORECASE)
        quarantine_candidates = [
            t for t, n_attempts, avg_s in blind_spots
            if (_is_junk(t) or _composite_re.search(t)) and n_attempts >= 2
        ]
        data["quarantine_candidates"] = quarantine_candidates[:20]

        # ── 4. Language confidence — based on certification rate per language ──
        lang_certified: dict[str, int] = defaultdict(int)
        lang_total: dict[str, int] = defaultdict(int)
        for e in real_exps:
            lang = e.get("lang") or _lang_of(e.get("topic", ""))
            lang_total[lang] += 1
            if e.get("success"):
                lang_certified[lang] += 1

        lang_confidence = {}
        for lang, total_n in lang_total.items():
            if total_n >= 3:  # need enough data to be meaningful
                lang_confidence[lang] = round(lang_certified[lang] / total_n, 3)
        data["language_confidence"] = lang_confidence

        # ── 5. Growth momentum — compare last 10 vs previous 10 sessions ──────
        timestamped = sorted(
            [e for e in real_exps if e.get("timestamp")],
            key=lambda x: x["timestamp"]
        )
        if len(timestamped) >= 20:
            recent_cert = sum(1 for e in timestamped[-10:] if e.get("success"))
            older_cert  = sum(1 for e in timestamped[-20:-10] if e.get("success"))
            if recent_cert > older_cert + 1:
                data["momentum"] = "accelerating"
            elif recent_cert < older_cert - 1:
                data["momentum"] = "stagnating"
            else:
                data["momentum"] = "stable"
        elif total > 0:
            data["momentum"] = "early"
        else:
            data["momentum"] = "unknown"

        # ── 6. Capability graph snapshot ───────────────────────────────────────
        cap_path = _MEMORY / "capability_graph.json"
        cap_skills = []
        if cap_path.exists():
            try:
                cg = json.loads(cap_path.read_text(encoding="utf-8"))
                nodes = cg.get("nodes", {})
                cap_skills = [
                    k for k, v in sorted(nodes.items(),
                                         key=lambda x: x[1].get("xp", 0), reverse=True)
                    if isinstance(v, dict) and v.get("xp", 0) > 0
                ]
            except Exception:
                pass
        data["top_capability_graph_skills"] = cap_skills[:15]
        data["capability_graph_size"] = len(cap_skills)

        model = cls(data)
        model.save()
        return model

    @classmethod
    def load_or_build(cls) -> "SelfModel":
        """Load from disk if fresh (< 24h), otherwise rebuild."""
        if _SELF_MODEL_PATH.exists():
            try:
                raw = json.loads(_SELF_MODEL_PATH.read_text(encoding="utf-8"))
                built_at = raw.get("built_at", "")
                if built_at:
                    age = datetime.now() - datetime.fromisoformat(built_at)
                    if age < timedelta(hours=24):
                        return cls(raw)
            except Exception:
                pass
        return cls.build()

    @classmethod
    def load(cls) -> Optional["SelfModel"]:
        """Load without rebuilding — returns None if no saved model."""
        if not _SELF_MODEL_PATH.exists():
            return None
        try:
            return cls(json.loads(_SELF_MODEL_PATH.read_text(encoding="utf-8")))
        except Exception:
            return None
