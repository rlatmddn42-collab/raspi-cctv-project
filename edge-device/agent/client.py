"""HTTP client wrapping the edge → server endpoints (COMMUNICATION_PROTOCOL.md §4).

This is the only module that knows the wire format. Higher layers (the
inference loop, snapshot uploader, etc.) call these methods and receive the
already-parsed response dict.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from .config import Config


def now_iso() -> str:
    """Returns current time as ISO 8601 UTC (e.g. 2026-05-21T10:30:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProtocolError(RuntimeError):
    """Server replied with the standard error envelope (§5)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"[{status} {code}] {message}")
        self.status = status
        self.code = code
        self.message = message


class EdgeClient:
    def __init__(self, cfg: Config, timeout_sec: float = 5.0):
        self._cfg = cfg
        self._timeout = timeout_sec
        self._session = requests.Session()
        self._session.headers.update({"X-Device-Api-Key": cfg.api_key})

    # --- internal helpers ---------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._cfg.server_url.rstrip('/')}{path}"

    def _device_path(self, suffix: str) -> str:
        return f"/api/devices/{self._cfg.device_id}{suffix}"

    def _post_json(self, path: str, payload: dict) -> dict:
        r = self._session.post(self._url(path), json=payload, timeout=self._timeout)
        return self._unwrap(r)

    @staticmethod
    def _unwrap(r: requests.Response) -> dict:
        try:
            body = r.json()
        except ValueError:
            r.raise_for_status()
            return {}
        if not r.ok or (isinstance(body, dict) and body.get("ok") is False):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise ProtocolError(
                status=r.status_code,
                code=err.get("code", "server_error"),
                message=err.get("message", r.text),
            )
        return body

    # --- protocol calls -----------------------------------------------------

    def heartbeat(
        self,
        *,
        status: str = "ok",
        system: dict,
        camera: dict,
        inference: dict,
        timestamp: Optional[str] = None,
    ) -> dict:
        return self._post_json(self._device_path("/heartbeat"), {
            "timestamp": timestamp or now_iso(),
            "status": status,
            "system": system,
            "camera": camera,
            "inference": inference,
        })

    def detections(self, detections: list[dict]) -> dict:
        return self._post_json(self._device_path("/detections"), {"detections": detections})

    def event(
        self,
        *,
        event_type: str,
        severity: str,
        message: str,
        related_detection_id: Optional[str] = None,
        snapshot_ref: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> dict:
        return self._post_json(self._device_path("/events"), {
            "timestamp": timestamp or now_iso(),
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "related_detection_id": related_detection_id,
            "snapshot_ref": snapshot_ref,
        })

    def snapshot(self, image_bytes: bytes, frame_id: str, *,
                 filename: str = "snapshot.jpg",
                 content_type: str = "image/jpeg") -> dict:
        metadata = {"timestamp": now_iso(), "frame_id": frame_id}
        files = {"file": (filename, image_bytes, content_type)}
        data = {"metadata": json.dumps(metadata)}
        r = self._session.post(
            self._url(self._device_path("/snapshots")),
            files=files,
            data=data,
            timeout=self._timeout,
        )
        return self._unwrap(r)
