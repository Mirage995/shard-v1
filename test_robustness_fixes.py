import os
import asyncio
from backend.study_agent import find_file
from backend.consciousness import ShardConsciousness
from backend.server import on_transcription

async def run_tests():
    print("--- 1. TESTING find_file ---")
    # Test file that we know exists
    target = "consciousness.py"
    path = find_file(target, "backend")
    if path:
        print(f"✅ Found {target} at {path}")
    else:
        print(f"❌ Could not find {target}")

    print("\n--- 2. TESTING on_transcription SIGNATURE ---")
    try:
        # Pass 1 arg
        on_transcription({"sender": "test", "text": "1 arg"})
        print("✅ 1 arg call passed without crashing")
        # Pass 2 args
        on_transcription({"sender": "test", "text": "2 args"}, "metadata_test")
        print("✅ 2 args call passed without crashing")
        # Pass kwargs
        on_transcription({"sender": "test", "text": "kwargs"}, extra_meta="test")
        print("✅ kwargs call passed without crashing")
    except Exception as e:
        print(f"❌ on_transcription failed: {e}")

    print("\n--- 3. TESTING consciousness duplicate loop protection ---")
    c = ShardConsciousness(None)
    
    # Avviamo il primo loop parallelamente
    t1 = asyncio.create_task(c.inner_monologue_loop())
    await asyncio.sleep(0.1) # Diamo il tempo di settare running=True
    
    # Avviamo il secondo loop
    t2 = asyncio.create_task(c.inner_monologue_loop())
    await asyncio.sleep(0.1)

    print(f"Loop 1 attivo: {t1.done() is False}")
    print(f"Loop 2 attivo: {not t2.done()}") # t2 should be done almost immediately (it returns)
    
    if t1.done() is False and t2.done() is True:
        print("✅ Duplicate loop correctly rejected!")
    else:
        print("❌ Duplicate loop protection failed")

    # Spegniamo la coscienza per non bloccare lo script
    c.active = False
    await t1

if __name__ == "__main__":
    asyncio.run(run_tests())
