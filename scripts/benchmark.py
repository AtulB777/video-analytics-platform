"""Measure the pipeline on a video file on *your* hardware (no database, no network).

    python scripts/benchmark.py sample_videos/lobby_demo.mp4

Prints the values collected by PipelineMetrics. Numbers depend on your CPU/GPU,
detector and video; none are shipped with the repo.
"""
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python scripts/benchmark.py`

from app.analytics.config import load_profiles
from app.analytics.engine import AnalyticsEngine
from app.core.config import get_settings
from app.detection.factory import create_detector
from app.events.engine import EventEngine
from app.streams.base import FileVideoSource
from app.streams.pipeline import StreamPipeline
from app.tracking.factory import create_tracker


def main(path: str) -> None:
    s = replace(get_settings(), file_playback_speed=0.0, loop_video=False)  # offline: no pacing
    cfg = load_profiles(s)["default"]
    pipe = StreamPipeline(1, "bench", FileVideoSource(path), create_detector(s), create_tracker(s),
                          AnalyticsEngine(cfg), EventEngine(1, cfg.crowd_threshold), s)
    t0 = time.perf_counter()
    pipe.start()
    while pipe.running:
        time.sleep(0.1)
    wall = time.perf_counter() - t0
    h = pipe.health()
    print(f"wall time: {wall:.2f}s  detector={h['detector']} tracker={h['tracker']}")
    for k in ("frames_received", "frames_processed", "skipped_frames", "dropped_frames",
              "inference_ms_avg", "inference_ms_p95", "pipeline_ms_avg", "pipeline_ms_p95"):
        print(f"{k:>20}: {h[k]}")
    print("stages:", h["stages"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample_videos/lobby_demo.mp4")
