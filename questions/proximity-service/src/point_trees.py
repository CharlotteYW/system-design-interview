"""Small in-memory Quadtree and k-d tree implementations for comparison."""

from dataclasses import dataclass
from uuid import UUID

from .geohash_cover import cover_bounds

LEAF_SIZE = 2
MAX_QUAD_DEPTH = 18


@dataclass(frozen=True)
class Point:
    business_id: UUID
    longitude: float
    latitude: float


@dataclass(frozen=True)
class Box:
    west: float
    south: float
    east: float
    north: float

    def overlaps(self, other: "Box") -> bool:
        return (
            self.west <= other.east and self.east >= other.west
            and self.south <= other.north and self.north >= other.south
        )

    def contains(self, point: Point) -> bool:
        return self.west <= point.longitude <= self.east and self.south <= point.latitude <= self.north


@dataclass
class Node:
    bounds: Box
    points: list[Point]
    children: tuple["Node", ...] = ()


def _quad(points: list[Point], bounds: Box, depth: int = 0) -> Node:
    if len(points) <= LEAF_SIZE or depth == MAX_QUAD_DEPTH:
        return Node(bounds, points)
    mid_x, mid_y = (bounds.west + bounds.east) / 2, (bounds.south + bounds.north) / 2
    groups: list[list[Point]] = [[], [], [], []]
    for point in points:
        groups[2 * (point.latitude >= mid_y) + (point.longitude >= mid_x)].append(point)
    boxes = (
        Box(bounds.west, bounds.south, mid_x, mid_y),
        Box(mid_x, bounds.south, bounds.east, mid_y),
        Box(bounds.west, mid_y, mid_x, bounds.north),
        Box(mid_x, mid_y, bounds.east, bounds.north),
    )
    return Node(bounds, [], tuple(_quad(group, box, depth + 1) for group, box in zip(groups, boxes) if group))


def _kd(points: list[Point], depth: int = 0) -> Node:
    bounds = Box(
        min(point.longitude for point in points), min(point.latitude for point in points),
        max(point.longitude for point in points), max(point.latitude for point in points),
    )
    if len(points) <= LEAF_SIZE:
        return Node(bounds, points)
    key = (lambda point: point.longitude) if depth % 2 == 0 else (lambda point: point.latitude)
    ordered = sorted(points, key=key)
    middle = len(ordered) // 2
    return Node(bounds, [], (_kd(ordered[:middle], depth + 1), _kd(ordered[middle:], depth + 1)))


def tree_candidates(
    mode: str, points: list[Point], latitude: float, longitude: float, radius: float
) -> tuple[list[UUID], int]:
    if not points:
        return [], 0
    south, north, longitude_ranges = cover_bounds(latitude, longitude, radius)
    query = [Box(west, south - 1e-10, east, north + 1e-10) for west, east in longitude_ranges]
    root = _quad(points, Box(-180, -90, 180, 90)) if mode == "quadtree" else _kd(points)
    pending = [root]
    candidates = []
    visited = 0
    while pending:
        node = pending.pop()
        visited += 1
        overlapping = [box for box in query if box.overlaps(node.bounds)]
        if overlapping:
            pending.extend(node.children)
            candidates.extend(
                point.business_id for point in node.points if any(box.contains(point) for box in overlapping)
            )
    return candidates, visited
