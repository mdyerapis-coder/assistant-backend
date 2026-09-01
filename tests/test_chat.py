import json
import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

from fastapi.testclient import TestClient

from app import db, memory, openai_client
from app.main import app

HEADERS = {"Authorization": "Bearer test-token"}


class FakeFunctionDelta:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class FakeToolCallDelta:
    def __init__(self, index, id=None, name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = (
            FakeFunctionDelta(name=name, arguments=arguments)
            if (name is not None or arguments is not None)
            else None
        )


class FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class FakeChunk:
    def __init__(self, delta, finish_reason=None):
        self.choices = [FakeChoice(delta, finish_reason)]


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c


def _parse_sse(body: str) -> list[dict | None]:
    events: list[dict | None] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        events.append(None if payload == "[DONE]" else json.loads(payload))
    return events


def test_chat_plain_text_reply(monkeypatch):
    chunks = [
        FakeChunk(FakeDelta(content="Hello")),
        FakeChunk(FakeDelta(content=" there"), finish_reason="stop"),
    ]

    async def fake_create(**kwargs):
        return FakeStream(chunks)

    monkeypatch.setattr(openai_client.client.chat.completions, "create", fake_create)

    with TestClient(app) as client:
        resp = client.post("/v1/chat", headers=HEADERS, json={"message": "hi"})
        assert resp.status_code == 200
        events = _parse_sse(resp.text)

        deltas = [e for e in events if e and e["type"] == "delta"]
        assert [d["content"] for d in deltas] == ["Hello", " there"]
        assert all(d["conversation_id"] for d in deltas)

        completed = next(e for e in events if e and e["type"] == "message_completed")
        assert completed["conversation_id"] == deltas[0]["conversation_id"]
        assert events[-1] is None  # the [DONE] sentinel

        async def _rows():
            conn = db.get_connection()
            async with conn.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? "
                "ORDER BY id",
                (completed["conversation_id"],),
            ) as cursor:
                return await cursor.fetchall()

        # run on the app's own event loop (via TestClient's portal) — the
        # aiosqlite connection is bound to that loop, not this thread's
        rows = client.portal.call(_rows)
        assert rows == [("user", "hi"), ("assistant", "Hello there")]


def test_chat_executes_tool_call_and_continues(monkeypatch):
    first_chunks = [
        FakeChunk(
            FakeDelta(
                tool_calls=[
                    FakeToolCallDelta(0, id="call_1", name="remember", arguments="")
                ]
            )
        ),
        FakeChunk(
            FakeDelta(
                tool_calls=[
                    FakeToolCallDelta(0, arguments='{"key": "name", "value": "Mason"}')
                ]
            ),
            finish_reason="tool_calls",
        ),
    ]
    second_chunks = [FakeChunk(FakeDelta(content="Got it."), finish_reason="stop")]
    responses = [FakeStream(first_chunks), FakeStream(second_chunks)]

    async def fake_create(**kwargs):
        return responses.pop(0)

    monkeypatch.setattr(openai_client.client.chat.completions, "create", fake_create)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            headers=HEADERS,
            json={"message": "remember my name is Mason"},
        )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)

        started = next(e for e in events if e and e["type"] == "tool_call_started")
        assert started["name"] == "remember"
        assert json.loads(started["args_json"]) == {"key": "name", "value": "Mason"}

        finished = next(e for e in events if e and e["type"] == "tool_call_finished")
        assert finished["ok"] is True

        deltas = [e for e in events if e and e["type"] == "delta"]
        assert "".join(d["content"] for d in deltas) == "Got it."

        facts = client.portal.call(memory.get_all_facts)
        assert facts == {"name": "Mason"}
def _capture_create(monkeypatch):
    """Stub the LLM call and capture the outbound completion kwargs."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return FakeStream([FakeChunk(FakeDelta(content="ok"), finish_reason="stop")])

    monkeypatch.setattr(openai_client.client.chat.completions, "create", fake_create)
    return captured


def test_chat_timezone_reaches_system_prompt(monkeypatch):
    captured = _capture_create(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            headers=HEADERS,
            json={"message": "what time is it", "timezone": "Australia/Brisbane"},
        )
        assert resp.status_code == 200

    system = captured["messages"][0]["content"]
    assert "Australia/Brisbane" in system


def test_chat_without_timezone_defaults_to_utc(monkeypatch):
    captured = _capture_create(monkeypatch)

    with TestClient(app) as client:
        resp = client.post("/v1/chat", headers=HEADERS, json={"message": "hi"})
        assert resp.status_code == 200

    assert "UTC" in captured["messages"][0]["content"]


def test_chat_invalid_timezone_falls_back_to_utc(monkeypatch):
    captured = _capture_create(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            headers=HEADERS,
            json={"message": "hi", "timezone": "Mars/Olympus"},
        )
        assert resp.status_code == 200

    assert "UTC" in captured["messages"][0]["content"]
