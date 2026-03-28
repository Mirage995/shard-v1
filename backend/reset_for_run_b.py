"""reset_for_run_b.py — Reset chirurgico per Run B (cold start controllato).

Resetta:
  1. mood_state.json → neutro (score=0, frustration=0)
  2. goals.json → nessun goal attivo (GoalEngine lo rigenera da zero)
  3. desire_state.json → forza password hashing come top priority

NON tocca:
  - storico SQLite (experiments, skill_library, ecc.)
  - session_reflections.jsonl (memoria episodica globale)
  - strategy_memory ChromaDB (vogliamo vedere se usa la stessa strategia)
  - capability_graph, self_model, world_model

Uso: python reset_for_run_b.py
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEM = ROOT / "shard_memory"

TARGET_TOPIC = "password hashing bcrypt argon2"


def reset_mood():
    path = MEM / "mood_state.json"
    neutral = {
        "mood_score": 0.0,
        "label": "neutral",
        "updated_at": datetime.now().isoformat(),
        "components": {
            "frustration": 0.0,
            "cert_rate": 0.0,
            "momentum": 0.0,
        }
    }
    path.write_text(json.dumps(neutral, indent=2), encoding="utf-8")
    print(f"[RESET] mood_state → neutral (score=0.0)")


def reset_goals():
    path = MEM / "goals.json"
    # Rimuove tutti i goal attivi — GoalEngine li rigenera autonomamente
    path.write_text(json.dumps([], indent=2), encoding="utf-8")
    print(f"[RESET] goals.json → [] (GoalEngine rigenererà da zero)")


def force_topic_priority():
    path = MEM / "desire_state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        state = {}

    # Imposta password hashing come topic dominante
    # frustration_hits alto = alta priorità nel desire engine
    state[TARGET_TOPIC] = {
        "topic": TARGET_TOPIC,
        "base_priority": 0.99,
        "frustration_hits": 9,
        "curiosity_pull": 0.0,
        "engagement_scores": [],
        "last_updated": datetime.now().isoformat(),
    }

    # Abbassa tutti gli altri topic per evitare competizione
    for key in state:
        if key != TARGET_TOPIC:
            state[key]["base_priority"] = min(state[key].get("base_priority", 0.5), 0.3)

    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"[RESET] desire_state → '{TARGET_TOPIC}' forced top (priority=0.99, frustration_hits=9)")


def main():
    print("=" * 60)
    print("RESET FOR RUN B — cold start controllato")
    print("=" * 60)
    reset_mood()
    reset_goals()
    force_topic_priority()
    print("=" * 60)
    print("DONE. Lancia Run B con:")
    print("  python night_runner.py --cycles 6 --timeout 60")
    print("=" * 60)


if __name__ == "__main__":
    main()
