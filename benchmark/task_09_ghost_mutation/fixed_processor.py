from state_manager import tick


def process(coords):
    s = tick()
    if s:
        if isinstance(coords, (list, tuple)):
            lat, lon = coords
        elif isinstance(coords, dict) and "lat" in coords and "lon" in coords:
            lat = coords["lat"]
            lon = coords["lon"]
        else:
            raise ValueError("Invalid coordinates format")
        return round(lat + lon, 6)
    else:
        if isinstance(coords, dict) and "lat" in coords and "lon" in coords:
            return round(coords["lat"] + coords["lon"], 6)
        else:
            raise ValueError("Invalid coordinates format")