from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.detection.base import DetectorUnavailable
from app.detection.factory import create_detector
from app.detection.mock import MockDetector
from app.streams.base import FileVideoSource
from app.streams.factory import validate_source


def test_mock_detector_finds_moving_objects(sample_video):
    src = FileVideoSource(str(sample_video))
    src.open()
    det = MockDetector()
    now = datetime.now(timezone.utc)
    seen = set()
    for i in range(200):
        ok, frame = src.read()
        assert ok
        for d in det.detect(frame, 1, now):
            seen.add(d.cls)
            assert 0 < d.confidence <= 1 and d.bbox.width > 0 and d.stream_id == 1
    src.close()
    assert {"person", "car"} <= seen


def test_detection_schema_uses_class_alias():
    from app.core.schemas import BBox, Detection

    d = Detection(stream_id=1, cls="person", confidence=0.5, bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                  timestamp=datetime.now(timezone.utc))
    assert d.model_dump(by_alias=True)["class"] == "person"


def test_yolo_missing_dependency_is_clear_or_falls_back():
    s = Settings(detector="yolo")
    try:
        import ultralytics  # noqa: F401
        pytest.skip("ultralytics installed")
    except ImportError:
        pass
    with pytest.raises(DetectorUnavailable):
        create_detector(s)
    assert isinstance(create_detector(Settings(detector="yolo", detector_fallback_to_mock=True)), MockDetector)


def test_validate_source(sample_video):
    s = Settings(video_dir=str(sample_video.parent))
    assert validate_source("file", sample_video.name, s) == str(sample_video)
    with pytest.raises(ValueError):
        validate_source("file", "/etc/passwd", s)
    with pytest.raises(ValueError):
        validate_source("rtsp", "http://nope", s)
    with pytest.raises(ValueError):
        validate_source("webcam", "abc", s)
    assert validate_source("webcam", None, s) == "0"
    assert validate_source("rtsp", "rtsp://cam/stream", s)
