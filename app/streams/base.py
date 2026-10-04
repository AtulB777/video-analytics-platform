"""VideoSource abstraction and OpenCV-backed implementations."""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.core.utils import mask_uri

log = logging.getLogger(__name__)


class VideoSource(ABC):
    """A pull-based frame source.

    ``is_live`` sources (webcam, RTSP) are read as fast as frames arrive and
    reconnected on failure. Non-live sources (files) end at EOF.
    """

    is_live: bool = False
    source_type: str = "unknown"

    def __init__(self, uri: str):
        self.uri = uri

    @property
    def safe_uri(self) -> str:
        return mask_uri(self.uri) or ""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def read(self) -> tuple[bool, Optional[np.ndarray]]: ...

    @abstractmethod
    def close(self) -> None: ...

    @property
    def fps(self) -> float:
        return 0.0

    def reopen(self) -> None:
        self.close()
        self.open()


class _CaptureSource(VideoSource):
    def __init__(self, uri: str):
        super().__init__(uri)
        self._cap: Optional[cv2.VideoCapture] = None

    def _make_capture(self) -> cv2.VideoCapture:
        raise NotImplementedError

    def open(self) -> None:
        cap = self._make_capture()
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Could not open {self.source_type} source: {self.safe_uri}")
        self._cap = cap

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        return bool(ok), (frame if ok else None)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def fps(self) -> float:
        if self._cap is None:
            return 0.0
        v = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        return v if 0 < v < 1000 else 0.0


class FileVideoSource(_CaptureSource):
    source_type = "file"
    is_live = False

    def __init__(self, path: str, loop: bool = False):
        super().__init__(path)
        self.loop = loop

    def _make_capture(self) -> cv2.VideoCapture:
        if not Path(self.uri).is_file():
            raise RuntimeError(f"Video file not found: {self.uri}")
        return cv2.VideoCapture(self.uri)

    def read(self):
        ok, frame = super().read()
        if not ok and self.loop and self._cap is not None:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = super().read()
        return ok, frame


class WebcamVideoSource(_CaptureSource):
    source_type = "webcam"
    is_live = True

    def __init__(self, device: str | int = 0):
        super().__init__(str(device))

    def _make_capture(self) -> cv2.VideoCapture:
        return cv2.VideoCapture(int(self.uri))


class RTSPVideoSource(_CaptureSource):
    """RTSP stream via OpenCV's FFmpeg backend.

    Uses TCP transport by default (more reliable across NAT/Docker). The
    pipeline handles reconnects with exponential backoff.
    """

    source_type = "rtsp"
    is_live = True

    def _make_capture(self) -> cv2.VideoCapture:
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        cap = cv2.VideoCapture(self.uri, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # not supported by every backend build
            pass
        return cap
