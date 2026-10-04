# Real-Time Video Analytics Platform

A portfolio-grade video analytics service: it ingests one or more video streams, runs
detection and tracking, derives analytics (counts, line crossings, zone occupancy),
emits events, stores everything in PostgreSQL, and exposes it over a REST API,
a WebSocket feed and a Streamlit dashboard.

It runs locally with **no camera, GPU, model download or dataset**. A synthetic sample video
is generated on first start, and a model-free `MockDetector` drives the pipeline. Real YOLO
inference and RTSP cameras plug in behind the same interfaces.

```
Video Source -> Stream Manager -> Frame Processing -> Detection -> Tracking
             -> Event Engine / Analytics -> Storage -> FastAPI -> Dashboard
```

## Quick start

### Docker (API + PostgreSQL + dashboard)

```bash
docker compose up --build
```

| Service   | URL                          |
|-----------|------------------------------|
| Dashboard | http://localhost:8501        |
| API docs  | http://localhost:8000/docs   |
| WebSocket | ws://localhost:8000/ws       |

`AUTOSTART_SAMPLE=true` is set in the compose file, so a "Sample lobby camera" stream starts
automatically (the video is generated into `./sample_videos/` and looped).

### Local (SQLite, no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                       # AUTOSTART_SAMPLE=true, SQLite by default
uvicorn app.main:app --reload              # API  -> http://localhost:8000/docs
streamlit run dashboard/app.py             # UI   -> http://localhost:8501
pytest                                     # tests
```

To use PostgreSQL locally, set
`DATABASE_URL=postgresql+psycopg2://vap:vap@localhost:5432/vap`.

Watch the live feed from a terminal: `python scripts/ws_client.py ws://localhost:8000/ws event`

## The sample video

`python -m app.streams.sample` writes `sample_videos/lobby_demo.mp4` (28 s, 640x360, 20 fps).
It is synthetic: coloured rectangles act as pedestrians (tall) and cars (wide), scripted so that every
analytic fires: people cross the entrance line in both directions, one person lingers in the lobby
zone, a group of six creates a crowd, and two cars pass. Any other MP4 inside `VIDEO_DIR`
works too, but the mock detector only finds motion against a static background (see Limitations).

## Architecture

Diagrams (system, per-frame sequence, ER schema) are in [`docs/architecture.md`](docs/architecture.md).

```mermaid
flowchart TD
    VS[VideoSource<br/>File / Webcam / RTSP] --> SM[Stream Manager]
    SM --> FP[Frame processing<br/>reader thread -> bounded queue -> throttle]
    FP --> DET[Detector<br/>Mock / YOLO]
    DET --> TRK[Tracker<br/>IoU / ByteTrack]
    TRK --> AN[Analytics<br/>counts, lines, zones]
    AN --> EV[Event engine]
    EV --> DB[(PostgreSQL)]
    EV --> WS[WebSocket hub]
    DB --> API[FastAPI]
    WS --> API
    API --> UI[Streamlit dashboard]
```

```
app/
  api/         REST routes and request/response schemas
  core/        settings (env vars), shared schemas, geometry helpers
  streams/     VideoSource implementations, StreamPipeline, StreamManager, overlay, sample generator
  detection/   Detector interface, MockDetector, YOLODetector, factory
  tracking/    Tracker interface, IoUTracker, ByteTrack adapter, factory
  analytics/   AnalyticsEngine (counts, lines, zones) and profile loading
  events/      EventEngine (stateful event generation)
  monitoring/  PipelineMetrics
  database/    SQLAlchemy models, session, repository
  websocket/   hub (thread-safe fan-out) and /ws route
dashboard/     Streamlit app          configs/   zones.json
tests/         pytest suite           scripts/   ws_client.py, benchmark.py
```

### Pipeline design

Each stream gets one `StreamPipeline` with two threads joined by a bounded queue:

- **Reader thread** pulls frames from the `VideoSource`. Files are paced to their native FPS
  (`FILE_PLAYBACK_SPEED`; `0` = as fast as possible with back-pressure). Live sources are read as
  frames arrive. When the queue is full the **oldest frame is dropped** and counted, so latency stays
  bounded instead of growing. Live sources reconnect with exponential backoff.
- **Processor thread** throttles to `PROCESSING_FPS` using the frame timeline (not wall-clock, so
  offline playback behaves identically), then runs detect -> track -> analytics -> events, persists,
  publishes, and renders a preview JPEG.

Separating the threads means a slow detector causes counted drops rather than stalling the camera
connection.

## Detection / tracking pipeline

- **`Detector`** (`detect(frame, stream_id, timestamp) -> list[Detection]`). A `Detection` carries
  `class`, `confidence`, `bbox`, `timestamp`, `stream_id`.
  - `MockDetector`: MOG2 background subtraction; labels tall blobs `person`, wide blobs `car`.
  - `YOLODetector`: Ultralytics wrapper (shared model cache, serialised `predict`), class filter via
    `DETECT_CLASSES`.
- **`Tracker`** (`update(detections, timestamp) -> list[TrackedObject]`). A `TrackedObject` has
  `track_id`, `class`, `bbox`, `first_seen`, `last_seen`, plus a short history of anchor points.
  - `IoUTracker` (default, dependency-free): class-aware greedy IoU matching, tracks are confirmed after
    3 hits (so IDs are not wasted on one-frame noise), and expire after 15 missed frames.
  - `ByteTrackTracker`: adapter over the optional `supervision` package. **Experimental and not covered
    by the tests.** DeepSORT can be wrapped the same way.
  - Track IDs continue from the stored maximum when a stream restarts, so `(stream_id, track_id)`
    stays unique.

Line and zone tests use an *anchor point*: the bottom-centre of the box for people (their feet), the
centre for everything else.

## Analytics

| Analytic          | Definition |
|-------------------|------------|
| Object counting   | Visible tracks per class in the current frame, plus distinct track IDs seen since the stream started |
| People counting   | Visible `person` tracks in the current frame |
| Line crossing     | The anchor's last movement segment intersects the finite line. `in` = moving from the negative to the positive side of the directed line `p1 -> p2`, `out` = the reverse. Cumulative in/out counts are kept per line |
| Zone occupancy    | People whose anchor lies in the zone polygon (ray casting) |

Lines and zones come from `configs/zones.json` (or inline `ZONES_JSON`). Coordinates are normalised
0..1 by default, so one profile works at any resolution; set `"normalized": false` for pixels.
Streams select a profile by name (`profile` in `POST /streams`).

```json
{ "default": { "normalized": true, "crowd_threshold": 5,
    "lines": [{ "name": "entrance", "p1": [0.5, 1.0], "p2": [0.5, 0.0] }],
    "zones": [{ "name": "lobby", "polygon": [[0.6,0.15],[0.95,0.15],[0.95,0.85],[0.6,0.85]] }] } }
```

## Event engine

`EventEngine` is stateful and turns analytics snapshots into discrete events.

| Event | Fires when |
|-------|-----------|
| `LINE_CROSSED` | A tracked object crosses a line; payload has `direction` and cumulative line counts |
| `PERSON_ENTERED_ZONE` | A person's anchor is inside a zone and was not in the previous state |
| `PERSON_EXITED_ZONE` | The person is visible outside the zone, or has been undetected for `exit_grace_s` (default 1 s). The grace period stops detector flicker from producing enter/exit pairs |
| `CROWD_THRESHOLD_EXCEEDED` | People count > `crowd_threshold` for 3 consecutive processed frames |
| `CROWD_THRESHOLD_CLEARED` | People count <= `crowd_threshold - crowd_hysteresis` |

Events are persisted and pushed to WebSocket clients.

## Database schema

Tables: `cameras`, `streams`, `detections`, `tracks`, `events`, `processing_metrics`
(ER diagram in [`docs/architecture.md`](docs/architecture.md)).

- `streams` links to a camera and stores source type, URI, analytics profile, status and last error.
- `detections` holds raw per-frame boxes (indexed on `stream_id, timestamp`).
- `tracks` holds one row per `(stream_id, track_id)` with first/last seen and last box.
- `events` holds type, timestamp, track, zone/line and a JSON payload.
- `processing_metrics` holds periodic samples of FPS, latency, queue size and drops.

Tables are created with `create_all` on startup to keep the demo self-contained. A real deployment
should use Alembic migrations.

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/streams` | Create a stream: `{name, source_type: file\|webcam\|rtsp, uri, profile?, autostart?}` |
| GET | `/streams` | List streams with live status and health |
| DELETE | `/streams/{id}` | Stop and delete a stream and its data |
| POST | `/streams/{id}/start` | Start processing (idempotent) |
| POST | `/streams/{id}/stop` | Stop processing |
| GET | `/streams/{id}/analytics` | Current counts, zone occupancy, cumulative line counts, current objects, health |
| GET | `/events` | Filter by `stream_id`, `type`, `since`; `limit`, `offset` |
| GET | `/health` | Service health (503 if the database is unreachable) |
| GET | `/streams/{id}/metrics` | Extra: live metrics and recent persisted samples |
| GET | `/streams/{id}/frame.jpg` | Extra: latest annotated frame |
| WS | `/ws?stream_id=N` | Real-time feed |

```bash
curl -X POST localhost:8000/streams -H 'content-type: application/json' \
  -d '{"name":"demo","source_type":"file","uri":"lobby_demo.mp4","autostart":true}'
curl localhost:8000/streams/1/analytics
curl 'localhost:8000/events?type=LINE_CROSSED&limit=10'
```

**WebSocket** messages share one envelope, `{"type", "stream_id", "timestamp", "data"}`, with types
`stream_status` (status plus health, on change and every `STATUS_PUBLISH_INTERVAL_S`), `detections`
(tracked objects per processed frame), `analytics` (counts, occupancy, line counts) and `event`.
Send `{"subscribe": [1, 2]}` to change the stream filter.

File sources must live inside `VIDEO_DIR` (path-traversal guard). RTSP credentials are masked in API
responses.

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)); a local `.env` is loaded
automatically.

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite:///./vap.db` | SQLAlchemy URL (PostgreSQL in Docker) |
| `DETECTOR` | `mock` | `mock` or `yolo` |
| `YOLO_MODEL`, `YOLO_DEVICE`, `DETECT_CLASSES` | `yolov8n.pt`, auto, COCO subset | YOLO settings |
| `CONFIDENCE_THRESHOLD` | `0.4` | Minimum detection confidence |
| `PROCESSING_FPS` | `10` | Target processing rate per stream (`0` = every frame) |
| `TRACKER` | `iou` | `iou` or `bytetrack` |
| `ZONES_CONFIG` / `ZONES_JSON` | `configs/zones.json` | Lines and zones (file or inline) |
| `CROWD_THRESHOLD` | from profile | Override the profile's crowd threshold |
| `FILE_PLAYBACK_SPEED` | `1.0` | `1` = real time, `0` = as fast as possible |
| `QUEUE_SIZE` | `8` | Frame queue length per stream |
| `PERSIST_DETECTIONS`, `PERSIST_EVERY_N` | `true`, `1` | Control raw-detection write volume |
| `AUTOSTART_SAMPLE`, `LOOP_VIDEO` | `false` | Demo conveniences |

## Performance considerations

`PipelineMetrics` (`app/monitoring/metrics.py`) is a thread-safe collector that measures, over a
sliding window: processing FPS and input FPS, inference latency, per-stage latency, total pipeline
latency (capture to finished, including queue wait; average and p95), queue size, dropped frames
(queue overflow) and skipped frames (intentional `PROCESSING_FPS` throttling). The same values feed
`/streams`, `/streams/{id}/analytics`, `/streams/{id}/metrics`, the dashboard, the WebSocket feed and the
`processing_metrics` table. `last_frame_timestamp` plus `status` give camera health.

**This repository ships no benchmark numbers.** Measure on your own hardware with
`python scripts/benchmark.py <video>`, which runs the pipeline offline and prints the collected metrics.

Design choices that matter at scale:

- Bounded queue with drop-oldest keeps latency flat under overload, and drops are visible, not silent.
- Processing FPS is decoupled from camera FPS; most analytics do not need 25-30 fps.
- Raw detections are the highest-volume table. Use `PERSIST_EVERY_N` / `PERSIST_DETECTIONS=false`, and add
  retention or partitioning for real deployments.
- Track and metric writes are batched or periodic; events are written immediately.
- The preview JPEG is encoded every processed frame. That is cheap for a demo but is the first thing to
  make on-demand for many streams.
- One thread pair per stream suits a handful of streams. Beyond that, move to worker processes or
  batched GPU inference.

## How to replace the mock detector

1. Install the extras: `pip install -r requirements-yolo.txt` (or build with `--build-arg INSTALL_YOLO=true`).
2. Put weights at `models/yolov8n.pt` (mounted into the container), or let Ultralytics download them
   (needs network access).
3. Set `DETECTOR=yolo`, `YOLO_MODEL=models/yolov8n.pt`, optionally `YOLO_DEVICE=0` for a GPU.
4. Set `DETECTOR_FALLBACK_TO_MOCK=true` if you want startup to degrade instead of fail when YOLO is unavailable.

To plug in a different model (ONNX, TensorRT, a remote inference server), implement `Detector.detect()`
in `app/detection/`, return `Detection` objects, and register it in `app/detection/factory.py`.

> `YOLODetector` is written against the Ultralytics API but was **not run** in this repository's tests
> (the dependency is optional and no weights are bundled). Treat it as untested until you run it.

## How to add RTSP

The pieces already exist: `RTSPVideoSource` (OpenCV/FFmpeg, TCP transport, minimal buffering), reconnect
with exponential backoff capped by `RTSP_RECONNECT_MAX_S`, a `reconnecting` status, and URI validation and
credential masking.

```bash
curl -X POST localhost:8000/streams -H 'content-type: application/json' \
  -d '{"name":"dock","source_type":"rtsp","uri":"rtsp://user:pass@192.168.1.20:554/stream1","autostart":true}'
```

To harden it for production: add read/open timeouts appropriate to your cameras, a stall watchdog (no frame
for N seconds), per-camera analytics profiles, and secret storage for credentials (see Limitations).
For many cameras, put a media server (e.g. MediaMTX) in front and consume a normalised stream. RTSP is
implemented but was not tested against a live camera here.

## Testing

`pytest` runs 21 tests: geometry, tracker, analytics and event engine behaviour, metrics math, the mock
detector on the generated video, source validation, and an end-to-end test that creates a stream through
the API, runs it to completion, and checks WebSocket messages, persisted events, line counts, metrics, the
preview frame and deletion. A second end-to-end test stops and restarts a stream to check track ID
uniqueness.

## Limitations

- **MockDetector is not object recognition.** It finds moving blobs on a static background and guesses a
  class from aspect ratio. Moving cameras, lighting changes and stationary people will break it.
- **The IoU tracker has no motion model or appearance features.** Fast motion, occlusion and crowds cause ID
  switches. Use ByteTrack/DeepSORT with a real detector for such scenes.
- **YOLO and ByteTrack paths are untested here**, as are webcam and RTSP against real hardware.
- **No authentication or authorisation** on the API or WebSocket; CORS is open by default. Add auth and
  TLS before exposing it.
- **RTSP credentials are stored in plaintext** in the `streams` table (masked only in API output).
- **Schema management uses `create_all`**, not migrations. No data retention policy exists for
  `detections`.
- **Single-process design:** pipelines run as threads in the API process, so streams share a GIL and
  fail together. Webcams are not available inside Docker on macOS/Windows (on Linux pass `--device /dev/video0`).
- **The dashboard polls the REST API** rather than consuming the WebSocket feed, so it is not truly
  real-time. Streamlit reruns the script on each refresh.
- **File timestamps are wall-clock** at processing time, not the video's own timeline.
- Line-crossing uses one anchor point per object; objects that jitter exactly on a line can produce
  repeated crossings.

## Roadmap ideas

Alembic migrations, auth, a React dashboard on the WebSocket feed, worker processes with a message queue,
batched GPU inference, per-camera calibration, Prometheus metrics export, and re-identification across cameras.
