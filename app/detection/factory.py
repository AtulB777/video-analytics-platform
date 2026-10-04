from __future__ import annotations

import logging

from app.core.config import Settings
from app.detection.base import Detector, DetectorUnavailable
from app.detection.mock import MockDetector

log = logging.getLogger(__name__)


def create_detector(settings: Settings) -> Detector:
    name = settings.detector
    if name == "mock":
        return MockDetector(confidence_threshold=settings.confidence_threshold)
    if name == "yolo":
        try:
            from app.detection.yolo import YOLODetector

            return YOLODetector(settings.yolo_model, settings.confidence_threshold,
                                settings.detect_classes, settings.yolo_device)
        except DetectorUnavailable as exc:
            if settings.detector_fallback_to_mock:
                log.warning("YOLO unavailable (%s); falling back to MockDetector", exc)
                return MockDetector(confidence_threshold=settings.confidence_threshold)
            raise
    raise ValueError(f"Unknown DETECTOR '{name}' (expected 'mock' or 'yolo')")
