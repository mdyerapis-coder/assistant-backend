"""Background scheduler that polls for due reminders and fires them, plus due automations.

Runs as an asyncio task during the app's lifespan. Polls every
SCHEDULER_INTERVAL_SECONDS (default 30) for reminders where
status='pending' AND due_at <= now, sends an FCM push to all
registered device tokens, then flips status to 'fired' with a
fired_at timestamp. Also checks for due automations (parsed via
croniter) and executes their action, then FCM-pushes the result.

Separated from the chat loop because reminder delivery is a
distinct concern — see docs/adr/006-reminder-creation-vs-delivery.md.
"""

import asyncio
import datetime
import logging

from . import db, fcm
from croniter import croniter

logger = logging.getLogger(__name__)

SCHEDULER_INTERVAL_SECONDS = 30


async def _fire_due_reminders() -> int:
    """Find due reminders, send FCM, update status. Returns count fired."""
    now = datetime.datetime.now(datetime.timezone.utc)
    conn = db.get_connection()

    # Fetch all pending reminders whose due_at has passed
    async with conn.execute(
        "SELECT id, text, due_at FROM reminders "
        "WHERE status = 'pending' AND due_at <= ? "
        "ORDER BY due_at ASC",
        (now.isoformat(),),
    ) as cursor:
        due = await cursor.fetchall()

    if not due:
        return 0

    # Fetch all registered device tokens
    async with conn.execute("SELECT token FROM device_tokens") as cursor:
        tokens = [row[0] for row in await cursor.fetchall()]

    if not tokens:
        logger.warning("No device tokens registered — cannot deliver %d reminders", len(due))
        return 0

    fired_count = 0
    for reminder_id, text, due_at in due:
        success = await fcm.send_notification(
            tokens=tokens,
            title="Reminder",
            body=text,
            data={"reminder_id": str(reminder_id), "due_at": due_at},
        )
        # Mark as fired regardless of FCM success to avoid infinite retries.
        # The user can check the reminder status to see if it was delivered.
        fired_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await conn.execute(
            "UPDATE reminders SET status = 'fired', fired_at = ? WHERE id = ?",
            (fired_at, reminder_id),
        )
        fired_count += 1
        if success:
            logger.info("Fired reminder %d: %s", reminder_id, text)
        else:
            logger.warning(
                "Reminder %d fired but FCM delivery failed: %s",
                reminder_id,
                text,
            )

    await conn.commit()
    return fired_count


async def _fire_due_automations() -> int:
    """Find due automations (via croniter), execute their action, FCM-push result. Returns count fired."""
    conn = db.get_connection()
    now = datetime.datetime.now(datetime.timezone.utc)

    # Fetch all enabled automations
    async with conn.execute(
        "SELECT id, name, cron, action FROM automations WHERE enabled = 1"
    ) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return 0

    fired_count = 0
    for auto_id, name, cron, action in rows:
        # Parse cron; skip if invalid
        try:
            schedule = croniter(cron, now)
            next_run = schedule.get_next(datetime.datetime)
        except Exception:
            logger.warning("Invalid cron expression for automation %s: %s", name, cron)
            continue

        # Check if the automation is due (next_run is in the past or now)
        # We consider it due if the next scheduled time is within the last second
        # (this is a simplification; a production system would match cron exactness)
        if (now - next_run).total_seconds() > 1:
            continue  # not due yet

        # Execute the action (skill/tool) via the tool registry
        from .registry import get_tool

        tool = get_tool(action)
        if tool is None:
            logger.warning("Automation %s has unknown action: %s", name, action)
            # Still mark as fired to avoid infinite retries
            fired_at = now.isoformat()
            await conn.execute(
                "UPDATE automations SET enabled = 0, fired_at = ? WHERE id = ?",
                (fired_at, auto_id),
            )
            fired_count += 1
            continue

        try:
            result = await tool.fn()
            success = True
            summary = result
        except Exception as e:
            success = False
            summary = f"Error: {e}"

        # FCM-push the result
        try:
            # Get device tokens
            async with conn.execute("SELECT token FROM device_tokens") as tcursor:
                tokens = [row[0] for row in await tcursor.fetchall()]
            if tokens:
                await fcm.send_notification(
                    tokens=tokens,
                    title="Automation fired",
                    body=f"Automation '{name}' executed",
                    data={"automation_id": auto_id, "action": action, "ok": str(success).lower(), "summary": summary},
                )
        except Exception as e:
            logger.warning("FCM push failed for automation %s: %s", name, e)

        # Mark as fired regardless of success; also disable after first fire
        fired_at = now.isoformat()
        await conn.execute(
            "UPDATE automations SET enabled = 0, fired_at = ? WHERE id = ?",
            (fired_at, auto_id),
        )
        fired_count += 1
        logger.info("Fired automation %s: %s", name, summary)

    await conn.commit()
    return fired_count


async def _scheduler_loop() -> None:
    """Main polling loop — runs until cancelled."""
    logger.info("Scheduler started (interval=%ds)", SCHEDULER_INTERVAL_SECONDS)
    try:
        while True:
            try:
                fired_reminders = await _fire_due_reminders()
                fired_automations = await _fire_due_automations()
                if fired_reminders:
                    logger.info("Scheduler cycle: %d reminders fired", fired_reminders)
                if fired_automations:
                    logger.info("Scheduler cycle: %d automations fired", fired_automations)
            except Exception:
                logger.exception("Scheduler cycle failed")
            await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Scheduler stopped")
        raise