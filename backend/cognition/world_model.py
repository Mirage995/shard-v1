class _SimpleGraph:
    def __init__(self):
        self._nodes = []
        self._edges = []

    def add_node(self, node, **attrs):
        if attrs:
            merged = dict(attrs)
            merged["id"] = node
            self._nodes.append(merged)
        else:
            self._nodes.append(node)

    def number_of_nodes(self):
        return len(self._nodes)

    def number_of_edges(self):
        return len(self._edges)

    def degree(self):
        counts = {}
        for node in self._nodes:
            if isinstance(node, dict):
                key = node.get("name") or node.get("topic") or str(node)
            else:
                key = str(node)
            counts[key] = counts.get(key, 0)
        return list(counts.items())


class WorldModel:
    def __init__(self):
        self.graph = _SimpleGraph()
        self.failures = []

    def ingest_concepts(self, concepts):
        for concept in concepts or []:
            if isinstance(concept, dict):
                name = concept.get("name")
            else:
                name = str(concept)

            if not name:
                continue

            self.graph.add_node({"type": "concept", "name": name})

    def compute_hubs(self):
        ranked = sorted(self.graph.degree(), key=lambda item: item[1], reverse=True)
        return ranked

    def record_failure(self, topic, error):
        print("[WORLD MODEL] recording failure:", topic)

        node = {
            "type": "failure",
            "topic": topic,
            "error": error
        }

        self.graph.add_node(node)
        self.failures.append(node)

    def get_failure_history(self):
        return list(self.failures)

    def reset(self):
        self.graph = _SimpleGraph()
        self.failures = []


world_model = WorldModel()

