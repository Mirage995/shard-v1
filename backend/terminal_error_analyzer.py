def analyze_error(output: str):
    """
    Detect common terminal errors.
    """

    text = output.lower()

    if "no such file or directory" in text or "impossibile trovare il percorso" in text:
        return {"type": "missing_file"}

    if "&&" in text or "token" in text:
        return {"type": "syntax_error"}

    if "module not found" in text:
        return {"type": "python_module"}

    if "permission denied" in text:
        return {"type": "permission_error"}

    return None
