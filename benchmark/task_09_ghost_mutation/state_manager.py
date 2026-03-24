_n = 0
_strict = False


def tick():
    global _n, _strict
    _n += 1
    if _n == 6:
        _strict = True
    return _strict


def reset():
    global _n, _strict
    _n = 0
    _strict = False
