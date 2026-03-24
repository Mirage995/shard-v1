from state_manager import tick


def process(coords):
    s = tick()
    if s:
        lat, lon = coords
        return round(lat + lon, 6)
    return round(coords["lat"] + coords["lon"], 6)
