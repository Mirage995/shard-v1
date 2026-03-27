"""identity_core.py — SHARD's persistent identity derived from real data.

Every field is computed from SQLite. The LLM only writes the narrative string —
it cannot invent facts. This is not a persona prompt. It is a biography.

Updated at end of every NightRunner session.
Read at the start of every session and injected into study_agent.session_context.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("shard.identity")

_ROOT          = Path(__file__).parent.parent.resolve()
_IDENTITY_FILE = _ROOT / "shard_memory" / "identity.json"

# Domain keyword mapping (mirrors self_model_tracker)
_DOMAIN_KEYWORDS = {
    "algorithms":    ["algorithm", "sort", "search", "graph", "tree", "dynamic", "union find", "trie", "heap"],
    "concurrency":   ["async", "thread", "race", "lock", "concurrent", "coroutine", "asyncio", "selector"],
    "data":          ["sql", "json", "parse", "serial", "injection", "sanitize", "query", "redis"],
    "cryptography":  ["encrypt", "decrypt", "hash", "sha", "aes", "rsa", "jwt", "bcrypt", "cipher"],
    "networking":    ["socket", "tcp", "dns", "http", "rabbitmq", "protocol"],
    "ml":            ["neural", "cnn", "transformer", "attention", "gradient", "regression", "backprop"],
    "debugging":     ["debug", "fix", "bug", "error", "exception", "failure", "ghost", "mutation"],
    "systems":       ["docker", "container", "linux", "process", "memory", "profil", "optim"],
}


def _infer_domain(topic: str) -> str:
    t = topic.lower()
    for domain, kws in _DOMAIN_KEYWORDS.items():
        if any(k in t for k in kws):
            return domain
    return "general"


class IdentityCore:
    """Compute and persist SHARD's factual self-identity."""

    def __init__(self):
        self._data     = self._load()
        self._core_env = None   # set by NightRunner after CognitionCore registration

    # ── Public API ────────────────────────────────────────────────────────────

    def rebuild(self, think_fn=None, momentum: str = "stable") -> dict:
        """Recompute all identity fields from SQLite. Optionally regenerate narrative via LLM.

        Returns the full identity dict.
        """
        facts = self._compute_facts(momentum)
        self._data.update(facts)
        self._data["updated_at"] = datetime.now().isoformat()

        if think_fn is not None:
            self._data["narrative"] = self._generate_narrative(facts, think_fn)

        self._save()

        # Broadcast to CognitionCore so other modules adapt
        if self._core_env is not None:
            self._core_env.broadcast(
                "identity_updated",
                {
                    "self_esteem":    facts["self_esteem"],
                    "trajectory":     facts["trajectory"],
                    "sessions_lived": facts["sessions_lived"],
                    "cert_rate":      facts["cert_rate_overall"],
                },
                source="identity_core",
            )
            if facts["self_esteem"] < 0.30:
                self._core_env.broadcast(
                    "low_self_esteem",
                    {"self_esteem": facts["self_esteem"], "trajectory": facts["trajectory"]},
                    source="identity_core",
                )

        logger.info(
            "[IDENTITY] Rebuilt — sessions=%d cert_rate=%.0f%% self_esteem=%.2f trajectory=%s domains_strong=%s",
            facts["sessions_lived"], facts["cert_rate_overall"] * 100,
            facts["self_esteem"], facts["trajectory"],
            ", ".join(facts["strong_domains"]) or "none",
        )
        return self._data

    # ── CognitionCore interface ───────────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to events from other modules."""
        if event_type == "session_complete":
            # Rebuild already triggered directly by NightRunner — just log
            logger.debug("[IDENTITY] session_complete received (rebuild handled by NightRunner)")

    def get_context_block(self) -> str:
        """Return a compact text block to inject into study prompts.

        Contains only facts — no invented personality traits.
        """
        d = self._data
        if not d.get("sessions_lived"):
            return ""

        lines = ["=== SHARD IDENTITY (derived from real session data) ==="]
        lines.append(f"Sessions lived: {d.get('sessions_lived', 0)}")
        lines.append(f"Lifetime cert rate: {d.get('cert_rate_overall', 0)*100:.0f}% ({d.get('total_certified',0)} certified / {d.get('total_attempts',0)} total)")
        lines.append(f"Self-esteem: {d.get('self_esteem', 0):.2f}/1.0  |  Trajectory: {d.get('trajectory','unknown')}")

        if d.get("strong_domains"):
            lines.append(f"Strong domains: {', '.join(d['strong_domains'])}")
        if d.get("weak_domains"):
            lines.append(f"Weak domains: {', '.join(d['weak_domains'])}")
        if d.get("peak_skills"):
            lines.append(f"Peak skills (score ≥9): {', '.join(d['peak_skills'][:4])}")
        if d.get("chronic_blocks"):
            lines.append(f"Chronic blocks (3+ fails, never certified): {', '.join(d['chronic_blocks'][:3])}")
        if d.get("narrative"):
            lines.append(f"\nSelf-narrative: {d['narrative'][:400]}")

        return "\n".join(lines)

    def get_status(self) -> dict:
        return dict(self._data)

    # ── Fact computation (all from SQLite) ───────────────────────────────────

    def _compute_facts(self, momentum: str) -> dict:
        try:
            from shard_db import query as db_query
        except Exception as e:
            logger.warning("[IDENTITY] DB unavailable: %s", e)
            return self._data

        # ── Total attempts and cert rate (weighted by difficulty) ─────────────
        # Join experiments with activation_log to get sig_difficulty + source.
        # Certifications on easy hybrid topics (curiosity_engine, difficulty<0.3)
        # count 0.5x. Hard curated topics (difficulty>0.7) count 1.5x.
        # This prevents specification gaming from inflating self-esteem (backlog #17).
        rows = db_query("SELECT certified, score, topic FROM experiments WHERE score IS NOT NULL")
        total = len(rows)

        try:
            al_rows = db_query(
                "SELECT topic, source, sig_difficulty, certified FROM activation_log"
            )
            al_map = {r["topic"]: r for r in al_rows}
        except Exception:
            al_map = {}

        total_weight = 0.0
        weighted_certified = 0.0
        for r in rows:
            t    = r.get("topic", "")
            al   = al_map.get(t, {})
            diff = al.get("sig_difficulty") or 0.5
            src  = al.get("source") or ""
            if src == "curiosity_engine" and diff < 0.3:
                w = 0.5
            elif diff > 0.7 and src in ("curated_list", "improvement_engine"):
                w = 1.5
            else:
                w = 1.0
            total_weight += w
            if r.get("certified"):
                weighted_certified += w

        certified = sum(1 for r in rows if r.get("certified"))
        cert_rate = round(weighted_certified / total_weight, 4) if total_weight > 0 else 0.0

        # ── Domain breakdown ──────────────────────────────────────────────────
        domain_cert  = defaultdict(int)
        domain_total = defaultdict(int)
        for r in rows:
            d = _infer_domain(r.get("topic", ""))
            domain_total[d] += 1
            if r.get("certified"):
                domain_cert[d] += 1

        strong, weak = [], []
        for domain, n in domain_total.items():
            if n < 3:
                continue
            rate = domain_cert[domain] / n
            if rate >= 0.60:
                strong.append(domain)
            elif rate <= 0.20:
                weak.append(domain)

        # ── Peak skills (score >= 9.0, certified) ─────────────────────────────
        peak = db_query(
            "SELECT DISTINCT topic FROM experiments WHERE certified=1 AND score>=9.0 "
            "ORDER BY score DESC LIMIT 8"
        )
        peak_skills = [r["topic"] for r in peak]

        # ── Chronic blocks: 3+ fails, never certified ─────────────────────────
        fail_counts  = defaultdict(int)
        cert_topics  = set()
        for r in rows:
            t = r.get("topic", "")
            if r.get("certified"):
                cert_topics.add(t)
            else:
                fail_counts[t] += 1
        chronic = [t for t, n in fail_counts.items() if n >= 3 and t not in cert_topics]

        # ── Sessions lived ────────────────────────────────────────────────────
        sessions_row = db_query("SELECT COUNT(DISTINCT session_id) as n FROM activation_log")
        sessions = sessions_row[0]["n"] if sessions_row else self._data.get("sessions_lived", 0)

        # ── Self-esteem: weighted combination ─────────────────────────────────
        momentum_score = {"growing": 1.0, "stable": 0.5, "stagnating": 0.0}.get(momentum, 0.5)
        self_esteem = round(0.6 * cert_rate + 0.4 * momentum_score, 4)

        # ── Trajectory from last 3 sessions ───────────────────────────────────
        recent = db_query(
            "SELECT certified FROM activation_log ORDER BY timestamp DESC LIMIT 20"
        )
        if len(recent) >= 10:
            first_half  = sum(1 for r in recent[10:] if r["certified"]) / max(len(recent[10:]), 1)
            second_half = sum(1 for r in recent[:10] if r["certified"]) / 10
            if second_half > first_half + 0.1:
                trajectory = "growing"
            elif second_half < first_half - 0.1:
                trajectory = "declining"
            else:
                trajectory = momentum
        else:
            trajectory = momentum

        return {
            "sessions_lived":    sessions,
            "total_attempts":    total,
            "total_certified":   certified,
            "cert_rate_overall": cert_rate,
            "strong_domains":    sorted(strong),
            "weak_domains":      sorted(weak),
            "peak_skills":       peak_skills,
            "chronic_blocks":    chronic[:10],
            "self_esteem":       self_esteem,
            "trajectory":        trajectory,
        }

    # ── Narrative (only LLM-generated field) ─────────────────────────────────

    def _generate_narrative(self, facts: dict, think_fn) -> str:
        """Ask LLM to write a 2-sentence self-narrative based on facts only.

        The prompt explicitly forbids inventing facts not in the data.
        """
        import asyncio

        strong  = ", ".join(facts["strong_domains"]) or "none yet"
        weak    = ", ".join(facts["weak_domains"]) or "none yet"
        chronic = ", ".join(facts["chronic_blocks"][:2]) or "none"
        traj    = facts["trajectory"]
        esteem  = facts["self_esteem"]
        n_cert  = facts["total_certified"]

        prompt = (
            f"You are SHARD, an autonomous AI learner. Write a 2-sentence first-person "
            f"self-narrative based ONLY on these measured facts:\n"
            f"- Certified {n_cert} skills so far\n"
            f"- Strong in: {strong}\n"
            f"- Weak in: {weak}\n"
            f"- Chronically blocked on: {chronic}\n"
            f"- Trajectory: {traj}\n"
            f"- Self-esteem: {esteem:.2f}/1.0\n\n"
            f"Do NOT invent personality traits. Do NOT use words like 'passionate' or 'curious'. "
            f"Describe only what the data shows. Be precise and honest."
        )

        async def _call():
            try:
                return await think_fn(prompt, max_tokens=120, temperature=0.2)
            except Exception:
                return ""

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, _call()).result(timeout=15)
            return loop.run_until_complete(_call())
        except Exception as e:
            logger.debug("[IDENTITY] narrative generation failed: %s", e)
            return ""

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            if _IDENTITY_FILE.exists():
                return json.loads(_IDENTITY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"sessions_lived": 0, "narrative": ""}

    def _save(self) -> None:
        try:
            _IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=_IDENTITY_FILE.parent, suffix=".tmp", delete=False,
            ) as tf:
                json.dump(self._data, tf, indent=2, ensure_ascii=False)
                tmp = tf.name
            os.replace(tmp, _IDENTITY_FILE)
        except Exception as e:
            logger.warning("[IDENTITY] save failed: %s", e)
