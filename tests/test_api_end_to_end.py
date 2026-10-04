import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client(sample_video):
    with TestClient(create_app()) as c:
        yield c


def _wait_status(client, sid, wanted, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/streams/{sid}").json()["status"]
        if st in wanted:
            return st
        time.sleep(0.25)
    raise AssertionError(f"stream {sid} never reached {wanted}; last={st}")


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"] is True


def test_validation_and_404(client):
    assert client.post("/streams", json={"name": "x", "source_type": "file", "uri": "missing.mp4"}).status_code == 400
    assert client.post("/streams", json={"name": "x", "source_type": "rtsp", "uri": "nope"}).status_code == 400
    assert client.post("/streams", json={"name": "x", "source_type": "bogus"}).status_code == 422
    assert client.get("/streams/9999").status_code == 404
    assert client.post("/streams/9999/start").status_code == 404
    assert client.delete("/streams/9999").status_code == 404


def test_full_pipeline_through_api(client, sample_video):
    r = client.post("/streams", json={"name": "demo", "source_type": "file", "uri": sample_video.name})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["status"] == "created"

    with client.websocket_connect(f"/ws?stream_id={sid}") as ws:
        assert ws.receive_json()["type"] == "hello"
        assert client.post(f"/streams/{sid}/start").status_code == 200
        types = set()
        for _ in range(400):
            types.add(ws.receive_json()["type"])
            if {"stream_status", "detections", "analytics", "event"} <= types:
                break
        assert {"stream_status", "detections", "analytics", "event"} <= types

    assert _wait_status(client, sid, {"completed", "error", "stopped"}) == "completed"

    events = client.get("/events", params={"stream_id": sid, "limit": 1000}).json()
    kinds = {e["type"] for e in events}
    assert {"LINE_CROSSED", "PERSON_ENTERED_ZONE", "PERSON_EXITED_ZONE", "CROWD_THRESHOLD_EXCEEDED"} <= kinds
    assert all(e["stream_id"] == sid for e in events)
    only = client.get("/events", params={"stream_id": sid, "type": "LINE_CROSSED"}).json()
    assert only and {e["type"] for e in only} == {"LINE_CROSSED"}

    a = client.get(f"/streams/{sid}/analytics").json()
    assert a["source"] == "live" and a["health"]["frames_processed"] > 50
    lines = a["cumulative"]["line_counts"]["entrance"]
    assert lines["in"] > 0 and lines["out"] > 0
    assert a["cumulative"]["unique_objects"]["person"] >= 8

    m = client.get(f"/streams/{sid}/metrics").json()
    assert m["live"]["dropped_frames"] == 0 and len(m["history"]) >= 1
    assert client.get(f"/streams/{sid}/frame.jpg").headers["content-type"] == "image/jpeg"
    assert client.get("/health").json()["streams"]["total"] >= 1

    assert client.delete(f"/streams/{sid}").status_code == 204
    assert client.get(f"/streams/{sid}").status_code == 404
    assert client.get("/events", params={"stream_id": sid}).json() == []


def test_stop_midway_and_restart_keeps_track_ids_unique(client, sample_video, monkeypatch):
    # real-time pacing so the stream is still running when we stop it
    import app.streams.manager as mgr_mod
    from dataclasses import replace

    mgr = client.app.state.manager
    mgr.settings = replace(mgr.settings, file_playback_speed=1.0)
    sid = client.post("/streams", json={"name": "rt", "source_type": "file", "uri": sample_video.name,
                                        "autostart": True}).json()["id"]
    _wait_status(client, sid, {"running"})
    time.sleep(2.0)
    assert client.post(f"/streams/{sid}/stop").json()["status"] in ("stopped", "running")
    assert _wait_status(client, sid, {"stopped"}) == "stopped"
    # restart must not violate the (stream_id, track_id) unique constraint
    client.post(f"/streams/{sid}/start")
    _wait_status(client, sid, {"running"})
    time.sleep(1.5)
    client.post(f"/streams/{sid}/stop")
    assert _wait_status(client, sid, {"stopped"}) == "stopped"
    assert client.get(f"/streams/{sid}").json()["last_error"] is None
    client.delete(f"/streams/{sid}")
