"""Pydantic models for the protocol payloads (COMMUNICATION_PROTOCOL.md §4)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Heartbeat ---------------------------------------------------------------

class SystemInfo(BaseModel):
    cpu_percent: float
    mem_percent: float
    temp_celsius: float
    uptime_seconds: int


class CameraInfo(BaseModel):
    connected: bool
    fps: float


class InferenceInfo(BaseModel):
    model_version: str
    avg_latency_ms: int


class HeartbeatIn(BaseModel):
    timestamp: str
    status: str
    system: SystemInfo
    camera: CameraInfo
    inference: InferenceInfo


# --- Detection ---------------------------------------------------------------

class DetectedObject(BaseModel):
    # `class` is a Python keyword; expose as `class_` but accept/emit "class".
    model_config = ConfigDict(populate_by_name=True)

    class_: str = Field(alias="class")
    confidence: float
    bbox: List[int]


class OcrResult(BaseModel):
    text: str
    confidence: float
    bbox: List[int]


class Detection(BaseModel):
    timestamp: str
    frame_id: str
    objects: List[DetectedObject] = []
    ocr: List[OcrResult] = []
    snapshot_ref: Optional[str] = None


class DetectionsIn(BaseModel):
    detections: List[Detection]


# --- Event -------------------------------------------------------------------

class EventIn(BaseModel):
    timestamp: str
    event_type: str
    severity: Literal["info", "warning", "critical"]
    message: str
    related_detection_id: Optional[str] = None
    snapshot_ref: Optional[str] = None


# --- Responses ---------------------------------------------------------------

class OkResponse(BaseModel):
    ok: bool = True
    received_at: Optional[str] = None


class AcceptedResponse(BaseModel):
    ok: bool = True
    accepted: int


class SnapshotResponse(BaseModel):
    ok: bool = True
    snapshot_id: str
    url: str


class DeviceListItem(BaseModel):
    device_id: str
    last_seen: Optional[str] = None
    status: Optional[str] = None
    location: Optional[str] = None


class DeviceListResponse(BaseModel):
    devices: List[DeviceListItem]
