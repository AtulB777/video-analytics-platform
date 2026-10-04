"""YOLODetector backed by Ultralytics (optional dependency).

Install with ``pip install -r requirements-yolo.txt``. Weights are loaded from
``YOLO_MODEL`` (a local path, or a model name that Ultralytics downloads on
first use, which needs network access).
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Iterable, Optional

import numpy as np

from app.core.schemas import BBox, Detection
from app.detection.base import Detector, DetectorUnavailable


class YOLODetector(Detector):
    name = "yolo"
    _models: dict[tuple[str, str], object] = {}
    _models_lock = threading.Lock()
    _infer_lock = threading.Lock()  # one shared model; serialise predict() calls

    def __init__(self, model_path: str, confidence_threshold: float = 0.4,
                 classes: Optional[Iterable[str]] = None, device: str = "", imgsz: int = 640):
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            raise DetectorUnavailable(
                "ultralytics is not installed. Run: pip install -r requirements-yolo.txt"
            ) from exc
        self.confidence_threshold = confidence_threshold
        self.allowed = {c.lower() for c in classes} if classes else None
        self.device = device or None
        self.imgsz = imgsz
        key = (model_path, device)
        with self._models_lock:
            if key not in self._models:
                try:
                    self._models[key] = YOLO(model_path)
                except Exception as exc:
                    raise DetectorUnavailable(f"Could not load YOLO model '{model_path}': {exc}") from exc
            self._model = self._models[key]

    def warmup(self) -> None:
        self.detect(np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8), 0, datetime.utcnow())

    def detect(self, frame: np.ndarray, stream_id: int, timestamp: datetime) -> list[Detection]:
        with self._infer_lock:
            result = self._model.predict(frame, conf=self.confidence_threshold, imgsz=self.imgsz,
                                         device=self.device, verbose=False)[0]
        names = result.names
        out: list[Detection] = []
        for box in result.boxes:
            cls_name = str(names[int(box.cls[0])]).lower()
            if self.allowed and cls_name not in self.allowed:
                continue
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            out.append(Detection(stream_id=stream_id, cls=cls_name, confidence=float(box.conf[0]),
                                 bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2), timestamp=timestamp))
        return out
