from backend.strategy_memory import StrategyMemory


class SimulationEngine:

    def __init__(self, world_model):
        self.world_model = world_model
        self.strategy_memory = StrategyMemory()

    def get_repair_history(self):

        if hasattr(self.strategy_memory, "get_all"):
            strategies = self.strategy_memory.get_all()
        else:
            strategies = self.strategy_memory.get_all_strategies()

        repairs = []

        for s in strategies:
            if s.get("type") == "swe_repair" or s.get("topic") == "swe_repair":
                repairs.append(s)

        return repairs

    def historical_success_score(self, patch):

        history = self.get_repair_history()

        if not history:
            return 0.5

        success = 0
        total = 0

        for r in history:

            total += 1

            if r.get("outcome") == "success":
                success += 1

        return success / total

    def failure_similarity_score(self, topic):

        failures = getattr(self.world_model, "failures", [])

        if not failures:
            return 0.5

        score = 0

        for f in failures:
            if topic.lower() in str(f).lower():
                score += 1

        return min(1.0, score / len(failures))

    def predict_patch_success(self, topic, patch):
        heuristic = 0.5

        patch_l = patch.lower()
        topic_l = topic.lower()

        # Reward patches that reference the actual topic domain
        topic_words = set(w for w in topic_l.split() if len(w) > 3)
        overlap = sum(1 for w in topic_words if w in patch_l)
        heuristic += min(0.3, overlap * 0.1)

        # Penalize patches that mention unrelated domains (rate limiter artifacts)
        unrelated_terms = ["token refill", "rate limit", "time delta", "rate_limiter"]
        if any(t in patch_l for t in unrelated_terms) and not any(t in topic_l for t in unrelated_terms):
            heuristic -= 0.2

        heuristic = max(0.0, min(1.0, heuristic))

        history_score = self.historical_success_score(patch)

        failure_score = self.failure_similarity_score(topic)

        score = (
            0.4 * heuristic +
            0.4 * history_score +
            0.2 * failure_score
        )

        print("[SIMULATION] heuristic:", heuristic)
        print("[SIMULATION] history_score:", history_score)
        print("[SIMULATION] failure_score:", failure_score)
        print("[SIMULATION] final_score:", score)

        return max(0.0, min(1.0, score))
