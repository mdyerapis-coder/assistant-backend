"""Tests for the reminder scheduler and device token registration."""

import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import datetime

import pytest

from app import db
from app.scheduler import _fire_due_reminders


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _minutes_ago(n: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(minutes=n)
    ).isoformat()


def _minutes_from_now(n: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=n)
    ).isoformat()


@pytest.fixture(autouse=True)
async def _db():
    await db.connect()
    yield
    await db.disconnect()


# --- _fire_due_reminders ---


@pytest.mark.asyncio
async def test_fire_due_reminders_fires_past_reminders():
    """Reminders whose due_at has passed should be fired."""
    conn = db.get_connection()
    # Insert a due reminder
    await conn.execute(
        "INSERT INTO reminders (text, due_at, created_at, status) "
        "VALUES (?, ?, ?, 'pending')",
        ("Call dentist", _minutes_ago(5), _now_iso()),
    )
    # Insert a future reminder (should NOT fire)
    await conn.execute(
        "INSERT INTO reminders (text, due_at, created_at, status) "
        "VALUES (?, ?, ?, 'pending')",
        ("Buy groceries", _minutes_from_now(60), _now_iso()),
    )
    # Insert a device token
    await conn.execute(
        "INSERT INTO device_tokens (token, device_id, created_at) VALUES (?, ?, ?)",
        ("test-token-abc", "test-device", _now_iso()),
    )
    await conn.commit()

    fired = await _fire_due_reminders()

    assert fired == 1

    # Check that the past reminder is now fired
    async with conn.execute(
        "SELECT status, fired_at FROM reminders WHERE text = 'Call dentist'"
    ) as cursor:
        row = await cursor.fetchone()
        assert row[0] == "fired"
        assert row[1] is not None

    # Check that the future reminder is still pending
    async with conn.execute(
        "SELECT status FROM reminders WHERE text = 'Buy groceries'"
    ) as cursor:
        row = await cursor.fetchone()
        assert row[0] == "pending"


@pytest.mark.asyncio
async def test_fire_due_reminders_no_tokens_skips():
    """If no device tokens are registered, no reminders should fire."""
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO reminders (text, due_at, created_at, status) "
        "VALUES (?, ?, ?, 'pending')",
        ("Test", _minutes_ago(1), _now_iso()),
    )
    await conn.commit()

    fired = await _fire_due_reminders()

    assert fired == 0

    # Reminder should still be pending
    async with conn.execute(
        "SELECT status FROM reminders WHERE text = 'Test'"
    ) as cursor:
        row = await cursor.fetchone()
        assert row[0] == "pending"


@pytest.mark.asyncio
async def test_fire_due_reminders_multiple_past():
    """Multiple past reminders should all fire in one cycle."""
    conn = db.get_connection()
    for i in range(3):
        await conn.execute(
            "INSERT INTO reminders (text, due_at, created_at, status) "
            "VALUES (?, ?, ?, 'pending')",
            (f"Task {i}", _minutes_ago(10 - i), _now_iso()),
        )
    await conn.execute(
        "INSERT INTO device_tokens (token, device_id, created_at) VALUES (?, ?, ?)",
        ("token-1", "device-1", _now_iso()),
    )
    await conn.commit()

    fired = await _fire_due_reminders()

    assert fired == 3

    # All should be fired now
    async with conn.execute(
        "SELECT COUNT(*) FROM reminders WHERE status = 'fired'"
    ) as cursor:
        row = await cursor.fetchone()
        assert row[0] == 3
