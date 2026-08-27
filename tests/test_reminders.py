import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import json

import pytest

from app import db
from app.tools import registry
from app.tools import reminders  # noqa: F401  registers the tools


def _invoke(name: str, **kwargs):
    spec = registry.get_tool(name)
    assert spec is not None, f"tool {name} not registered"
    return spec.fn(**kwargs)


@pytest.fixture(autouse=True)
async def _db():
    await db.connect()
    yield
    await db.disconnect()


@pytest.mark.asyncio
async def test_create_reminder_inserts_pending_row():
    result = await _invoke(
        "create_reminder",
        text="call the dentist",
        due_at="2026-08-28T09:00:00+10:00",
    )
    assert "Reminder 1 created" in result
    assert "2026-08-28T09:00:00+10:00" in result

    conn = db.get_connection()
    cursor = await conn.execute(
        "SELECT id, text, due_at, status, fired_at FROM reminders"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    rid, text, due_at, status, fired_at = rows[0]
    assert rid == 1
    assert text == "call the dentist"
    assert due_at == "2026-08-28T09:00:00+10:00"
    assert status == "pending"
    assert fired_at is None


@pytest.mark.asyncio
async def test_create_reminder_rejects_invalid_due_at():
    result = await _invoke(
        "create_reminder", text="bad", due_at="not-a-timestamp"
    )
    assert "Invalid due_at" in result
    conn = db.get_connection()
    cursor = await conn.execute("SELECT COUNT(*) FROM reminders")
    (count,) = await cursor.fetchone()
    assert count == 0


@pytest.mark.asyncio
async def test_list_reminders_returns_pending_only_ordered_by_due_at():
    await _invoke("create_reminder", text="later", due_at="2026-09-01T10:00:00+00:00")
    await _invoke("create_reminder", text="earlier", due_at="2026-08-28T09:00:00+00:00")
    await _invoke("create_reminder", text="middle", due_at="2026-08-30T12:00:00+00:00")

    result = await _invoke("list_reminders")
    payload = json.loads(result)
    texts = [r["text"] for r in payload]
    assert texts == ["earlier", "middle", "later"]
    for r in payload:
        assert r["status"] == "pending"
        assert set(r.keys()) == {"id", "text", "due_at", "created_at", "status"}


@pytest.mark.asyncio
async def test_list_reminders_empty_returns_human_message():
    result = await _invoke("list_reminders")
    assert result == "No pending reminders."


@pytest.mark.asyncio
async def test_cancel_reminder_sets_status_to_cancelled():
    await _invoke("create_reminder", text="call the dentist", due_at="2026-08-28T09:00:00+00:00")
    result = await _invoke("cancel_reminder", id=1)
    assert "cancelled" in result.lower()

    conn = db.get_connection()
    cursor = await conn.execute("SELECT status FROM reminders WHERE id = 1")
    (status,) = await cursor.fetchone()
    assert status == "cancelled"

    listing = await _invoke("list_reminders")
    assert listing == "No pending reminders."


@pytest.mark.asyncio
async def test_cancel_reminder_unknown_id():
    result = await _invoke("cancel_reminder", id=999)
    assert "No reminder with id 999" in result


@pytest.mark.asyncio
async def test_cancel_reminder_already_cancelled_is_idempotent():
    await _invoke("create_reminder", text="call the dentist", due_at="2026-08-28T09:00:00+00:00")
    await _invoke("cancel_reminder", id=1)
    result = await _invoke("cancel_reminder", id=1)
    assert "already cancelled" in result.lower()


@pytest.mark.asyncio
async def test_reminder_tools_are_always_visible():
    visible = {t.name for t in registry.always_visible_tools()}
    assert "create_reminder" in visible
    assert "list_reminders" in visible
    assert "cancel_reminder" in visible
