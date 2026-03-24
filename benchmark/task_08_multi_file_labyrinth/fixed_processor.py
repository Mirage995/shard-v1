from database import get_data as _fetch


def process():
    d = _fetch()
    if isinstance(d, dict):
        return d["value"] * 2
    return d * 2