from datetime import datetime, timedelta, timezone

from app.analytics.config import AnalyticsConfig, LineConfig, ZoneConfig
from app.analytics.engine import AnalyticsEngine
from app.core.schemas import BBox, Detection, EventType
from app.events.engine import EventEngine
from app.tracking.iou_tracker import IoUTracker

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def det(x, y=100, w=20, h=50, cls="person"):
    return Detection(stream_id=1, cls=cls, confidence=0.9, bbox=BBox(x1=x, y1=y, x2=x + w, y2=y + h), timestamp=T0)


def ts(i):
    return T0 + timedelta(seconds=i * 0.1)


def test_tracker_keeps_id_and_confirms_after_min_hits():
    tr = IoUTracker(min_hits=3)
    assert tr.update([det(10)], ts(0)) == []
    assert tr.update([det(12)], ts(1)) == []
    out = tr.update([det(14)], ts(2))
    assert len(out) == 1 and out[0].track_id == 1
    out = tr.update([det(16)], ts(3))
    assert out[0].track_id == 1 and out[0].first_seen == ts(0)


def test_tracker_separates_objects_and_classes():
    tr = IoUTracker(min_hits=1)
    out = tr.update([det(10), det(200), det(10, cls="car")], ts(0))
    assert len({t.track_id for t in out}) == 3


def test_tracker_drops_stale_tracks():
    tr = IoUTracker(min_hits=1, max_age=2)
    tr.update([det(10)], ts(0))
    for i in range(1, 5):
        tr.update([], ts(i))
    out = tr.update([det(10)], ts(5))
    assert out[0].track_id == 2  # old track expired, new ID issued


def _run(xs, cfg, cls="person", stream_id=1):
    tracker, analytics = IoUTracker(min_hits=1), AnalyticsEngine(cfg)
    analytics.set_frame_size(200, 200)
    events = EventEngine(stream_id, cfg.crowd_threshold, cfg.crowd_hysteresis, debounce_frames=2, exit_grace_s=0.3)
    all_events, snaps = [], []
    for i, frame_dets in enumerate(xs):
        tracks = tracker.update(frame_dets, ts(i))
        snap = analytics.update(tracks, ts(i))
        snaps.append(snap)
        all_events += events.process(snap)
    return snaps, all_events


LINE_CFG = AnalyticsConfig(lines=[LineConfig("gate", (100, 200), (100, 0))], normalized=False)


def test_line_crossing_counts_direction():
    xs = [[det(x)] for x in range(60, 150, 10)]  # left -> right
    snaps, events = _run(xs, LINE_CFG)
    crossed = [e for e in events if e.type == EventType.LINE_CROSSED]
    assert len(crossed) == 1 and crossed[0].payload["direction"] == "in"
    assert snaps[-1].line_counts["gate"] == {"in": 1, "out": 0}

    _, events = _run(list(reversed(xs)), LINE_CFG)
    assert [e.payload["direction"] for e in events if e.type == EventType.LINE_CROSSED] == ["out"]


def test_zone_enter_and_exit_events():
    cfg = AnalyticsConfig(zones=[ZoneConfig("z", [(80, 0), (140, 0), (140, 200), (80, 200)])], normalized=False)
    path = [20, 40, 60, 100, 110, 120, 130, 170, 180, 190]
    _, events = _run([[det(x)] for x in path], cfg)
    kinds = [e.type for e in events]
    assert kinds.count(EventType.PERSON_ENTERED_ZONE) == 1
    assert kinds.count(EventType.PERSON_EXITED_ZONE) == 1
    assert kinds.index(EventType.PERSON_ENTERED_ZONE) < kinds.index(EventType.PERSON_EXITED_ZONE)


def test_crowd_threshold_debounce_and_clear():
    cfg = AnalyticsConfig(crowd_threshold=2, crowd_hysteresis=1, normalized=False)
    crowd = [det(10 + 40 * i) for i in range(4)]
    frames = [crowd] * 5 + [crowd[:1]] * 3
    _, events = _run(frames, cfg)
    kinds = [e.type for e in events]
    assert kinds.count(EventType.CROWD_THRESHOLD_EXCEEDED) == 1
    assert kinds.count(EventType.CROWD_THRESHOLD_CLEARED) == 1
    assert kinds[0] == EventType.CROWD_THRESHOLD_EXCEEDED


def test_object_and_people_counts():
    cfg = AnalyticsConfig(normalized=False)
    snaps, _ = _run([[det(10), det(100), det(50, cls="car")]] * 2, cfg)
    assert snaps[-1].people_count == 2
    assert snaps[-1].object_counts == {"person": 2, "car": 1}
    assert snaps[-1].unique_objects == {"person": 2, "car": 1}
