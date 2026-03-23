import asyncio
import os
import sys

# Add backend to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from impact_analyzer import pre_check

async def test_syntax_error():
    result = await pre_check("dummy.py", "def foo(:")
    assert result["risk"] == "BLOCK"
    assert "SyntaxError" in result["reason"]
    print("test_syntax_error PASSED")

async def test_critical_module():
    result = await pre_check("server.py", "def foo(): pass")
    assert result["risk"] == "HIGH"
    assert "Critical module" in result["reason"]
    print("test_critical_module PASSED")

async def test_signature_delta():
    path = "backend/dummy_test_sig.py" if os.path.exists("backend") else "dummy_test_sig.py"
    with open(path, "w") as f:
        f.write("def foo(): pass\ndef bar(): pass\n")
    
    new_content = "def foo(): pass\n"
    result = await pre_check(path, new_content)
    assert result["risk"] == "MEDIUM"
    assert "Functions removed" in result["reason"]
    
    os.remove(path)
    print("test_signature_delta PASSED")

async def test_dependents():
    path = "backend/impact_analyzer.py" if os.path.exists("backend/impact_analyzer.py") else "impact_analyzer.py"
    result = await pre_check(path, "def pre_check(): pass")
    print(f"Dependents found for impact_analyzer.py: {result['dependents']}")
    # session_orchestrator.py should be there
    assert "session_orchestrator.py" in result["dependents"]
    print("test_dependents PASSED")

async def main():
    await test_syntax_error()
    await test_critical_module()
    await test_signature_delta()
    await test_dependents()
    print("All tests PASSED")

if __name__ == "__main__":
    asyncio.run(main())
