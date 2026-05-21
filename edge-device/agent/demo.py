"""Send one of each protocol message to the central server.

Useful for smoke-testing the server during dev. Run from the repo root:

    python edge-device/agent/demo.py
"""

import sys
from pathlib import Path

# `edge-device` has a hyphen, so it isn't an importable package. Put its
# parent on sys.path so `from agent import ...` works when this is run
# directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import client  # noqa: E402
from agent.config import load  # noqa: E402


def main() -> None:
    cfg = load()
    c = client.EdgeClient(cfg)
    print(f"server: {cfg.server_url}  device: {cfg.device_id}")

    hb = c.heartbeat(
        system={"cpu_percent": 23.4, "mem_percent": 41.2, "temp_celsius": 52.1, "uptime_seconds": 86400},
        camera={"connected": True, "fps": 15.0},
        inference={"model_version": "yolov8n-smoke-v1", "avg_latency_ms": 87},
    )
    print("heartbeat ->", hb)

    det = c.detections([{
        "timestamp": client.now_iso(),
        "frame_id": "f_demo_0001",
        "objects": [
            {"class": "smoke", "confidence": 0.87, "bbox": [120, 80, 340, 290]},
            {"class": "vehicle", "confidence": 0.92, "bbox": [50, 200, 220, 380]},
        ],
        "ocr": [{"text": "12가3456", "confidence": 0.95, "bbox": [60, 320, 200, 360]}],
        "snapshot_ref": None,
    }])
    print("detections ->", det)

    ev = c.event(
        event_type="smoke_detected",
        severity="warning",
        message="Smoke detected with confidence 0.87",
        related_detection_id="f_demo_0001",
    )
    print("event ->", ev)


if __name__ == "__main__":
    main()
