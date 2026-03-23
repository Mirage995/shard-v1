import sys
import os

# Ensure we are running from backend context
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from knowledge_bridge import query_knowledge_base

def test():
    print("--- Testing knowledge_bridge standalone ---")
    topic = "python optimization algorithms"
    print(f"Querying topic: {topic}")
    try:
        result = query_knowledge_base(topic, n_results=2)
        print(f"Result type: {type(result)}")
        print(f"Result length: {len(result)}")
        print(f"Result repr:\n{repr(result)}")
        print("--- Test Completed ---")
    except Exception as e:
        print(f"❌ CRASHED: {e}")

if __name__ == "__main__":
    test()
