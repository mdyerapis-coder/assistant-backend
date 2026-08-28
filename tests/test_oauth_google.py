"""Tests for the Google OAuth flow and calendar/gmail tools."""

import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")
os.environ.setdefault(
    "GOOGLE_TOKEN_ENCRYPTION_KEY",
    "YrMWBFJqEufUV1H5at3Nqbqb2d1tHXDzdQPy3YJDUeY=",
)

import base64
import json

import pytest

from app import db
from app.routers import oauth_google
from app.tools import calendar, gmail  # noqa: F401  ensures tools are registered


@pytest.fixture(autouse=True)
async def _db():
    await db.connect()
    yield
    await db.disconnect()


# --- CSRF state ---


@pytest.mark.asyncio
async def test_store_and_consume_state():
    await oauth_google._store_state("state-abc")
    assert await oauth_google._consume_state("state-abc") is True
    # State is single-use
    assert await oauth_google._consume_state("state-abc") is False


@pytest.mark.asyncio
async def test_consume_unknown_state_returns_false():
    assert await oauth_google._consume_state("never-stored") is False


@pytest.mark.asyncio
async def test_consume_expired_state_returns_false():
    # Manually insert an expired state
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO oauth_states (state, created_at, expires_at) VALUES (?, ?, ?)",
        ("expired-state", "2020-01-01T00:00:00+00:00", "2020-01-01T00:01:00+00:00"),
    )
    await conn.commit()
    assert await oauth_google._consume_state("expired-state") is False


# --- Token encryption ---


@pytest.mark.asyncio
async def test_encrypt_decrypt_roundtrip():
    plaintext = "ya29.a0Aa7pCaQVkSAMPLE_ACCESS_TOKEN"
    encrypted = oauth_google._encrypt(plaintext)
    assert isinstance(encrypted, bytes)
    assert encrypted != plaintext.encode()
    assert oauth_google._decrypt(encrypted) == plaintext


@pytest.mark.asyncio
async def test_decrypt_garbage_raises():
    with pytest.raises(Exception):
        oauth_google._decrypt(b"not-valid-ciphertext")


# --- OAuth status (no tokens stored) ---


@pytest.mark.asyncio
async def test_status_not_connected():
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(oauth_google.router)

    client = TestClient(app)
    resp = client.get(
        "/oauth/google/status",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"connected": False}


# --- Calendar tool when not connected ---


@pytest.mark.asyncio
async def test_list_todays_calendar_not_connected():
    result = await calendar._list_today_events()
    assert "not connected" in result.lower()


@pytest.mark.asyncio
async def test_list_upcoming_calendar_events_not_connected():
    result = await calendar._list_upcoming_events(days=3)
    assert "not connected" in result.lower()


# --- Gmail tool when not connected ---


@pytest.mark.asyncio
async def test_list_unread_emails_not_connected():
    result = await gmail._list_unread_emails(max_results=5)
    assert "not connected" in result.lower()


@pytest.mark.asyncio
async def test_send_email_not_connected():
    result = await gmail._send_email(
        to="test@example.com",
        subject="hi",
        body="hello",
    )
    assert "not connected" in result.lower()


# --- Tools are registered ---


def test_calendar_tools_registered():
    from app.tools import registry
    names = {t.name for t in registry.always_visible_tools()}
    assert "list_todays_calendar" in names
    assert "list_upcoming_calendar_events" in names


def test_gmail_tools_registered():
    from app.tools import registry
    names = {t.name for t in registry.always_visible_tools()}
    assert "list_unread_emails" in names
    assert "send_email" in names
