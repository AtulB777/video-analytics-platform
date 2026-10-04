from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class StreamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: Literal["file", "webcam", "rtsp"]
    uri: Optional[str] = Field(default=None, description="File path (inside VIDEO_DIR), webcam index, or rtsp:// URL")
    profile: str = "default"
    camera_name: Optional[str] = None
    location: Optional[str] = None
    autostart: bool = False


class StreamOut(BaseModel):
    id: int
    camera_id: int
    name: str
    source_type: str
    uri: Optional[str]
    profile: str
    status: str
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    health: Optional[dict[str, Any]] = None
