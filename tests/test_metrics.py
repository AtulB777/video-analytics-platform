from app.monitoring.metrics import PipelineMetrics, percentile


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_percentile():
    assert percentile([], 95) == 0.0
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert percentile([1, 2, 3, 4], 50) == 2


def test_fps_latency_queue_and_drops():
    clock = FakeClock()
    m = PipelineMetrics(window_s=5.0, clock=clock)
    for i in range(20):  # 10 fps for 2 seconds
        clock.t = i * 0.1
        m.record_input()
        m.record_frame(pipeline_ms=10 + i, stages={"inference": 4.0})
    m.record_dropped(3)
    m.record_skipped(2)
    m.set_queue_size(4)
    clock.t = 2.0
    s = m.snapshot()
    assert s["processing_fps"] == 10.0
    assert s["inference_ms_avg"] == 4.0
    assert s["pipeline_ms_avg"] == 19.5
    assert s["pipeline_ms_p95"] == 28  # nearest-rank: ceil(0.95 * 20) = 19th of 10..29
    assert (s["queue_size"], s["dropped_frames"], s["skipped_frames"], s["frames_processed"]) == (4, 3, 2, 20)
    assert s["last_frame_timestamp"] is not None


def test_window_forgets_old_frames():
    clock = FakeClock()
    m = PipelineMetrics(window_s=1.0, clock=clock)
    m.record_frame(5.0)
    clock.t = 10.0
    s = m.snapshot()
    assert s["processing_fps"] == 0.0 and s["frames_processed"] == 1
