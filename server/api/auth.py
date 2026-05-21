"""X-Device-Api-Key validation (COMMUNICATION_PROTOCOL.md §1.3)."""

from typing import Optional

from fastapi import HTTPException

from . import storage


def require_api_key(device_id: str, provided: Optional[str]) -> None:
    if not storage.device_exists(device_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "device_not_found", "message": f"device {device_id} not found"},
        )
    expected = storage.get_api_key(device_id)
    if not provided or provided != expected:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_api_key", "message": "API key is missing or invalid"},
        )
