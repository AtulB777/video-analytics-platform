"""Synthetic sample video so the project runs with zero external assets.

Rectangles stand in for pedestrians ("tall") and vehicles ("wide") moving over
a static background. The scenario is scripted so every analytic fires:

* people walking left->right and right->left across the vertical entrance line
* one person who stops inside the zone
* a group of six people (crowd) from ~t=17s
* two vehicles

Run:  python -m app.streams.sample [output.mp4]
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

W, H, FPS, DURATION = 640, 360, 20, 28
PERSON = (28, 56)
CAR = (70, 34)
PERSON_LANES = [10, 70, 130, 190, 250]
CAR_LANE = 318


def _walk(start: float, dur: float, lane: int, ltr: bool, size=PERSON, color=(40, 70, 200)):
    w = size[0]
    xs = (-w, W) if ltr else (W, -w)
    return {"keys": [(start, xs[0]), (start + dur, xs[1])], "y": lane, "size": size, "color": color}


def _scenario():
    objs = [
        _walk(0, 9, 10, True, color=(30, 60, 190)),
        _walk(2, 9, 250, False, color=(20, 140, 60)),
        _walk(4, 10, 70, True, color=(160, 40, 120)),
        _walk(6, 8, 190, False, color=(200, 120, 20)),
        _walk(3, 8, CAR_LANE, False, size=CAR, color=(170, 60, 60)),
        _walk(16, 8, CAR_LANE, False, size=CAR, color=(60, 60, 170)),
    ]
    # lingerer: walks into the zone, pauses, leaves
    objs.append({"keys": [(1, -PERSON[0]), (5, 450), (8, 450), (12, W)], "y": 130, "size": PERSON, "color": (20, 160, 160)})
    # crowd of six, all visible together roughly t=17..24
    palette = [(30, 60, 190), (20, 140, 60), (160, 40, 120), (200, 120, 20), (20, 160, 160), (110, 50, 200)]
    for i in range(6):
        objs.append(_walk(15 + 0.4 * i, 10, PERSON_LANES[i % 5], True, color=palette[i]))
    return objs


def _x_at(keys, t):
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, x0), (t1, x1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            return x0 + (x1 - x0) * (t - t0) / (t1 - t0) if t1 > t0 else x1
    return keys[-1][1]


def generate_sample_video(path: str | Path, fps: int = FPS, duration: int = DURATION) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    ys, xs = np.mgrid[0:H, 0:W]
    background = (105 + 25 * (ys / H)).astype(np.float32)[..., None].repeat(3, axis=2)
    background += rng.normal(0, 1.5, (H, W, 1)).astype(np.float32)  # fixed sensor-like texture
    background = np.clip(background, 0, 255).astype(np.uint8)

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open a VideoWriter for mp4v")
    objs = _scenario()
    for n in range(fps * duration):
        t = n / fps
        frame = background.copy()
        for o in objs:
            x = int(round(_x_at(o["keys"], t)))
            w, h = o["size"]
            if x + w <= 0 or x >= W:
                continue
            x1, x2 = max(0, x), min(W, x + w)
            cv2.rectangle(frame, (x1, o["y"]), (x2 - 1, o["y"] + h - 1), o["color"], -1)
        writer.write(frame)
    writer.release()
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "sample_videos/lobby_demo.mp4"
    print(f"wrote {generate_sample_video(out)}")
