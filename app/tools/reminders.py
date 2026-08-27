"""create_reminder / list_reminders / cancel_reminder — the model's
interface to the reminders table. Creation/list/cancel only; delivery
(firing at due_at) is a separate phase, see docs/adr/006.
"""

import json
from datetime import datetime, timezone

from .. import db
from .registry import ToolSpec, register


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _create_reminder(text: str, due_at: str) -> str:
    try:
        datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    except ValueError:
        return f"Invalid due_at: {due_at!r} is not a valid ISO 8601 timestamp."
    conn = db.get_connection()
    created_at = _now_iso()
    cursor = await conn.execute(
        "INSERT INTO reminders (text, due_at, created_at, status) "
        "VALUES (?, ?, ?, 'pending')",
        (text, due_at, created_at),
    )
    await conn.commit()
    return f"Reminder {cursor.lastrowid} created for {due_at}: {text}"


async def _list_reminders() -> str:
    conn = db.get_connection()
    cursor = await conn.execute(
        "SELECT id, text, due_at, created_at, status FROM reminders "
        "WHERE status = 'pending' ORDER BY due_at ASC"
    )
    rows = await cursor.fetchall()
    if not rows:
        return "No pending reminders."
    return json.dumps(
        [
            {
                "id": r[0],
                "text": r[1],
                "due_at": r[2],
                "created_at": r[3],
                "status": r[4],
            }
            for r in rows
        ]
    )


async def _cancel_reminder(id: int) -> str:
    conn = db.get_connection()
    cursor = await conn.execute("SELECT status FROM reminders WHERE id = ?", (id,))
    row = await cursor.fetchone()
    if row is None:
        return f"No reminder with id {id}."
    if row[0] == "cancelled":
        return f"Reminder {id} is already cancelled."
    if row[0] != "pending":
        return f"Reminder {id} cannot be cancelled (status={row[0]})."
    await conn.execute(
        "UPDATE reminders SET status = 'cancelled' WHERE id = ?", (id,)
    )
    await conn.commit()
    return f"Reminder {id} cancelled."


register(
    ToolSpec(
        name="create_reminder",
        description=(
            "Create a reminder to fire at a specific time in the future. "
            "due_at must be an ISO 8601 timestamp (e.g. '2026-08-28T09:00:00+10:00')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "what to remind the user about"},
                "due_at": {"type": "string", "description": "ISO 8601 timestamp for when the reminder should fire"},
            },
            "required": ["text", "due_at"],
        },
        fn=_create_reminder,
    )
)

register(
    ToolSpec(
        name="list_reminders",
        description=(
            "List all pending reminders, ordered by due_at ascending. "
            "Returns the id, text, and due_at of each."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=_list_reminders,
    )
)

register(
    ToolSpec(
        name="cancel_reminder",
        description="Cancel a pending reminder by its id.",
        parameters={
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "id of the reminder to cancel"}},
            "required": ["id"],
        },
        fn=_cancel_reminder,
    )
)
