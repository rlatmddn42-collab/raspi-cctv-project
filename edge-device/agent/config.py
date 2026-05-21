"""Edge agent configuration.

Override via environment variables — useful when running on the Pi vs. dev VM.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    server_url: str
    device_id: str
    api_key: str
    heartbeat_interval_sec: int


def load() -> Config:
    return Config(
        server_url=os.environ.get("CCTV_SERVER_URL", "http://localhost:9000"),
        device_id=os.environ.get("CCTV_DEVICE_ID", "rpi-001"),
        api_key=os.environ.get("CCTV_API_KEY", "dev-key-rpi-001"),
        heartbeat_interval_sec=int(os.environ.get("CCTV_HEARTBEAT_SEC", "30")),
    )
