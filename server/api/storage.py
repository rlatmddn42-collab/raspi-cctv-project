"""In-memory storage for the v0.1 server.

Everything resets on restart. Replace with a real DB later.
"""

from typing import List, Optional


# device_id -> { api_key, location }
# Seed one dev device so curl/the edge client can start posting immediately.
_devices: dict = {
    "rpi-001": {"api_key": "dev-key-rpi-001", "location": "정문 CCTV"},
}

# device_id -> { last_seen, status, heartbeat }
_device_state: dict = {}

# device_id -> [detection, ...]
_detections: dict = {}

# device_id -> [event, ...]
_events: dict = {}

# snapshot_id -> { device_id, data, content_type, metadata }
_snapshots: dict = {}


# --- Devices / auth ----------------------------------------------------------

def device_exists(device_id: str) -> bool:
    return device_id in _devices


def get_api_key(device_id: str) -> Optional[str]:
    d = _devices.get(device_id)
    return d["api_key"] if d else None


def register_device(device_id: str, api_key: str, location: Optional[str] = None) -> None:
    _devices[device_id] = {"api_key": api_key, "location": location}


def list_devices() -> List[dict]:
    out = []
    for device_id, info in _devices.items():
        state = _device_state.get(device_id, {})
        hb = state.get("heartbeat") or {}
        out.append({
            "device_id": device_id,
            "last_seen": state.get("last_seen"),
            "status": state.get("status"),
            "location": info.get("location"),
            # Additive fields surfaced from the latest heartbeat (null until one
            # arrives). Existing consumers can ignore them; the protocol §4.5
            # shape is preserved.
            "fps": (hb.get("camera") or {}).get("fps"),
            "model_version": (hb.get("inference") or {}).get("model_version"),
        })
    return out


def get_device(device_id: str) -> Optional[dict]:
    if device_id not in _devices:
        return None
    info = _devices[device_id]
    state = _device_state.get(device_id, {})
    return {
        "device_id": device_id,
        "location": info.get("location"),
        "last_seen": state.get("last_seen"),
        "status": state.get("status"),
        "heartbeat": state.get("heartbeat"),
    }


# --- Writes ------------------------------------------------------------------

def record_heartbeat(device_id: str, hb: dict) -> None:
    _device_state[device_id] = {
        "last_seen": hb.get("timestamp"),
        "status": hb.get("status"),
        "heartbeat": hb,
    }


def append_detections(device_id: str, items: List[dict]) -> int:
    _detections.setdefault(device_id, []).extend(items)
    return len(items)


def append_event(device_id: str, ev: dict) -> None:
    _events.setdefault(device_id, []).append(ev)


def store_snapshot(
    device_id: str,
    snapshot_id: str,
    data: bytes,
    metadata: dict,
    content_type: str,
) -> None:
    _snapshots[snapshot_id] = {
        "device_id": device_id,
        "data": data,
        "content_type": content_type,
        "metadata": metadata,
    }


def get_snapshot(snapshot_id: str) -> Optional[dict]:
    return _snapshots.get(snapshot_id)


# --- Reads -------------------------------------------------------------------

def _in_range(ts: Optional[str], since: Optional[str], until: Optional[str]) -> bool:
    # ISO 8601 UTC strings sort lexicographically.
    if ts is None:
        return True
    if since and ts < since:
        return False
    if until and ts > until:
        return False
    return True


def query_detections(
    device_id: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
) -> List[dict]:
    items = _detections.get(device_id, [])
    filtered = [d for d in items if _in_range(d.get("timestamp"), since, until)]
    return filtered[-limit:]


def query_events(
    device_id: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
) -> List[dict]:
    items = _events.get(device_id, [])
    filtered = [e for e in items if _in_range(e.get("timestamp"), since, until)]
    return filtered[-limit:]
