import sys
import os

# Ensure we are running from backend context
os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("Testing server.py import...")
try:
    from server import app
    print("✅ server.py imported successfully!")
except Exception as e:
    print(f"❌ server.py import FAILED: {e}")
    import traceback
    traceback.print_exc()
