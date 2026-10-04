"""MockDetector: a model-free stand-in so the platform runs without a GPU.

It uses OpenCV background subtraction (MOG2) to find moving blobs and labels
them with a crude aspect-ratio heuristic (tall -> "person", wide -> "car").
It is **not** an object recognizer: it only demonstrates the pipeline, and it
works well on static-camera footage such as the generated sample video.
"""
from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np

from app.core.schemas import BBox, Detection
from app.detection.base import Detector


class MockDetector(Detector):
    name = "mock"

    def __init__(self, confidence_threshold: float = 0.0, min_area: int = 300, learning_rate: float = 0.002):
        self.confidence_threshold = confidence_threshold
        self.min_area = min_area
        self.learning_rate = learning_rate
        self._bg = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=32, detectShadows=False)
        self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    def detect(self, frame: np.ndarray, stream_id: int, timestamp: datetime) -> list[Detection]:
        mask = self._bg.apply(frame, learningRate=self.learning_rate)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_area = float(frame.shape[0] * frame.shape[1])
        out: list[Detection] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            cls = "person" if h / max(w, 1) >= 1.2 else "car"
            # Pseudo-confidence grows with blob size; clearly synthetic by design.
            conf = round(min(0.99, 0.55 + 0.44 * min(1.0, area / (frame_area * 0.01))), 3)
            if conf < self.confidence_threshold:
                continue
            out.append(
                Detection(stream_id=stream_id, cls=cls, confidence=conf,
                          bbox=BBox(x1=x, y1=y, x2=x + w, y2=y + h), timestamp=timestamp)
            )
        return out
