from state_manager import tick
import copy


def process(coords):
    s = tick()
    coords_copy = copy.deepcopy(coords)
    if s:
        if isinstance(coords_copy, dict) and "_processed" not in coords_copy:
            lat, lon = coords_copy["lat"], coords_copy["lon"]
            coords_copy["sum"] = round(lat + lon, 6)
            coords_copy["_processed"] = True
        elif isinstance(coords_copy, (list, tuple)) and len(coords_copy) == 2 and "_processed" not in coords_copy:
            lat, lon = coords_copy
            coords_copy = round(lat + lon, 6)
            coords_copy = {"sum": coords_copy, "_processed": True}
        if isinstance(coords_copy, dict) and "sum" in coords_copy:
            return coords_copy["sum"]
        else:
            return coords_copy
    else:
        if isinstance(coords_copy, dict):
            return round(coords_copy["lat"] + coords_copy["lon"], 6)
        else:
            return coords_copy