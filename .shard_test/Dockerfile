FROM python:3.11-slim
WORKDIR /test

RUN mkdir -p /test/shard_memory

COPY experiment_history.json /test/shard_memory/
COPY capability_graph.json   /test/shard_memory/
COPY self_model.py .
COPY world_model.py .
COPY goal_engine.py .
COPY cognition_core.py .
COPY test_cognition.py .
COPY test_cognition_final.py .

CMD ["python", "test_cognition_final.py"]
