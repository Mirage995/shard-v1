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


