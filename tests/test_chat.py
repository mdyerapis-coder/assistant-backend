import json
import os
from typing import cast, NotRequired, TypedDict

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

from fastapi.testclient import TestClient

from app import db, memory, openai_client, providers
from app.main import app

HEADERS = {"Authorization": "Bearer test-token"}


class SseEvent(TypedDict):
    type: str
    conversation_id: str
    content: NotRequired[str]
    message_id: NotRequired[str]
    name: NotRequired[str]
    args_json: NotRequired[str]
    ok: NotRequired[bool]


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


def _parse_sse(body: str) -> list[SseEvent | None]:
    events: list[SseEvent | None] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        events.append(
            None if payload == "[DONE]" else cast(SseEvent, json.loads(payload))
        )
    return events


def _string(event: SseEvent, key: str) -> str:
    value = event.get(key)
    assert isinstance(value, str)
    return value


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
        assert [_string(d, "content") for d in deltas] == ["Hello", " there"]
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
        assert client.portal is not None
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
        assert _string(started, "name") == "remember"
        assert json.loads(_string(started, "args_json")) == {
            "key": "name",
            "value": "Mason",
        }

        finished = next(e for e in events if e and e["type"] == "tool_call_finished")
        assert finished.get("ok") is True

        deltas = [e for e in events if e and e["type"] == "delta"]
        assert "".join(_string(d, "content") for d in deltas) == "Got it."

        assert client.portal is not None
        facts = client.portal.call(memory.get_all_facts)
        assert facts == {"name": "Mason"}


def test_models_lists_only_configured_providers(monkeypatch):
    # Given
    for provider in providers.PROVIDERS:
        monkeypatch.delenv(provider.api_key_env, raising=False)
    configured = providers.PROVIDERS[0]
    monkeypatch.setenv(configured.api_key_env, "fake-key")

    # When
    with TestClient(app) as client:
        response = client.get("/v1/models", headers=HEADERS)

    # Then
    assert response.status_code == 200
    assert response.json() == {
        "default_model_id": configured.name,
        "models": [
            {
                "id": configured.name,
                "model": configured.default_model,
                "provider": configured.name,
                "description": configured.note,
            }
        ],
    }


def test_chat_uses_selected_model_when_request_names_provider(monkeypatch):
    # Given
    chunks = [FakeChunk(FakeDelta(content="Selected."), finish_reason="stop")]
    selected_ids: list[str | None] = []
    called_models: list[str] = []

    async def fake_create(**kwargs):
        called_models.append(kwargs["model"])
        return FakeStream(chunks)

    monkeypatch.setattr(openai_client.client.chat.completions, "create", fake_create)

    def fake_resolve(model_id: str | None):
        selected_ids.append(model_id)
        return openai_client.ModelRuntime(
            client=openai_client.client,
            model="selected-model",
            extra_body={},
        )

    monkeypatch.setattr(openai_client, "resolve_model", fake_resolve)

    # When
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            headers=HEADERS,
            json={"message": "hello", "model": "gemini"},
        )

    # Then
    assert response.status_code == 200
    assert selected_ids == ["gemini"]
    assert called_models == ["selected-model"]


def test_chat_rejects_unavailable_selected_model(monkeypatch):
    # Given
    monkeypatch.setattr(openai_client, "resolve_model", lambda model_id: None)

    # When
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            headers=HEADERS,
            json={"message": "hello", "model": "missing"},
        )

    # Then
    assert response.status_code == 422
