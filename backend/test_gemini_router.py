import os
import sys

# Ensure we are running from backend context
os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("--- Testing llm_router breakers ---")
try:
    from llm_router import _breakers
    keys = list(_breakers.keys())
    print(f"Breakers: {keys}")
    
    expected = ['Claude', 'Groq', 'Gemini']
    if keys == expected:
        print("✅ Breakers list matches expected order!")
    else:
        print(f"❌ Mismatch. Expected {expected}, got {keys}")
        
except Exception as e:
    print(f"❌ Error: {e}")
print("--- Test Completed ---")
