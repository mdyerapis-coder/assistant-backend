import os
from pathlib import Path

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest

from app import db, patterns


@pytest.fixture(autouse=True)
async def _db():
    await db.connect()
    yield
    await db.disconnect()


@pytest.mark.asyncio
async def test_record_pattern_crosses_threshold_at_three():
    # 1st execution -> False
    cross1 = await patterns.record_pattern("get_current_time", {})
    assert cross1 is False

    # 2nd execution -> False
    cross2 = await patterns.record_pattern("get_current_time", {})
    assert cross2 is False

    # 3rd execution -> True (exact threshold crossing)
    cross3 = await patterns.record_pattern("get_current_time", {})
    assert cross3 is True

    # 4th execution -> False
    cross4 = await patterns.record_pattern("get_current_time", {})
    assert cross4 is False


@pytest.mark.asyncio
async def test_pending_nudge_notice_and_nudge_limit():
    # Record 3 tool executions to trigger pattern
    for _ in range(3):
        await patterns.record_pattern("list_reminders", {})

    # 1st nudge call -> should produce notice and bump nudge_count to 1
    notice1 = await patterns.pending_nudge_notice()
    assert 'Pattern notice: you have performed "list_reminders"' in notice1
    assert "create_skill" in notice1

    # 2nd nudge call -> should produce notice and bump nudge_count to 2
    notice2 = await patterns.pending_nudge_notice()
    assert 'Pattern notice: you have performed "list_reminders"' in notice2

    # 3rd nudge call -> max nudges (2) reached, should return empty string
    notice3 = await patterns.pending_nudge_notice()
    assert notice3 == ""


@pytest.mark.asyncio
async def test_prune_old_patterns():
    conn = db.get_connection()
    old_time = "2020-01-01T00:00:00+00:00"
    await conn.execute(
        "INSERT INTO action_patterns (name, args_template, count, first_at, last_at) "
        "VALUES ('old_tool', '{}', 5, ?, ?)",
        (old_time, old_time),
    )
    await conn.commit()

    # Prune
    await patterns.prune_old_patterns()

    cursor = await conn.execute(
        "SELECT count(*) FROM action_patterns WHERE name = 'old_tool'"
    )
    row = await cursor.fetchone()
    assert row[0] == 0
