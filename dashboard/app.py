"""Streamlit dashboard. Polls the REST API (the WebSocket feed is for programmatic clients)."""
from __future__ import annotations

import os
import time

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(page_title="Video Analytics", layout="wide")


def api(method: str, path: str, **kw):
    try:
        r = requests.request(method, f"{API_URL}{path}", timeout=5, **kw)
        r.raise_for_status()
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r.content
    except requests.HTTPError as exc:
        st.sidebar.error(f"{exc.response.status_code}: {exc.response.text[:200]}")
    except requests.RequestException as exc:
        st.error(f"API unreachable at {API_URL}: {exc}")
    return None


# ------------------------------------------------------------------ sidebar
st.sidebar.title("Controls")
auto = st.sidebar.toggle("Auto-refresh", value=True)
interval = st.sidebar.slider("Refresh interval (s)", 0.5, 5.0, 1.0, 0.5)

with st.sidebar.expander("Add stream"):
    name = st.text_input("Name", "My stream")
    stype = st.selectbox("Source type", ["file", "webcam", "rtsp"])
    uri = st.text_input("URI", "sample_videos/lobby_demo.mp4" if stype == "file" else ("0" if stype == "webcam" else "rtsp://"))
    if st.button("Create & start"):
        created = api("POST", "/streams", json={"name": name, "source_type": stype, "uri": uri, "autostart": True})
        if created:
            st.success(f"Stream {created['id']} created")

streams = api("GET", "/streams") or []
st.title("Real-Time Video Analytics")
if not streams:
    st.info("No streams yet. Add one in the sidebar, or start the API with AUTOSTART_SAMPLE=true.")
    st.stop()

# ----------------------------------------------------------- stream health
st.subheader("Streams")
rows = []
for s in streams:
    h = s.get("health") or {}
    rows.append({"id": s["id"], "name": s["name"], "type": s["source_type"], "status": s["status"],
                 "processing fps": h.get("processing_fps"), "input fps": h.get("input_fps"),
                 "inference ms": h.get("inference_ms_avg"), "pipeline ms (avg)": h.get("pipeline_ms_avg"),
                 "pipeline ms (p95)": h.get("pipeline_ms_p95"), "queue": h.get("queue_size"),
                 "dropped": h.get("dropped_frames"), "last frame": h.get("last_frame_timestamp")})
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

active = [s for s in streams if s["status"] in ("running", "reconnecting", "starting")]
c1, c2, c3 = st.columns(3)
c1.metric("Active streams", len(active))
c2.metric("Total streams", len(streams))

selected = st.selectbox("Stream", streams, format_func=lambda s: f"#{s['id']} {s['name']} ({s['status']})")
sid = selected["id"]

b1, b2, b3, _ = st.columns([1, 1, 1, 5])
if b1.button("Start"):
    api("POST", f"/streams/{sid}/start")
if b2.button("Stop"):
    api("POST", f"/streams/{sid}/stop")
if b3.button("Delete"):
    api("DELETE", f"/streams/{sid}")
    st.rerun()

data = api("GET", f"/streams/{sid}/analytics") or {}
cur = data.get("current") or {}
health = data.get("health") or {}
c3.metric("People now", cur.get("people_count", "–"))

left, right = st.columns([3, 2])
with left:
    frame = api("GET", f"/streams/{sid}/frame.jpg")
    if isinstance(frame, bytes):
        st.image(frame, caption="Latest annotated frame", use_container_width=True)
    else:
        st.caption("No frame yet (start the stream).")
with right:
    m1, m2 = st.columns(2)
    m1.metric("Processing FPS", health.get("processing_fps", "–"))
    m2.metric("Pipeline latency (ms)", health.get("pipeline_ms_avg", "–"))
    m1.metric("Inference (ms)", health.get("inference_ms_avg", "–"))
    m2.metric("Dropped frames", health.get("dropped_frames", "–"))
    st.markdown("**Object counts (now)**")
    counts = cur.get("object_counts") or {}
    if counts:
        st.bar_chart(pd.Series(counts, name="count"))
    else:
        st.caption("none")
    st.markdown("**Zone occupancy**")
    st.json(cur.get("zone_occupancy") or {})
    st.markdown("**Line crossings (cumulative)**")
    st.json((data.get("cumulative") or {}).get("line_counts") or {})

st.markdown("**Current detections**")
objs = data.get("objects") or []
if objs:
    st.dataframe(pd.DataFrame([{"track": o["track_id"], "class": o["class"], "conf": o["confidence"], **o["bbox"]}
                               for o in objs]), hide_index=True, use_container_width=True)
else:
    st.caption("none")

st.subheader("Recent events")
events = api("GET", f"/events?stream_id={sid}&limit=50") or []
if events:
    st.dataframe(pd.DataFrame([{"time": e["timestamp"], "type": e["type"], "track": e["track_id"],
                                "class": e["class"], "zone": e["zone"], "line": e["line"],
                                "details": e["payload"]} for e in events]),
                 hide_index=True, use_container_width=True)
else:
    st.caption("No events yet.")

if auto:
    time.sleep(interval)
    st.rerun()
