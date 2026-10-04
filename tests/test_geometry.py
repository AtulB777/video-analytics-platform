from app.core.geometry import crossing_direction, iou, point_in_polygon

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-9


def test_point_in_polygon():
    assert point_in_polygon((5, 5), SQUARE)
    assert not point_in_polygon((15, 5), SQUARE)
    assert not point_in_polygon((-1, -1), SQUARE)


def test_crossing_direction_both_ways_and_miss():
    p1, p2 = (50, 100), (50, 0)  # upward line at x=50
    assert crossing_direction((40, 50), (60, 50), p1, p2) == "in"
    assert crossing_direction((60, 50), (40, 50), p1, p2) == "out"
    assert crossing_direction((40, 50), (45, 50), p1, p2) is None
    # passes the infinite line, but beyond the segment end
    assert crossing_direction((40, 150), (60, 150), p1, p2) is None
