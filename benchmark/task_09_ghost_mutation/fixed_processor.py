from state_manager import tick


def process(coords):
    s = tick()
    if s:
        if isinstance(coords, tuple) and len(coords) == 2:
            lat, lon = coords
            return round(lat + lon, 6)
        elif isinstance(coords, dict) and "lat" in coords and "lon" in coords:
            return round(coords["lat"] + coords["lon"], 6)
        else:
            raise ValueError("Invalid coordinates format")
    else:
        if isinstance(coords, dict) and "lat" in coords and "lon" in coords:
            return round(coords["lat"] + coords["lon"], 6)
        elif isinstance(coords, tuple) and len(coords) == 2:
            lat, lon = coords
            return round(lat + lon, 6)
        else:
            raise ValueError("Invalid coordinates format")