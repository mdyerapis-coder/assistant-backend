"""Background scheduler that polls for due reminders and fires them.

Runs as an asyncio task during the app's lifespan. Polls every
SCHEDULER_INTERVAL_SECONDS (default 30) for reminders where
status='pending' AND due_at <= now, sends an FCM push to all
registered device tokens, then flips status to 'fired' with a
fired_at timestamp.

Separated from the chat loop because reminder delivery is a
distinct concern — see docs/adr/006-reminder-creation-vs-delivery.md.
"""

import asyncio
import datetime
import logging

from . import db, fcm

logger = logging.getLogger(__name__)

SCHEDULER_INTERVAL_SECONDS = 30


async def _fire_due_reminders() -> int:
    """Find due reminders, send FCM, update status. Returns count fired."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn = db.get_connection()

    # Fetch all pending reminders whose due_at has passed
    async with conn.execute(
        "SELECT id, text, due_at FROM reminders "
        "WHERE status = 'pending' AND due_at <= ? "
        "ORDER BY due_at ASC",
        (now,),
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


async def _scheduler_loop() -> None:
    """Main polling loop — runs until cancelled."""
    logger.info("Scheduler started (interval=%ds)", SCHEDULER_INTERVAL_SECONDS)
    try:
        while True:
            try:
                fired = await _fire_due_reminders()
                if fired:
                    logger.info("Scheduler cycle: %d reminders fired", fired)
            except Exception:
                logger.exception("Scheduler cycle failed")
            await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Scheduler stopped")
        raise
