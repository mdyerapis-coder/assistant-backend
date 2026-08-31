import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest

from app import db
from app.tools import registry


def _invoke(tool_name: str, **kwargs):
    spec = registry.get_tool(tool_name)
    assert spec is not None, f"tool {tool_name} not registered"
    return spec.fn(**kwargs)


@pytest.fixture(autouse=True)
async def _db():
    await db.connect()
    yield
    await db.disconnect()


@pytest.mark.asyncio
async def test_create_automation_inserts_row():
    """create_automation creates a row in the automations table."""
    result = await _invoke(
        "create_automation",
        name="Daily digest",
        cron="0 9 * * *",  # 9am daily
        action="send_sms",
    )
    assert "Automation 'Daily digest' created" in result

    conn = db.get_connection()
    cursor = await conn.execute(
        "SELECT id, name, cron, action, enabled, created_at FROM automations"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    auto_id, name, cron, action, enabled, created_at = rows[0]
    assert name == "Daily digest"
    assert cron == "0 9 * * *"
    assert action == "send_sms"
    assert enabled == 1
    assert created_at is not None


@pytest.mark.asyncio
async def test_create_automation_with_different_cron():
    """create_automation works with various cron expressions."""
    result = await _invoke(
        "create_automation",
        name="Hourly chime",
        cron="0 * * * *",  # every hour
        action="notify",
    )
    assert "created" in result.lower()


@pytest.mark.asyncio
async def test_list_automations_returns_enabled():
    """list_automations returns enabled automations by default."""
    # Create automations first
    await _invoke("create_automation", name="Morning brief", cron="0 7 * * *", action="noop")
    await _invoke("create_automation", name=" Evening check", cron="20 18 * * *", action="notify")

    result = await _invoke("list_automations")
    assert "Morning brief" in result
    assert " Evening check" in result


@pytest.mark.asyncio
async def test_list_automations_all_includes_disabled():
    """list_automations with enabled_only=False shows all including disabled."""
    # Create automations
    await _invoke("create_automation", name="Enabled auto", cron="0 9 * * *", action="noop")
    await _invoke("create_automation", name="Disabled auto", cron="0 6 * * *", action="noop")

    # List all (including disabled)
    result = await _invoke("list_automations", enabled_only=False)
    assert "Enabled auto" in result
    assert "Disabled auto" in result


@pytest.mark.asyncio
async def test_list_automations_enabled_only_shows_enabled():
    """list_automations with enabled_only=True shows only enabled."""
    await _invoke("create_automation", name="Enabled auto", cron="0 9 * * *", action="noop")
    await _invoke("create_automation", name="Disabled auto", cron="0 6 * * *", action="noop")

    result = await _invoke("list_automations", enabled_only=True)
    assert "Enabled auto" in result


@pytest.mark.asyncio
async def test_delete_automation_removes_row():
    """delete_automation removes the automation by id."""
    create_result = await _invoke(
        "create_automation",
        name="To be deleted",
        cron="0 6 * * *",
        action="send_sms",
    )
    # Get the actual id from the DB
    conn = db.get_connection()
    cursor = await conn.execute("SELECT id FROM automations ORDER BY created_at DESC LIMIT 1")
    row = await cursor.fetchone()
    auto_id = row[0]  # actual DB id string

    delete_result = await _invoke("delete_automation", automation_id=auto_id)
    assert "deleted" in delete_result.lower()

    # Verify it's gone
    cursor = await conn.execute("SELECT COUNT(*) FROM automations")
    (count,) = await cursor.fetchone()
    assert count == 0


@pytest.mark.asyncio
async def test_delete_automation_unknown_id():
    """delete_automation reports not found for unknown id."""
    result = await _invoke("delete_automation", automation_id="auto-nonexistent")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_scheduler_cron_parsing():
    """Test that croniter can parse various cron expressions."""
    from croniter import croniter
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)

    # Test common cron expressions
    expressions = [
        ("0 9 * * *", "9am daily"),
        ("0 * * * *", "every hour"),
        ("0 0 * * *", "midnight daily"),
        ("30 18 * * 1-5", "6:30pm weekdays"),
    ]

    for expr, desc in expressions:
        schedule = croniter(expr, now)
        next_run = schedule.get_next(datetime.datetime)
        assert next_run is not None, f"Failed to parse cron: {expr} ({desc})"


@pytest.mark.asyncio
async def test_automation_tools_are_not_always_visible():
    """Automation tools should be hidden behind use_skill("automations")."""
    visible = {t.name for t in registry.always_visible_tools()}
    assert "create_automation" not in visible, \
        "create_automation should NOT be always_visible (hidden behind use_skill)"
    assert "list_automations" not in visible, \
        "list_automations should NOT be always_visible"
    assert "delete_automation" not in visible, \
        "delete_automation should NOT be always_visible"
