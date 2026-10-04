from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import numpy as np

from app.core.schemas import Detection


class DetectorUnavailable(RuntimeError):
    """Raised when a detector's optional dependencies/weights are missing."""


class Detector(ABC):
    """Frame in, detections out. Implementations may be stateful (per stream)."""

    name = "base"

    @abstractmethod
    def detect(self, frame: np.ndarray, stream_id: int, timestamp: datetime) -> list[Detection]: ...

    def warmup(self) -> None:  # optional
        return None

    def close(self) -> None:  # optional
        return None
