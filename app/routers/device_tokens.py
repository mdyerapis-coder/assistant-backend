"""POST /v1/device-tokens — register FCM device tokens for push notifications.

The Android app calls this on startup (and when the token refreshes) to
register its FCM token with the backend. The scheduler (app/scheduler.py)
uses these tokens to deliver reminder push notifications.
"""

import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db
from ..auth import require_bearer_token

router = APIRouter()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class DeviceTokenRequest(BaseModel):
    token: str
    device_id: str | None = None


class DeviceTokenResponse(BaseModel):
    ok: bool
    message: str


@router.post(
    "/v1/device-tokens",
    response_model=DeviceTokenResponse,
    dependencies=[Depends(require_bearer_token)],
)
async def register_device_token(req: DeviceTokenRequest) -> DeviceTokenResponse:
    """Register an FCM device token for push notifications."""
    conn = db.get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO device_tokens (token, device_id, created_at) "
        "VALUES (?, ?, ?)",
        (req.token, req.device_id, _now_iso()),
    )
    await conn.commit()
    return DeviceTokenResponse(ok=True, message="Device token registered")
