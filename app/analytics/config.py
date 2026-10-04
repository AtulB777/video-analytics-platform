"""Analytics profiles: counting lines and zones, loaded from JSON."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.core.config import Settings

log = logging.getLogger(__name__)
Point = tuple[float, float]


@dataclass
class LineConfig:
    name: str
    p1: Point
    p2: Point


@dataclass
class ZoneConfig:
    name: str
    polygon: list[Point]


@dataclass
class AnalyticsConfig:
    lines: list[LineConfig] = field(default_factory=list)
    zones: list[ZoneConfig] = field(default_factory=list)
    crowd_threshold: int = 5
    normalized: bool = True  # coordinates are 0..1 fractions of the frame
    crowd_hysteresis: int = 1
    exit_grace_s: float = 1.0

    def resolve(self, width: int, height: int) -> "AnalyticsConfig":
        """Return a copy with absolute pixel coordinates."""
        if not self.normalized:
            return self

        def sc(p: Point) -> Point:
            return (p[0] * width, p[1] * height)

        return replace(
            self,
            normalized=False,
            lines=[LineConfig(l.name, sc(l.p1), sc(l.p2)) for l in self.lines],
            zones=[ZoneConfig(z.name, [sc(p) for p in z.polygon]) for z in self.zones],
        )


def _parse_profile(raw: dict, crowd_override: int | None) -> AnalyticsConfig:
    cfg = AnalyticsConfig(
        lines=[LineConfig(l["name"], tuple(l["p1"]), tuple(l["p2"])) for l in raw.get("lines", [])],
        zones=[ZoneConfig(z["name"], [tuple(p) for p in z["polygon"]]) for z in raw.get("zones", [])],
        crowd_threshold=int(raw.get("crowd_threshold", 5)),
        normalized=bool(raw.get("normalized", True)),
        crowd_hysteresis=int(raw.get("crowd_hysteresis", 1)),
        exit_grace_s=float(raw.get("exit_grace_s", 1.0)),
    )
    if crowd_override is not None:
        cfg.crowd_threshold = crowd_override
    return cfg


def load_profiles(settings: Settings) -> dict[str, AnalyticsConfig]:
    """Load profiles from ZONES_JSON (inline) or ZONES_CONFIG (file). Always has 'default'."""
    raw: dict = {}
    if settings.zones_json.strip():
        raw = json.loads(settings.zones_json)
    else:
        path = Path(settings.zones_config_path)
        if path.is_file():
            raw = json.loads(path.read_text())
        else:
            log.warning("Zones config %s not found; using an empty default profile", path)
    profiles = {name: _parse_profile(p, settings.crowd_threshold) for name, p in raw.items()}
    profiles.setdefault("default", _parse_profile({}, settings.crowd_threshold))
    return profiles
