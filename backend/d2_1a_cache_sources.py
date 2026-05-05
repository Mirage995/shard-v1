"""d2_1a_cache_sources.py -- Pre-fetch MAP + AGGREGATE for D2.1A topics.

One-time fetcher that runs the live MAP (DDGS) + AGGREGATE (Playwright)
phases for each D2.1A topic and freezes the result to disk. The cache
files are then read back by phase_map / phase_aggregate hooks (gated by
the D2_CACHED_SOURCES_PATH env var) so D2.1A subprocess runs perform
ZERO network/scraping calls.

Cache schema:
    {
        "schema_version": 1,
        "topic":       str,
        "created_at":  iso timestamp,
        "sources":     list[dict]   # phase_map return shape
        "all_text":    str          # phase_aggregate return shape
        "hash":        "sha256:..."  # deterministic, excludes created_at
    }

Hash payload (deterministic):
    sha256(json.dumps({topic, sources, all_text}, sort_keys=True))

The env var D2_CACHED_SOURCES_PATH is forcibly cleared at startup so
this fetcher cannot accidentally read a stale cache when it is meant
to do live fetches.

Usage:
    python backend/d2_1a_cache_sources.py
    python backend/d2_1a_cache_sources.py --force        # rebuild all
    python backend/d2_1a_cache_sources.py --topic "..."  # single topic
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# CRITICAL: prevent reading a stale cache during live fetch
os.environ.pop("D2_CACHED_SOURCES_PATH", None)

_ROOT = Path(__file__).resolve().parent.parent
# Mirror night_runner.py path setup: both ROOT and backend/ on sys.path
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_ROOT / "backend"))

CACHE_DIR = _ROOT / "shard_workspace" / "d2_cached_sources"

D2_TOPICS = [
    "sql injection prevention python",
    "asyncio advanced patterns",
    "python OOP design patterns",
]


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _payload_hash(topic: str, sources: list, all_text: str) -> str:
    payload = {"topic": topic, "sources": sources, "all_text": all_text}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


async def _fetch_topic(topic: str) -> dict:
    """Run live MAP + AGGREGATE for a single topic. Returns cache dict."""
    # Lazy import so env var is guaranteed cleared before module sees it
    from study_agent import StudyAgent

    print(f"[D2.1A CACHE] Topic: {topic!r}")
    agent = StudyAgent(goal_engine=None)
    print(f"[D2.1A CACHE]   phase_map -> live DDGS search...")
    sources = await agent.phase_map(topic, tier=1)
    print(f"[D2.1A CACHE]   {len(sources)} sources found")
    print(f"[D2.1A CACHE]   phase_aggregate -> Playwright scrape...")
    all_text = await agent.phase_aggregate(sources)
    print(f"[D2.1A CACHE]   {len(all_text)} chars aggregated")

    cache = {
        "schema_version": 1,
        "topic":          topic,
        "created_at":     datetime.now().isoformat(),
        "sources":        sources,
        "all_text":       all_text,
    }
    cache["hash"] = _payload_hash(topic, sources, all_text)
    return cache


def _save(cache: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[D2.1A CACHE]   Saved -> {path}  hash={cache['hash'][:23]}...")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="re-fetch even if cache exists")
    p.add_argument("--topic", help="fetch only this topic")
    args = p.parse_args()

    topics = [args.topic] if args.topic else D2_TOPICS

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("D2.1A SOURCE CACHE BUILDER")
    print("=" * 70)
    print(f"Cache dir: {CACHE_DIR}")
    print(f"Topics:    {topics}")
    print(f"Force:     {args.force}")
    print(f"Env var D2_CACHED_SOURCES_PATH: {os.environ.get('D2_CACHED_SOURCES_PATH', '<unset>')}")
    print("=" * 70)

    for topic in topics:
        cache_file = CACHE_DIR / f"{_slug(topic)}.json"
        if cache_file.exists() and not args.force:
            existing = json.loads(cache_file.read_text(encoding="utf-8"))
            print(f"[D2.1A CACHE] SKIP {topic!r} (cache exists, hash={existing.get('hash', '?')[:23]}...)")
            continue
        cache = await _fetch_topic(topic)
        _save(cache, cache_file)

    print()
    print("Cache files:")
    for f in sorted(CACHE_DIR.glob("*.json")):
        size_kb = f.stat().st_size / 1024
        data = json.loads(f.read_text(encoding="utf-8"))
        print(f"  {f.name:<60} {size_kb:>8.1f} KB  hash={data['hash'][:23]}...")


if __name__ == "__main__":
    asyncio.run(main())
