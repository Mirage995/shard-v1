import os
import json

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shard_memory"))
failed_cache_path = os.path.join(base_dir, "failed_cache.json")
experiment_history_path = os.path.join(base_dir, "experiment_history.json")

fake_topics = ["quante imparato", "web scraping with beautifulsoup", "python meta-programming", "impossible quantum topic 999"]
fake_topics_lower = [t.lower() for t in fake_topics]

# Clean failed cache
if os.path.exists(failed_cache_path):
    with open(failed_cache_path, "r") as f:
        try:
            failed_cache = json.load(f)
        except json.JSONDecodeError:
            failed_cache = {}
    print("Failed cache before:", len(failed_cache))
    keys_to_delete = [k for k in failed_cache.keys() if k.lower() in fake_topics_lower]
    for k in keys_to_delete:
        del failed_cache[k]
    print("Failed cache after:", len(failed_cache))
    with open(failed_cache_path, "w") as f:
        json.dump(failed_cache, f, indent=4)

# Clean experiment history
if os.path.exists(experiment_history_path):
    with open(experiment_history_path, "r") as f:
        try:
            history = json.load(f)
        except json.JSONDecodeError:
            history = []
    print("History before:", len(history))
    history = [e for e in history if e.get("topic", "").lower() not in fake_topics_lower]
    print("History after:", len(history))
    with open(experiment_history_path, "w") as f:
        json.dump(history, f, indent=2)
