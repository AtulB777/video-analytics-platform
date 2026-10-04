"""Event engine: turns analytics snapshots into discrete, stateful events."""
from __future__ import annotations

from app.analytics.engine import AnalyticsSnapshot
from app.core.schemas import Event, EventType


class EventEngine:
    """Detects state transitions between consecutive snapshots.

    * LINE_CROSSED: one event per crossing reported by analytics.
    * PERSON_ENTERED_ZONE / PERSON_EXITED_ZONE: membership diff per zone. A person
      who is merely not detected for a moment is kept "inside" for ``exit_grace_s``
      so tracker flicker does not create enter/exit pairs.
    * CROWD_THRESHOLD_EXCEEDED: people > threshold for ``debounce_frames`` frames
      in a row; CROWD_THRESHOLD_CLEARED once people <= threshold - hysteresis.
    """

    def __init__(self, stream_id: int, crowd_threshold: int, hysteresis: int = 1,
                 debounce_frames: int = 3, exit_grace_s: float = 1.0):
        self.stream_id = stream_id
        self.crowd_threshold = crowd_threshold
        self.hysteresis = hysteresis
        self.debounce_frames = debounce_frames
        self.exit_grace_s = exit_grace_s
        self._zones: dict[str, dict[int, float]] = {}  # zone -> {track_id: last_inside_epoch}
        self._crowd_active = False
        self._streak = 0

    def process(self, snap: AnalyticsSnapshot) -> list[Event]:
        events: list[Event] = []
        ts = snap.timestamp
        now = ts.timestamp()

        for c in snap.new_crossings:
            events.append(Event(
                type=EventType.LINE_CROSSED, stream_id=self.stream_id, timestamp=ts,
                track_id=c.track_id, cls=c.cls, line=c.line,
                payload={"direction": c.direction, "line_counts": snap.line_counts.get(c.line, {})},
            ))

        for zone, ids in snap.zone_occupancy.items():
            state = self._zones.setdefault(zone, {})
            inside = set(ids)
            for tid in inside:
                if tid not in state:
                    events.append(Event(
                        type=EventType.PERSON_ENTERED_ZONE, stream_id=self.stream_id, timestamp=ts,
                        track_id=tid, cls="person", zone=zone, payload={"occupancy": len(inside)},
                    ))
                state[tid] = now
            for tid in list(state):
                if tid in inside:
                    continue
                visible_outside = tid in snap.visible_track_ids
                if visible_outside or now - state[tid] > self.exit_grace_s:
                    del state[tid]
                    events.append(Event(
                        type=EventType.PERSON_EXITED_ZONE, stream_id=self.stream_id, timestamp=ts,
                        track_id=tid, cls="person", zone=zone, payload={"occupancy": len(inside)},
                    ))

        count = snap.people_count
        if not self._crowd_active:
            self._streak = self._streak + 1 if count > self.crowd_threshold else 0
            if self._streak >= self.debounce_frames:
                self._crowd_active = True
                events.append(Event(
                    type=EventType.CROWD_THRESHOLD_EXCEEDED, stream_id=self.stream_id, timestamp=ts,
                    payload={"people_count": count, "threshold": self.crowd_threshold},
                ))
        elif count <= self.crowd_threshold - self.hysteresis:
            self._crowd_active = False
            self._streak = 0
            events.append(Event(
                type=EventType.CROWD_THRESHOLD_CLEARED, stream_id=self.stream_id, timestamp=ts,
                payload={"people_count": count, "threshold": self.crowd_threshold},
            ))
        return events
