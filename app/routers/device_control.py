"""POST /v1/device/results — the phone's report-back channel for device control relay.

The Android relay (assistant-android phase 11) executes a
`read_notifications` / `control_media` FCM data push from app/tools/device_control.py
and reports the outcome here. Bearer-gated like every other router; the backend
never calls the phone directly.

Body (read_notifications):
    {"request_id": "...", "ok": true}
    {"request_id": "...", "ok": false, "error": "reason"}
    {"request_id": "...", "ok": true, "notifications": [
        {"package": "...", "tag": "...", "title": "...", "text": "...", "received_at": "iso-8601"}
    ]}

Body (control_media):
    {"request_id": "...", "ok": true}
    {"request_id": "...", "ok": false, "error": "reason"}
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..auth import require_bearer_token

router = APIRouter()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class DeviceResultNotification(BaseModel):
    package: str
    tag: str | None = None
    title: str | None = None
    text: str | None = None
    received_at: str


class DeviceResultMessage(BaseModel):
    from_number: str | None = None
    message: str | None = None


class DeviceResultRequest(BaseModel):
    request_id: str
    ok: bool
    error: str | None = None
    notifications: list[DeviceResultNotification] | None = None
    messages: list[DeviceResultMessage] | None = None


class DeviceResultResponse(BaseModel):
    ok: bool


@router.post(
    "/v1/device/results",
    response_model=DeviceResultResponse,
    dependencies=[Depends(require_bearer_token)],
)
async def report_device_result(req: DeviceResultRequest) -> DeviceResultResponse:
    """Record the outcome of a relayed device control request.

    Supports two action types from POST /v1/device/results:
    - read_notifications: reports notification list with package, title, text
    - control_media: simple ok/failed report
    """
    conn = db.get_connection()
    async with conn.execute(
        "SELECT id, action, status FROM sms_relay WHERE id = ?", (req.request_id,)
    ) as cursor:
        existing = await cursor.fetchone()

    if existing is None:
        raise HTTPException(status_code=404, detail="Unknown request_id")

    action = existing[1]
    now = _now_iso()
    if req.ok:
        await conn.execute(
            "UPDATE sms_relay SET status = 'delivered', updated_at = ? WHERE id = ?",
            (now, req.request_id),
        )
        if action == "read_notifications" and req.notifications:
            await conn.executemany(
                "INSERT INTO sms_relay_messages "
                "(request_id, from_number, message, received_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (req.request_id, n.package, n.text, n.received_at)
                    for n in req.notifications
                ],
            )
        elif action == "control_media":
            # For control_media we just mark delivered; no message storage needed
            pass
    else:
        await conn.execute(
            "UPDATE sms_relay SET status = 'failed', error = ?, updated_at = ? "
            "WHERE id = ?",
            (req.error or "phone reported failure", now, req.request_id),
        )
    await conn.commit()
    return DeviceResultResponse(ok=True)