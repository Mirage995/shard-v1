"""export_stats.py — Generate shard_workspace/stats.json for the Figma dashboard.

Run manually or via cron:
    python backend/export_stats.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from epistemic_tracker import EpistemicTracker

tracker = EpistemicTracker()
stats = tracker.get_latest_stats()

out = Path(__file__).resolve().parent.parent / "shard_workspace" / "stats.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(stats, indent=2), encoding="utf-8")

print(json.dumps(stats, indent=2))
print(f"\n[EXPORT] Written to {out}")
