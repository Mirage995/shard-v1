import asyncio
import time
from backend.terminal_memory import TerminalMemory
from backend.terminal_error_analyzer import analyze_error
import os

async def run_tests():
    print("--- 1. TESTING TerminalMemory ---")
    mem = TerminalMemory()
    cmd = "python script.py"
    
    # Should not block initially
    assert mem.should_block(cmd) == False, "New command should not be blocked"
    
    # Register failure
    mem.register_failure(cmd)
    
    # Should block now
    assert mem.should_block(cmd) == True, "Failed command should be blocked"
    
    # Should not block a different command
    assert mem.should_block("python other.py") == False, "Different command should not be blocked"
    print("✅ TerminalMemory logic passed")

    print("\n--- 2. TESTING terminal_error_analyzer ---")
    # Missing file
    out1 = "python: can't open file 'script.py': [Errno 2] No such file or directory"
    ans1 = analyze_error(out1)
    assert ans1 and ans1["type"] == "missing_file", "Failed to detect missing_file"

    # Syntax error
    out2 = "The token '&&' is not a recognized statement, block, or expression."
    ans2 = analyze_error(out2)
    assert ans2 and ans2["type"] == "syntax_error", "Failed to detect syntax_error"

    # Module not found
    out3 = "Error: module not found: numpy"
    ans3 = analyze_error(out3)
    assert ans3 and ans3["type"] == "python_module", "Failed to detect python_module"

    # Permission denied
    out4 = "Permission denied"
    ans4 = analyze_error(out4)
    assert ans4 and ans4["type"] == "permission_error", "Failed to detect permission_error"

    # No error
    out5 = "Hello World"
    ans5 = analyze_error(out5)
    assert ans5 is None, "False positive in error analysis"
    
    print("✅ terminal_error_analyzer logic passed")

if __name__ == "__main__":
    asyncio.run(run_tests())
