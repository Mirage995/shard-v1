class CriticFeedbackEngine:
    """
    Routes CriticAgent analysis to the ResearchAgenda as Priority 0 topics.
    Only injects remediation topics when confidence is above threshold.
    """

    CONFIDENCE_THRESHOLD = 0.5

    def __init__(self, research_agenda=None, capability_graph=None):
        self.research_agenda = research_agenda
        self.capability_graph = capability_graph

    def process_feedback(self, feedback: dict):
        """
        Take a CriticAgent result and inject the remediation topic
        into the research agenda if confidence is sufficient.
        """
        if not feedback or feedback.get("analysis") == "stub":
            return None

        confidence = feedback.get("confidence", 0.0)
        remediation_topic = feedback.get("remediation_topic")
        capability = feedback.get("capability", "unknown")

        if not remediation_topic:
            print(f"[CRITIC FEEDBACK] No remediation topic for '{capability}' — skipping injection")
            return None

        if confidence < self.CONFIDENCE_THRESHOLD:
            print(f"[CRITIC FEEDBACK] Low confidence ({confidence:.2f}) for '{capability}' — skipping injection")
            return None

        if self.research_agenda and hasattr(self.research_agenda, "add_priority_topic"):
            self.research_agenda.add_priority_topic(remediation_topic)
            print(
                f"[CRITIC FEEDBACK] Injected Priority 0 topic: '{remediation_topic}' "
                f"(from failure on '{capability}', confidence={confidence:.2f})"
            )
        else:
            print("[CRITIC FEEDBACK] No research agenda available — topic not injected")

        return {
            "injected_topic": remediation_topic,
            "source_capability": capability,
            "confidence": confidence,
        }
