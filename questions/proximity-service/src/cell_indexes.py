"""S2 and H3 candidate indexes for the advanced lab."""

import math
from pathlib import Path
from uuid import UUID

import h3
from psycopg import Connection
from s2sphere import Angle, Cap, CellId, LatLng, RegionCoverer

from .geohash_cover import LOWER_EARTH_RADIUS_METERS, cover_bounds

S2_STORAGE_LEVEL = 13
H3_RESOLUTION = 7
_SCHEMA = Path(__file__).with_name("cell_schema.sql")


def _s2_key(cell: CellId) -> str:
    # Fixed width and C collation preserve the unsigned ID order in PostgreSQL.
    return format(cell.id(), "016x")


def store_cell_keys(conn: Connection, business_id: UUID, latitude: float, longitude: float) -> None:
    s2 = CellId.from_lat_lng(LatLng.from_degrees(latitude, longitude)).parent(S2_STORAGE_LEVEL)
    rows = [
        ("s2", _s2_key(s2), business_id),
        ("h3", h3.latlng_to_cell(latitude, longitude, H3_RESOLUTION), business_id),
    ]
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO business_cell_keys (method, cell_id, business_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (business_id, method) DO UPDATE SET cell_id = EXCLUDED.cell_id
            """,
            rows,
        )


def prepare_cell_keys(conn: Connection) -> None:
    """Create the comparison table and backfill existing lab rows on startup."""
    conn.execute(_SCHEMA.read_text())
    missing = conn.execute(
        """
        SELECT b.business_id, ST_Y(b.location::geometry) AS latitude,
               ST_X(b.location::geometry) AS longitude
        FROM businesses b
        WHERE (SELECT count(*) FROM business_cell_keys k WHERE k.business_id = b.business_id) < 2
        """
    ).fetchall()
    for row in missing:
        store_cell_keys(conn, row["business_id"], row["latitude"], row["longitude"])


def s2_ranges(latitude: float, longitude: float, radius: float) -> list[tuple[str, str]]:
    point = LatLng.from_degrees(latitude, longitude).to_point()
    cap = Cap.from_axis_angle(point, Angle.from_radians(radius / LOWER_EARTH_RADIUS_METERS + 1e-9))
    coverer = RegionCoverer()
    coverer.max_level = S2_STORAGE_LEVEL
    coverer.max_cells = 16
    return [(_s2_key(cell.range_min()), _s2_key(cell.range_max())) for cell in coverer.get_covering(cap)]


def h3_cover(latitude: float, longitude: float, radius: float) -> list[str] | None:
    # Use a conservative polygon around the spherical cap. A regular spherical
    # polygon's sides touch that cap when tan(vertex_angle) * cos(pi/n) = tan(cap_angle).
    sides = 24
    angle = radius / LOWER_EARTH_RADIUS_METERS
    vertex_angle = math.atan(math.tan(angle) / math.cos(math.pi / sides)) + 1e-9
    south, north, longitude_ranges = cover_bounds(
        latitude, longitude, vertex_angle * LOWER_EARTH_RADIUS_METERS
    )
    # Keep polar and date-line polygons outside this demo's H3 polygon path.
    if south <= -90 or north >= 90 or len(longitude_ranges) > 1:
        return None

    lat, lon = math.radians(latitude), math.radians(longitude)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_a, cos_a = math.sin(vertex_angle), math.cos(vertex_angle)
    vertices = []
    for index in range(sides):
        bearing = math.tau * index / sides
        lat2 = math.asin(sin_lat * cos_a + cos_lat * sin_a * math.cos(bearing))
        lon2 = lon + math.atan2(
            math.sin(bearing) * sin_a * cos_lat, cos_a - sin_lat * math.sin(lat2)
        )
        vertices.append((math.degrees(lat2), math.degrees(lon2)))
    return sorted(h3.h3shape_to_cells_experimental(h3.LatLngPoly(vertices), H3_RESOLUTION, contain="overlap"))
