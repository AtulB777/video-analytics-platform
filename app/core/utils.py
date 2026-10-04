from __future__ import annotations

import re

_CRED = re.compile(r"(://)([^/@\s]+)@")


def mask_uri(uri: str | None) -> str | None:
    """Hide credentials in URIs such as rtsp://user:pass@host/stream."""
    if not uri:
        return uri
    return _CRED.sub(r"\1***@", uri)
