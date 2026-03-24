import json
from pathlib import Path

_P = Path(__file__).parent / "config.json"


def get_data():
    try:
        c = json.loads(_P.read_text())
    except Exception:
        c = {}
    v = int(c.get("value", 42))
    if c.get("raw_mode", False):
        return v
    return {"value": v, "metadata": {"ver": 1}}
