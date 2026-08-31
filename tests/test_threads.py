import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

from fastapi.testclient import TestClient

from app import db
from app.main import app

HEADERS = {"Authorization": "Bearer test-token"}


async def _seed(
    conversation_id: str,
    rows: list[tuple[str, str | None]],
    created_at: str = "2026-08-31T10:00:00+00:00",
) -> None:
    """Insert a conversation plus (role, content) messages. content None
    mimics an assistant row that only carried tool calls."""
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
        (conversation_id, created_at),
    )
    for i, (role, content) in enumerate(rows):
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, f"2026-08-31T10:00:0{i}+00:00"),
        )
    await conn.commit()


def test_threads_requires_auth():
    with TestClient(app) as client:
        assert client.get("/v1/threads").status_code == 401


def test_threads_empty_when_no_history():
    with TestClient(app) as client:
        resp = client.get("/v1/threads", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"threads": []}


def test_threads_lists_threads_with_derived_title_and_preview():
    with TestClient(app) as client:
        async def seed():
            await _seed(
                "t1",
                [
                    ("user", "what's on my calendar today"),
                    ("tool", '{"events": []}'),
                    ("assistant", "You have nothing scheduled."),
                ],
            )

        client.portal.call(seed)

        resp = client.get("/v1/threads", headers=HEADERS)
        assert resp.status_code == 200
        threads = resp.json()["threads"]
        assert len(threads) == 1
        thread = threads[0]
        assert thread["id"] == "t1"
        assert thread["title"] == "what's on my calendar today"
        # preview is the last user/assistant content, not the tool row
        assert thread["preview"] == "You have nothing scheduled."
        # message_count includes tool rows
        assert thread["message_count"] == 3
        assert thread["last_message_at"]


def test_threads_orders_by_last_message_and_skips_empty_conversations():
    with TestClient(app) as client:
        async def seed_all():
            await _seed("older", [("user", "first thread")])
            conn = db.get_connection()
            await conn.execute(
                "UPDATE messages SET created_at = '2026-08-30T09:00:00+00:00' "
                "WHERE conversation_id = 'older'"
            )
            await conn.execute(
                "INSERT INTO conversations (id, created_at) "
                "VALUES ('empty', '2026-08-31T11:00:00+00:00')"
            )
            await conn.commit()

        client.portal.call(seed_all)

        resp = client.get("/v1/threads", headers=HEADERS)
        threads = resp.json()["threads"]
        assert [t["id"] for t in threads] == ["older"]


def test_threads_truncates_long_titles():
    with TestClient(app) as client:
        async def seed():
            await _seed("long", [("user", "x" * 300)])

        client.portal.call(seed)
        thread = client.get("/v1/threads", headers=HEADERS).json()["threads"][0]
        assert len(thread["title"]) <= 81  # 80 chars + ellipsis
        assert thread["title"].endswith("…")


def test_thread_messages_returns_only_renderable_rows():
    with TestClient(app) as client:
        async def seed():
            await _seed(
                "t1",
                [
                    ("user", "hello"),
                    ("assistant", None),  # tool-call-only assistant row
                    ("tool", "raw tool result"),
                    ("assistant", "Hi there"),
                ],
            )

        client.portal.call(seed)

        resp = client.get("/v1/threads/t1/messages", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["thread_id"] == "t1"
        assert [m["content"] for m in body["messages"]] == ["hello", "Hi there"]
        assert all(m["role"] in ("user", "assistant") for m in body["messages"])
        assert all(isinstance(m["id"], int) for m in body["messages"])


def test_thread_messages_unknown_thread_404():
    with TestClient(app) as client:
        resp = client.get("/v1/threads/nope/messages", headers=HEADERS)
        assert resp.status_code == 404
