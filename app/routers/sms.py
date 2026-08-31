"""POST /v1/sms/results — the phone's report-back channel for SMS relay.

The Android relay (assistant-android phase 10) executes a `send_sms` /
`read_sms` FCM data push from app/tools/sms.py and reports the outcome
here. Bearer-gated like every other router; the backend never calls the
phone directly.

Body:
    {"request_id": "...", "ok": true}
    {"request_id": "...", "ok": false, "error": "reason"}
    {"request_id": "...", "ok": true, "messages": [
        {"from_number": "+614...", "message": "...", "received_at": "iso-8601"}
    ]}
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


class SmsResultMessage(BaseModel):
    from_number: str
    message: str
    received_at: str


class SmsResultRequest(BaseModel):
    request_id: str
    ok: bool
    error: str | None = None
    messages: list[SmsResultMessage] | None = None


class SmsResultResponse(BaseModel):
    ok: bool


@router.post(
    "/v1/sms/results",
    response_model=SmsResultResponse,
    dependencies=[Depends(require_bearer_token)],
)
async def report_sms_result(req: SmsResultRequest) -> SmsResultResponse:
    """Record the outcome of a relayed SMS request."""
    conn = db.get_connection()
    async with conn.execute(
        "SELECT id, status FROM sms_relay WHERE id = ?", (req.request_id,)
    ) as cursor:
        existing = await cursor.fetchone()

    if existing is None:
        raise HTTPException(status_code=404, detail="Unknown request_id")

    now = _now_iso()
    if req.ok:
        await conn.execute(
            "UPDATE sms_relay SET status = 'delivered', updated_at = ? WHERE id = ?",
            (now, req.request_id),
        )
        if req.messages:
            await conn.executemany(
                "INSERT INTO sms_relay_messages "
                "(request_id, from_number, message, received_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (req.request_id, m.from_number, m.message, m.received_at)
                    for m in req.messages
                ],
            )
    else:
        await conn.execute(
            "UPDATE sms_relay SET status = 'failed', error = ?, updated_at = ? "
            "WHERE id = ?",
            (req.error or "phone reported failure", now, req.request_id),
        )
    await conn.commit()
    return SmsResultResponse(ok=True)
