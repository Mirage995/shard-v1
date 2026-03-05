import json
import os

class SemanticExperimentCache:
    """
    Stores failed experiments to avoid repeating them 
    UNLESS the agent has acquired new capabilities.
    """

    def __init__(self, filepath="shard_memory/failed_cache.json"):
        # Salviamo nella cartella della memoria di SHARD
        self.filepath = filepath
        self.failed_cache = self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_cache(self):
        # Assicurati che la directory esista
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w") as f:
            json.dump(self.failed_cache, f, indent=4)

    def register_failure(self, topic: str, current_skill_count: int):
        """
        Store a failed experiment mapped to the number of skills SHARD had at the time.
        """
        topic_key = topic.lower().strip()
        self.failed_cache[topic_key] = current_skill_count
        self._save_cache()
        print(f"[CACHE] Registered failed experiment: '{topic}' (Skills at failure: {current_skill_count})")

    def should_skip(self, topic: str, current_skill_count: int) -> bool:
        """
        Skip ONLY IF the topic failed previously AND no new skills were learned.
        """
        topic_key = topic.lower().strip()
        
        if topic_key in self.failed_cache:
            skills_at_failure = self.failed_cache[topic_key]
            if current_skill_count <= skills_at_failure:
                print(f"[CACHE] Skipping '{topic}': Already failed and no new skills acquired.")
                return True
            else:
                print(f"[CACHE] Allowing retry for '{topic}': {current_skill_count - skills_at_failure} new skills acquired!")
                return False
                
        return False
