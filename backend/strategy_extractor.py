class StrategyExtractor:
    """Stub strategy extractor used during transition away from legacy module.

    Provides the method extract_from_experiment expected by StudyAgent.
    """

    def extract_from_experiment(self, experiment):
        # Minimal no-op: return None to skip additional storage.
        return None

