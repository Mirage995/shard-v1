from utils import transform


def handle_request(opts=None):
    f = (opts or {}).get("factor", 1)
    return {"ok": True, "v": transform(factor=f)}
