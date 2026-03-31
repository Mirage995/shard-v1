from state_manager import tick


def process(coords):
    s = tick()
    if s:
        if isinstance(coords, dict):
            lat, lon = coords["lat"], coords["lon"]
        else:
            lat, lon = coords
        return round(lat + lon, 6)
    else:
        return round(coords["lat"] + coords["lon"], 6)