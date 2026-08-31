"""send_sms / read_sms / get_sms_result — SMS relay tools (Phase 06).

The backend has no SMS gateway: messages are relayed through the
connected Android phone. A tool call enqueues a relay request and pushes
an FCM data message (`action: send_sms|read_sms`) to the phone; the phone
executes via the Android SMS APIs and reports the outcome to
`POST /v1/sms/results` (see app/routers/sms.py). The model then calls
`get_sms_result(request_id)` to learn whether the send succeeded or to
read the messages the phone returned.

These tools are registered with `always_visible=False`: they only enter
the request's tool schema after `use_skill("sms")` activates them, per
ADR-009 progressive disclosure. The skill file is `skills/sms.md`.
"""

from __future__ import annotations

import datetime
import json
import uuid

from .. import db, fcm
from .registry import ToolSpec, register


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _device_tokens() -> list[str]:
    conn = db.get_connection()
    async with conn.execute(
        "SELECT token FROM device_tokens ORDER BY created_at DESC"
    ) as cursor:
        return [row[0] for row in await cursor.fetchall()]


async def _dispatch(action: str, payload: dict[str, str]) -> str:
    """Push a relay request to the registered phone and track it."""
    tokens = await _device_tokens()
    if not tokens:
        return (
            "No phone is registered for SMS relay. Ask the user to open the "
            "Assistant app on their phone and confirm notifications are "
            "enabled, then retry."
        )

    request_id = str(uuid.uuid4())
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO sms_relay (id, action, phone, message, limit_count, "
        "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'dispatched', ?, ?)",
        (
            request_id,
            action,
            payload.get("phone"),
            payload.get("message"),
            payload.get("limit"),
            _now_iso(),
            _now_iso(),
        ),
    )
    await conn.commit()

    data = {"action": action, "request_id": request_id, **payload}
    await fcm.send_notification(
        tokens,
        title="Assistant SMS",
        body="SMS relay request",
        data=data,
    )
    return (
        f"Dispatched SMS {action} request {request_id} to the phone. "
        "Call get_sms_result with that request id to check the outcome."
    )


async def _send_sms(phone: str, message: str) -> str:
    if not phone or not message:
        return "send_sms requires both 'phone' and 'message'."
    return await _dispatch("send_sms", {"phone": phone, "message": message})


async def _read_sms(phone: str | None = None, limit: int = 10) -> str:
    if limit < 1 or limit > 100:
        return "read_sms 'limit' must be between 1 and 100."
    payload: dict[str, str] = {"limit": str(limit)}
    if phone:
        payload["phone"] = phone
    return await _dispatch("read_sms", payload)


async def _get_sms_result(request_id: str) -> str:
    conn = db.get_connection()
    async with conn.execute(
        "SELECT action, status, error, updated_at FROM sms_relay WHERE id = ?",
        (request_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return f"No SMS relay request with id {request_id}."

    action, status, error, updated_at = row
    if action == "read_sms" and status == "delivered":
        async with conn.execute(
            "SELECT from_number, message, received_at FROM sms_relay_messages "
            "WHERE request_id = ? ORDER BY received_at DESC",
            (request_id,),
        ) as msg_cursor:
            rows = await msg_cursor.fetchall()
        if rows:
            payload = [
                {
                    "from": m[0],
                    "message": m[1],
                    "received_at": m[2],
                }
                for m in rows
            ]
            return json.dumps(payload)
        return f"Read request {request_id} delivered but returned no messages."

    if status == "failed":
        return f"SMS request {request_id} failed: {error or 'unknown error'}"
    if status == "delivered":
        return f"SMS request {request_id} delivered to the phone."
    return f"SMS request {request_id} still in flight (status={status}, updated {updated_at})."


register(
    ToolSpec(
        name="send_sms",
        description=(
            "Send an SMS via the user's connected phone. The phone must have "
            "the Assistant app installed with notifications enabled. Call "
            "get_sms_result with the returned request id to confirm delivery."
        ),
        parameters={
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "Recipient phone number in international format, e.g. +61412345678.",
                },
                "message": {
                    "type": "string",
                    "description": "SMS body text.",
                },
            },
            "required": ["phone", "message"],
        },
        fn=_send_sms,
        always_visible=False,
    )
)

register(
    ToolSpec(
        name="read_sms",
        description=(
            "Read recent SMS messages from the user's connected phone. "
            "Returns a request id; call get_sms_result with it after the "
            "phone reports back."
        ),
        parameters={
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "Optional filter: only messages from this number.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (1-100, default 10).",
                },
            },
            "required": [],
        },
        fn=_read_sms,
        always_visible=False,
    )
)

register(
    ToolSpec(
        name="get_sms_result",
        description=(
            "Check the outcome of a send_sms or read_sms relay request "
            "given its request id. For read_sms, returns the messages once "
            "the phone has reported them; otherwise reports delivered, "
            "failed, or still in flight."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The request id returned by send_sms or read_sms.",
                },
            },
            "required": ["request_id"],
        },
        fn=_get_sms_result,
        always_visible=False,
    )
)
