import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest

from app import db, extraction, memory, openai_client


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


@pytest.fixture(autouse=True)
async def _db():
    await db.connect()
    yield
    await db.disconnect()


def _patch_create(monkeypatch, content, calls=None):
    async def fake_create(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return FakeCompletion(content)

    monkeypatch.setattr(openai_client.client.chat.completions, "create", fake_create)


async def _seed_exchange(conversation_id: str, user: str, assistant: str) -> None:
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO conversations (id, created_at) VALUES (?, 'now')",
        (conversation_id,),
    )
    await conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) "
        "VALUES (?, 'user', ?, 'now')",
        (conversation_id, user),
    )
    await conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) "
        "VALUES (?, 'assistant', ?, 'now')",
        (conversation_id, assistant),
    )
    await conn.commit()


def test_extract_json_object_plain():
    assert extraction._extract_json_object('{"facts": {"a": "b"}}') == {
        "facts": {"a": "b"}
    }


def test_extract_json_object_markdown_fenced():
    fenced = '```json\n{"facts": {"a": "b"}}\n```'
    assert extraction._extract_json_object(fenced) == {"facts": {"a": "b"}}


def test_extract_json_object_embedded_in_prose():
    prose = 'Here you go: {"facts": {"a": "b"}} — hope that helps!'
    assert extraction._extract_json_object(prose) == {"facts": {"a": "b"}}


def test_extract_json_object_garbage_returns_none():
    assert extraction._extract_json_object("no json here at all") is None


async def test_extract_facts_returns_new_facts(monkeypatch):
    _patch_create(monkeypatch, '{"facts": {"dog_name": "Rover"}}')
    facts = await extraction.extract_facts("my dog is called Rover", "Noted!")
    assert facts == {"dog_name": "Rover"}


async def test_extract_facts_skips_model_call_on_empty_input(monkeypatch):
    calls: list[dict] = []
    _patch_create(monkeypatch, '{"facts": {"x": "y"}}', calls)
    assert await extraction.extract_facts("", "reply") == {}
    assert await extraction.extract_facts("hello", "   ") == {}
    assert calls == []


async def test_extract_facts_invalid_json_returns_empty(monkeypatch):
    _patch_create(monkeypatch, "I cannot answer that as JSON")
    assert await extraction.extract_facts("hi", "hello") == {}


async def test_extract_facts_model_failure_returns_empty(monkeypatch):
    async def failing_create(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        openai_client.client.chat.completions, "create", failing_create
    )
    assert await extraction.extract_facts("hi", "hello") == {}


async def test_extract_and_store_writes_new_fact(monkeypatch):
    _patch_create(monkeypatch, '{"facts": {"dog_name": "Rover"}}')
    await _seed_exchange("c1", "my dog is called Rover", "Noted!")
    await extraction.extract_and_store("c1")
    assert await memory.get_all_facts() == {"dog_name": "Rover"}


async def test_extract_and_store_skips_unchanged_facts(monkeypatch):
    await memory.remember("dog_name", "Rover")
    # same value the model would extract
    _patch_create(monkeypatch, '{"facts": {"dog_name": "Rover"}}')
    await _seed_exchange("c1", "my dog is called Rover", "Noted!")
    await extraction.extract_and_store("c1")
    # still exactly one fact, unchanged
    assert await memory.get_all_facts() == {"dog_name": "Rover"}


async def test_extract_and_store_survives_cap_rejection(monkeypatch):
    _patch_create(
        monkeypatch,
        '{"facts": {"small": "ok", "giant": "' + "z" * 5000 + '"}}',
    )
    await _seed_exchange("c1", "stuff", "things")
    await extraction.extract_and_store("c1")
    facts = await memory.get_all_facts()
    assert facts == {"small": "ok"}  # giant rejected by the cap, no crash


async def test_extract_and_store_no_user_message_is_a_no_op(monkeypatch):
    calls: list[dict] = []
    _patch_create(monkeypatch, '{"facts": {"a": "b"}}', calls)
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO conversations (id, created_at) VALUES ('c1', 'now')"
    )
    await conn.commit()
    await extraction.extract_and_store("c1")
    assert await memory.get_all_facts() == {}
