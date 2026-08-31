"""SMS relay tests — tool dispatch (FCM push + relay row), results endpoint,
and the get_sms_result read-back. fcm is stubbed: tests assert the push
payload that would have been sent, without touching Firebase."""

import asyncio
import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools import sms as sms_tools
from app.tools.registry import always_visible_tools, get_tool

HEADERS = {"Authorization": "Bearer test-token"}

_sent: list[tuple[list[str], str, str, dict[str, str]]] = []


@pytest.fixture(autouse=True)
def _fake_fcm(monkeypatch):
    async def _fake_send(tokens, title, body, data=None):
        _sent.append((tokens, title, body, data or {}))
        return True

    monkeypatch.setattr(sms_tools.fcm, "send_notification", _fake_send)
    _sent.clear()
    yield


async def _relay_row(request_id: str):
    from app import db

    conn = db.get_connection()
    async with conn.execute(
        "SELECT action, status, error FROM sms_relay WHERE id = ?", (request_id,)
    ) as cursor:
        return await cursor.fetchone()


def test_sms_tools_registered_hidden():
    names = {t.name for t in always_visible_tools()}
    assert "send_sms" not in names
    assert "read_sms" not in names
    assert get_tool("send_sms") is not None
    assert get_tool("read_sms") is not None
    assert get_tool("get_sms_result") is not None


def test_sms_skill_file_present():
    from pathlib import Path

    from app import skills as skills_module

    skills_module.load_skills(Path(__file__).resolve().parent.parent / "skills")
    skill = skills_module.get_skill("sms")
    assert skill is not None
    assert {"send_sms", "read_sms", "get_sms_result"} <= set(skill.tools)


def test_send_sms_dispatches_fcm_and_tracks_request():
    from app import db

    async def _seed():
        conn = db.get_connection()
        await conn.execute(
            "INSERT INTO device_tokens (token, device_id, created_at) "
            "VALUES ('fcm-token-1', 'phone-1', '2026-09-01T00:00:00Z')"
        )
        await conn.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        result = asyncio.run(sms_tools._send_sms("+61412345678", "Hello from assistant"))
        assert len(_sent) == 1
        tokens, _title, _body, data = _sent[0]
        assert data["request_id"] in result
        assert tokens == ["fcm-token-1"]
        assert data["action"] == "send_sms"
        assert data["phone"] == "+61412345678"
        assert data["message"] == "Hello from assistant"
        assert asyncio.run(_relay_row(data["request_id"]))[0:2] == (
            "send_sms",
            "dispatched",
        )


def test_send_sms_without_registered_phone_returns_guidance():
    from app import db

    async def _run():
        await db.connect()
        try:
            return await sms_tools._send_sms("+61412345678", "hi")
        finally:
            await db.disconnect()

    result = asyncio.run(_run())
    assert "No phone is registered" in result
    assert _sent == []


def test_results_endpoint_records_failure():
    from app import db

    async def _seed():
        conn = db.get_connection()
        await conn.execute(
            "INSERT INTO sms_relay (id, action, status, created_at, updated_at) "
            "VALUES ('req-1', 'send_sms', 'dispatched', 'now', 'now')"
        )
        await conn.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        resp = client.post(
            "/v1/sms/results",
            headers=HEADERS,
            json={"request_id": "req-1", "ok": False, "error": "SIM missing"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert asyncio.run(_relay_row("req-1")) == ("send_sms", "failed", "SIM missing")


def test_results_endpoint_records_read_messages():
    from app import db

    async def _seed():
        conn = db.get_connection()
        await conn.execute(
            "INSERT INTO sms_relay (id, action, status, created_at, updated_at) "
            "VALUES ('req-2', 'read_sms', 'dispatched', 'now', 'now')"
        )
        await conn.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        resp = client.post(
            "/v1/sms/results",
            headers=HEADERS,
            json={
                "request_id": "req-2",
                "ok": True,
                "messages": [
                    {
                        "from_number": "+61498765432",
                        "message": "See you at 5",
                        "received_at": "2026-09-01T01:00:00Z",
                    }
                ],
            },
        )
        assert resp.status_code == 200

        result = asyncio.run(sms_tools._get_sms_result("req-2"))
        assert "+61498765432" in result
        assert "See you at 5" in result


def test_results_endpoint_unknown_request_404():
    with TestClient(app) as client:
        resp = client.post(
            "/v1/sms/results",
            headers=HEADERS,
            json={"request_id": "nope", "ok": True},
        )
        assert resp.status_code == 404


def test_get_sms_result_pending_and_unknown():
    from app import db

    async def _seed():
        conn = db.get_connection()
        await conn.execute(
            "INSERT INTO sms_relay (id, action, status, created_at, updated_at) "
            "VALUES ('req-3', 'send_sms', 'dispatched', 'now', 'now')"
        )
        await conn.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        pending = asyncio.run(sms_tools._get_sms_result("req-3"))
        assert "in flight" in pending
        unknown = asyncio.run(sms_tools._get_sms_result("missing-id"))
        assert "No SMS relay request" in unknown
