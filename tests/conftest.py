import os
import tempfile
from pathlib import Path

# Environment must be set before the app (and its cached settings) is imported.
_TMP = Path(tempfile.mkdtemp(prefix="vap-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "VIDEO_DIR": str(_TMP),
    "FILE_PLAYBACK_SPEED": "0",      # as fast as possible, with back-pressure (no drops)
    "PROCESSING_FPS": "10",
    "AUTOSTART_SAMPLE": "false",
    "ZONES_CONFIG": str(Path(__file__).resolve().parent.parent / "configs" / "zones.json"),
    "METRICS_PERSIST_INTERVAL_S": "0.2",
    "STATUS_PUBLISH_INTERVAL_S": "0.2",
})

import pytest  # noqa: E402

from app.streams.sample import generate_sample_video  # noqa: E402


@pytest.fixture(scope="session")
def sample_video() -> Path:
    return generate_sample_video(_TMP / "sample.mp4")
