"""device control tools — notifications + media relay through the user's connected Android phone.

Pattern: same FCM data push relay as sms.py. Tools are always_visible=False,
activated via use_skill("device_control") or the new "device" skill.
"""

from __future__ import annotations

import json
import uuid

from .. import db, fcm
from .registry import ToolSpec, register


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _device_tokens() -> list[str]:
    """Fetch registered FCM device tokens from the DB."""
    conn = db.get_connection()
    async with conn.execute("SELECT token FROM device_tokens") as cursor:
        return [row[0] for row in await cursor.fetchall()]


async def _dispatch(action: str, payload: dict[str, str]) -> str:
    """Push a relay request to the registered phone via FCM data payload and track it.

    Returns the request_id, or an error string.
    """
    request_id = str(uuid.uuid4())
    tokens = await _device_tokens()
    if not tokens:
        return f"device_control {action}: no registered phone — open the Assistant app " "on your phone and enable notifications, then retry."

    # Persist the relay request so we can match outcomes later
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO sms_relay (id, action, status, created_at) VALUES (?, ?, 'dispatched', ?)",
        (request_id, action, _now_iso()),
    )
    await conn.commit()

    # Send FCM data push to each registered token
    from .. import fcm as fcm_mod
    sent = 0
    for token in tokens:
        try:
            await fcm_mod.send_fcm_data(token, action, {"request_id": request_id, **payload})
            sent += 1
        except Exception as e:
            Log.e("device_control", f"FCM send failed for token {token[:10]}: {e}")

    if sent == 0:
        # Roll back the DB entry if nothing was sent
        await conn.execute(
            "DELETE FROM sms_relay WHERE id = ?", (request_id,)
        )
        await conn.commit()
        return f"device_control {action}: FCM send failed for all tokens."

    return request_id


async def _read_notifications(limit: int = 10) -> str:
    """Dispatch a read_notifications relay request.

    The phone's SmsRelayController (extended to handle NOTIFICATION_LISTENER)
    will query the notification inbox and report back via POST /v1/device/results.
    """
    if limit < 1 or limit > 100:
        return "read_notifications limit must be between 1 and 100."
    return await _dispatch("read_notifications", {"limit": str(limit)})


async def _control_media(action: str) -> str:
    """Dispatch a control_media relay request.

    Valid actions: play, pause, next, prev
    The phone's DeviceRelayController (extended from SmsRelayController) will
    handle the media control and report back via POST /v1/device/results.
    """
    action = action.lower()
    if action not in ("play", "pause", "next", "prev"):
        return f"control_media: invalid action '{action}'. Must be one of: play, pause, next, prev."
    return await _dispatch("control_media", {"action": action})


# ── register tools ──────────────────────────────────────────────────

register(
    ToolSpec(
        name="read_notifications",
        description=(
            "Read recent notifications from the user's connected Android phone. "
            "Relays through the Assistant app's NotificationListenerService. "
            "Returns a request_id; follow up with get_device_result(request_id)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notifications to read (1-100, default 10).",
                    "default": 10,
                },
            },
            "required": [],
        },
        always_visible=False,
    )
)

register(
    ToolSpec(
        name="control_media",
        description=(
            "Control media playback on the user's connected Android phone. "
            "Actions: play, pause, next, prev. Relays through the Assistant app's "
            "MediaSessionManager. Returns a request_id; follow up with get_device_result(request_id)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Media action to perform: play, pause, next, or prev.",
                    "enum": ["play", "pause", "next", "prev"],
                },
            },
            "required": ["action"],
        },
        always_visible=False,
    )
)