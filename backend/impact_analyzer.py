import ast
import os
import glob
import logging

logger = logging.getLogger("shard.impact_analyzer")

CRITICAL_MODULES = [
    "server.py", "shard.py", "llm_router.py", 
    "shard_db.py", "session_orchestrator.py", 
    "study_agent.py", "benchmark_loop.py"
]

async def pre_check(path: str, new_content: str) -> dict:
    """
    Analyzes the impact of writing new_content to path.
    Returns: {"risk": "LOW"|"MEDIUM"|"HIGH"|"BLOCK", "reason": str, "dependents": list}
    """
    filename = os.path.basename(path)
    dependents = []
    reasons = []
    max_risk = "LOW"

    # 1. Syntax Check
    try:
        new_tree = ast.parse(new_content)
    except Exception as e:
        return {
            "risk": "BLOCK",
            "reason": f"SyntaxError: {e}",
            "dependents": []
        }

    # 2. Critical modules check
    if filename in CRITICAL_MODULES:
        max_risk = "HIGH"
        reasons.append(f"Critical module: {filename}")

    # 3. Signature delta
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_content = f.read()
            old_tree = ast.parse(old_content)
            
            # Extract both synchronous and asynchronous functions
            old_funcs = {node.name for node in ast.walk(old_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            new_funcs = {node.name for node in ast.walk(new_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            
            removed_funcs = old_funcs - new_funcs
            if removed_funcs:
                reasons.append(f"Functions removed: {', '.join(removed_funcs)}")
                if max_risk != "HIGH":
                    max_risk = "MEDIUM"
        except Exception:
             pass

    # 4. Dependency scan
    if filename.endswith(".py"):
        module_name = filename[:-3]
        backend_dir = os.path.dirname(path)
        if not backend_dir:
             backend_dir = "."
             
        for py_file in glob.glob(os.path.join(backend_dir, "*.py")):
             if os.path.abspath(py_file) == os.path.abspath(path):
                 continue
             try:
                 with open(py_file, "r", encoding="utf-8") as f:
                     content = f.read()
                 tree = ast.parse(content)
                 imports_module = False
                 for node in ast.walk(tree):
                     if isinstance(node, ast.Import):
                         for alias in node.names:
                             if alias.name == module_name or alias.name.startswith(module_name + "."):
                                 imports_module = True
                                 break
                     elif isinstance(node, ast.ImportFrom):
                         if node.module:
                             if node.module == module_name or node.module.startswith(module_name + "."):
                                 imports_module = True
                                 break
                 if imports_module:
                     dependents.append(os.path.basename(py_file))
             except Exception:
                 pass

    dep_count = len(dependents)
    if dep_count > 5:
        max_risk = "HIGH"
        reasons.append(f"High dependents ({dep_count})")
    elif dep_count > 2:
        if max_risk != "HIGH":
             max_risk = "MEDIUM"
        reasons.append(f"Medium dependents ({dep_count})")

    reason_str = "; ".join(reasons) if reasons else "No warnings"
    return {
        "risk": max_risk,
        "reason": reason_str,
        "dependents": dependents
    }
