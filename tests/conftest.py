"""Shared test fixtures.

Sets the same env defaults every test file used to set individually (the
app modules read config at import time, and conftest is imported first).

The chat router schedules background fact extraction after every cleanly
completed turn (app/extraction.py). That background task races the
TestClient's lifespan teardown in chat tests that don't care about it,
so it is stubbed out here by default — extraction has its own dedicated
tests that exercise the real functions directly.
"""

import os

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

from types import SimpleNamespace

import pytest

from app.routers import chat as chat_router


@pytest.fixture(autouse=True)
def _no_background_extraction(monkeypatch):
    monkeypatch.setattr(
        chat_router,
        "extraction",
        SimpleNamespace(schedule=lambda conversation_id: None),
    )
