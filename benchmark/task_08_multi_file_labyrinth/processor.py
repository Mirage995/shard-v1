from database import get_data as _fetch


def process():
    d = _fetch()
    return d["value"] * 2
