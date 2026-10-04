"""Pure geometry helpers (no OpenCV dependency, easy to unit-test)."""
from __future__ import annotations

from typing import Optional, Sequence

Point = tuple[float, float]
Box = tuple[float, float, float, float]


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def side_of_line(p1: Point, p2: Point, pt: Point) -> float:
    """Signed cross product: >0 on one side of directed line p1->p2, <0 on the other."""
    return (p2[0] - p1[0]) * (pt[1] - p1[1]) - (p2[1] - p1[1]) * (pt[0] - p1[0])


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    """Even-odd ray casting."""
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def crossing_direction(prev: Point, cur: Point, p1: Point, p2: Point) -> Optional[str]:
    """Return "in"/"out" if the movement prev->cur crosses the finite segment p1-p2.

    "in" means moving from the negative to the positive side of the directed
    line p1->p2 (see ``side_of_line``); "out" is the reverse.
    """
    before = side_of_line(p1, p2, prev) > 0
    after = side_of_line(p1, p2, cur) > 0
    if before == after:
        return None
    # Movement must also pass between the segment endpoints (finite line).
    m1 = side_of_line(prev, cur, p1)
    m2 = side_of_line(prev, cur, p2)
    if m1 * m2 > 0:
        return None
    return "in" if after else "out"
