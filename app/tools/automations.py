"""create_automation / list_automations / delete_automation — natural-language cron automations.

Automations are user-defined recurring jobs expressed as cron expressions.
Creation/listing/deletion are CRUD only; delivery (firing at due time) is
handled by the scheduler loop in app/scheduler.py.

Automations are hidden behind use_skill("automations") (always_visible=False),
so they don't appear in every OpenAI tool-schema call — progressive disclosure
(ADR-009).
"""

import json
from datetime import datetime, timezone

from .. import db
from .registry import ToolSpec, register


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _create_automation(name: str, cron: str, action: str) -> str:
    """Create a new automation. Returns the automation id."""
    try:
        conn = db.get_connection()
        created_at = _now_iso()
        cursor = await conn.execute(
            """INSERT INTO automations (id, name, cron, action, enabled, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (
                f"auto_{name.replace(' ', '_').lower()}_{created_at}",
                name,
                cron,
                action,
                created_at,
            ),
        )
        await conn.commit()
        return f"Automation '{name}' created with id {cursor.lastrowid}"
    except Exception as e:
        return f"Failed to create automation: {e}"


async def _list_automations(enabled_only: bool = True) -> str:
    """List all automations (or only enabled ones)."""
    conn = db.get_connection()
    cond = "WHERE enabled = 1" if enabled_only else ""
    async with conn.execute(
        f"SELECT id, name, cron, action, enabled, created_at FROM automations {cond} ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    if not rows:
        return "No automations found." if enabled_only else "No automations configured."
    lines = []
    for row in rows:
        auto_id, name, cron, action, enabled, created_at = row
        status = "enabled" if enabled else "disabled"
        lines.append(f"  id={auto_id}  name={name}  cron={cron}  action={action}  status={status}  created={created_at}")
    return "Automations:\n" + "\n".join(lines)


async def _delete_automation(automation_id: str) -> str:
    """Delete an automation by its id."""
    conn = db.get_connection()
    # Check if it exists first
    async with conn.execute("SELECT id, name FROM automations WHERE id = ?", (automation_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return f"Automation with id '{automation_id}' not found."
    name = row[1]
    await conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
    await conn.commit()
    return f"Automation '{name}' (id={automation_id}) deleted."


# ── register tools ──

register(
    ToolSpec(
        name="create_automation",
        description="Create a new automation with a natural-language cron expression and action. "
                    "The cron is parsed by the scheduler (croniter). "
                    "The action is a skill name or tool call path that the scheduler will execute when due.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable name for the automation"},
                "cron": {"type": "string", "description": "Standard cron expression (e.g. '0 9 * * *' for 9am daily)"},
                "action": {"type": "string", "description": "The skill/tool to execute when the cron fires"},
            },
            "required": ["name", "cron", "action"],
            "additionalProperties": False,
        },
        fn=_create_automation,
        always_visible=False,
    )
)

register(
    ToolSpec(
        name="list_automations",
        description="List all automations, or only the enabled ones. "
                    "Automations are hidden behind use_skill(\"automations\") — progressive disclosure.",
        parameters={
            "type": "object",
            "properties": {
                "enabled_only": {"type": "boolean", "description": "If True (default), only show enabled automations", "default": True},
            },
            "additionalProperties": False,
        },
        fn=_list_automations,
        always_visible=False,
    )
)

register(
    ToolSpec(
        name="delete_automation",
        description="Delete an automation by its id. The id is returned by create_automation.",
        parameters={
            "type": "object",
            "properties": {
                "automation_id": {"type": "string", "description": "The id of the automation to delete"},
            },
            "additionalProperties": False,
        },
        fn=_delete_automation,
        always_visible=False,
    )
)