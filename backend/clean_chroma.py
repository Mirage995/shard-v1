# Script di manutenzione standalone -- NON importato dal runtime SHARD.
# Usa PersistentClient diretto intenzionalmente: viene eseguito manualmente
# a server spento, quindi non causa lock contention con db_manager.
import os
import chromadb

CHROMA_EXP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shard_memory", "experiment_db"))
CHROMA_STRAT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shard_memory", "strategy_db"))

fake_topics = ["Quante imparato", "web scraping with BeautifulSoup", "Python Meta-programming", "impossible quantum topic 999"]

try:
    client_exp = chromadb.PersistentClient(path=CHROMA_EXP)
    col_exp = client_exp.get_collection("experiments")
    print("Exp DB before:", col_exp.count())
    for t in fake_topics:
        col_exp.delete(where={"topic": t})
    print("Exp DB after:", col_exp.count())
except Exception as e:
    print("Exp DB error:", e)

try:
    client_strat = chromadb.PersistentClient(path=CHROMA_STRAT)
    col_strat = client_strat.get_collection("strategy_memory")
    print("Strat DB before:", col_strat.count())
    for t in fake_topics:
        col_strat.delete(where={"topic": t})
    print("Strat DB after:", col_strat.count())
except Exception as e:
    print("Strat DB error:", e)
