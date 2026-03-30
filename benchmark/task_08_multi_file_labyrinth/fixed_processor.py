from database import get_data as _fetch
import copy

_TRANSFORMED = False


def process():
    global _TRANSFORMED
    d = _fetch()
    if isinstance(d, int):
        return d * 2

    d_copy = copy.deepcopy(d)
    if not _TRANSFORMED:
        d_copy["value"] = d_copy["value"] * 2
        _TRANSFORMED = True
    return d_copy["value"]