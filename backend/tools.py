import json
import re


def parse_llm_json(text: str) -> dict:
    """Robust JSON parser for raw LLM output.

    Tries four strategies in order:
    1. Direct json.loads
    2. Extract from ```json ... ``` fenced block
    3. Extract first {...} block via regex
    4. Fallback dict with raw text snippet
    """
    # 1. Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Fenced ```json block
    match = re.search(r"```json\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. Regex search for first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    # 4. Fallback
    return {"concepts": [], "raw": text[:500]}


generate_cad_prototype_tool = {
    "name": "generate_cad_prototype",
    "description": "Generates a 3D wireframe prototype based on a user's description. Use this when the user asks to 'visualize', 'prototype', 'create a wireframe', or 'design' something in 3D.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "The user's description of the object to prototype."
            }
        },
        "required": ["prompt"]
    }
}

# NOTE: write_file, read_directory, read_file tools have been migrated to SHARD.py
# as list_directory, read_file, write_file with workspace sandboxing via filesystem_tools.py

tools_list = [{"function_declarations": [
    generate_cad_prototype_tool,
]}]


