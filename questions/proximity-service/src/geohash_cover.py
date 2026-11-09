"""Cover a meter-based radius with fixed, four-character Geohash keys."""

import math

ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"
BINS = 1024  # Four characters encode ten bits per coordinate.
# Smaller than the minimum WGS 84 curvature radius, for a conservative cover.
LOWER_EARTH_RADIUS_METERS = 6_300_000


def _cell_key(x: int, y: int) -> str:
    bits = 0
    for shift in range(9, -1, -1):
        bits = (bits << 2) | (((x >> shift) & 1) << 1) | ((y >> shift) & 1)
    return "".join(ALPHABET[(bits >> shift) & 31] for shift in (15, 10, 5, 0))


def _bins(lower: float, upper: float, offset: int) -> range:
    step = 2 * offset / BINS
    # Include cells touching either edge, even at an exact grid boundary.
    start = max(0, min(BINS - 1, math.floor((lower + offset - 1e-10) / step)))
    end = max(0, min(BINS - 1, math.floor((upper + offset + 1e-10) / step)))
    return range(start, end + 1)


def cover_bounds(
    latitude: float, longitude: float, radius_meters: float
) -> tuple[float, float, list[tuple[float, float]]]:
    """Return conservative latitude bounds and one or two longitude ranges."""
    angle = radius_meters / LOWER_EARTH_RADIUS_METERS
    lat_delta = math.degrees(angle)
    south, north = max(-90, latitude - lat_delta), min(90, latitude + lat_delta)

    if south <= -90 or north >= 90:
        longitude_ranges = [(-180, 180)]
    else:
        delta = math.degrees(math.asin(min(1, math.sin(angle) / math.cos(math.radians(latitude)))))
        west, east = longitude - delta, longitude + delta
        if west <= -180:
            longitude_ranges = [(west + 360, 180), (-180, east)]
        elif east >= 180:
            longitude_ranges = [(west, 180), (-180, east - 360)]
        else:
            longitude_ranges = [(west, east)]

    return south, north, longitude_ranges


def cover(latitude: float, longitude: float, radius_meters: float) -> list[str]:
    south, north, longitude_ranges = cover_bounds(latitude, longitude, radius_meters)
    keys = {
        _cell_key(x, y)
        for west, east in longitude_ranges
        for x in _bins(west, east, 180)
        for y in _bins(south, north, 90)
    }
    return sorted(keys)
