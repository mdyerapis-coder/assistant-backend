import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest

from app import db, memory


@pytest.fixture(autouse=True)
async def _db():
    await db.connect()
    yield
    await db.disconnect()


@pytest.mark.asyncio
async def test_remember_and_get_all_facts():
    result = await memory.remember("timezone", "Australia/Sydney")
    assert "Remembered" in result
    facts = await memory.get_all_facts()
    assert facts == {"timezone": "Australia/Sydney"}


@pytest.mark.asyncio
async def test_remember_overwrites_existing_key():
    await memory.remember("timezone", "Australia/Sydney")
    await memory.remember("timezone", "UTC")
    facts = await memory.get_all_facts()
    assert facts == {"timezone": "UTC"}


@pytest.mark.asyncio
async def test_forget_removes_fact():
    await memory.remember("timezone", "UTC")
    result = await memory.forget("timezone")
    assert "Forgot" in result
    assert await memory.get_all_facts() == {}


@pytest.mark.asyncio
async def test_forget_unknown_key_reports_nothing_stored():
    result = await memory.forget("nope")
    assert "No fact named" in result


@pytest.mark.asyncio
async def test_remember_rejects_write_past_cap():
    big_value = "x" * (memory.MAX_FACTS_CHARS + 1)
    result = await memory.remember("giant", big_value)
    assert "cap" in result.lower()
    assert await memory.get_all_facts() == {}


@pytest.mark.asyncio
async def test_remember_allows_overwrite_of_existing_key_even_near_cap():
    half = "x" * (memory.MAX_FACTS_CHARS // 2)
    await memory.remember("a", half)
    # overwriting "a" again shouldn't be blocked just because it's already large
    result = await memory.remember("a", half)
    assert "Remembered" in result


def test_render_facts_block_empty():
    assert memory.render_facts_block({}) == ""


def test_render_facts_block_nonempty():
    block = memory.render_facts_block({"timezone": "UTC"})
    assert "timezone: UTC" in block


@pytest.mark.asyncio
async def test_search_past_conversations_matches_content():
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO conversations (id, created_at) VALUES ('c1', 'now')"
    )
    await conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) "
        "VALUES ('c1', 'user', 'remember to buy milk', 'now')"
    )
    await conn.commit()
    results = await memory.search_past_conversations("milk")
    assert len(results) == 1
    assert results[0]["content"] == "remember to buy milk"
